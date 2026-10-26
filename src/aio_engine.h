// aio_engine.h - Native completion queue engine for pynng asynchronous I/O
//
// Thread-safe MPSC completion queue engine for nng asynchronous operations (nng_aio).
// Allows nng background worker threads to notify completed operations in pure C
// without acquiring Python's GIL or invoking Python runtime callbacks,
// eliminating GIL contention and PyPy foreign-thread context switch overhead.

#ifndef PYNNG_AIO_ENGINE_H
#define PYNNG_AIO_ENGINE_H

#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>

#if defined(_WIN32)
  #include <windows.h>
  #include <io.h>
#else
  #include <unistd.h>
  #include <fcntl.h>
  #include <pthread.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Constant wake-up byte passed to pipe write() to wake the asyncio event loop */
static const char _pynng_wake_byte = 1;

typedef struct pynng_aio_entry {
    void *aio;
    _Atomic(uintptr_t) slot_id;
    void *queue;
    struct pynng_aio_entry *next; /* link in the queue; guarded by the queue lock */
    _Atomic(int) state; /* 0 = IDLE, 1 = QUEUED, 2 = FREED */
} pynng_aio_entry_t;

/* Completed entries are linked through the entries themselves, so pushing a
   completion never allocates and cannot fail. Each entry carries one reference
   on its queue, so the queue outlives MPSCAIOEngine when it is finalized before
   the AIOHelper/DeviceAIO objects that use it. */
typedef struct pynng_mpsc_queue {
    pynng_aio_entry_t *head;
    pynng_aio_entry_t *tail;
    int closed;
    int write_fd;
    _Atomic(size_t) refcount;
#if defined(_WIN32)
    CRITICAL_SECTION cs;
#else
    pthread_mutex_t lock;
#endif
} pynng_mpsc_queue_t;

static void _pynng_mpsc_queue_lock(pynng_mpsc_queue_t *q) {
#if defined(_WIN32)
    EnterCriticalSection(&q->cs);
#else
    pthread_mutex_lock(&q->lock);
#endif
}

static void _pynng_mpsc_queue_unlock(pynng_mpsc_queue_t *q) {
#if defined(_WIN32)
    LeaveCriticalSection(&q->cs);
#else
    pthread_mutex_unlock(&q->lock);
#endif
}

static void _pynng_mpsc_queue_retain(pynng_mpsc_queue_t *q) {
    atomic_fetch_add_explicit(&q->refcount, 1, memory_order_relaxed);
}

/* Must be called without the queue lock held: the last release destroys it. */
static void _pynng_mpsc_queue_release(pynng_mpsc_queue_t *q, size_t n) {
    if (n == 0) return;
    if (atomic_fetch_sub_explicit(&q->refcount, n, memory_order_acq_rel) == n) {
#if defined(_WIN32)
        DeleteCriticalSection(&q->cs);
#else
        pthread_mutex_destroy(&q->lock);
#endif
        free(q);
    }
}

/* Unlinks queued entries (all of them when out_slot_ids is NULL) and frees
   those already marked FREED. Returns the number of freed entries, whose queue
   references the caller must release after unlocking. */
static size_t _pynng_mpsc_queue_pop(pynng_mpsc_queue_t *q, uintptr_t *out_slot_ids,
                                    int max_entries, int *count) {
    size_t freed = 0;
    *count = 0;
    while (q->head && (!out_slot_ids || *count < max_entries)) {
        pynng_aio_entry_t *entry = q->head;
        q->head = entry->next;
        if (!q->head) q->tail = NULL;
        entry->next = NULL;

        uintptr_t slot_id = atomic_load_explicit(&entry->slot_id, memory_order_acquire);
        int prev_state = atomic_exchange_explicit(&entry->state, 0, memory_order_acq_rel);
        if (prev_state == 2) {
            free(entry);
            freed++;
        } else if (out_slot_ids && slot_id != 0) {
            out_slot_ids[(*count)++] = slot_id;
        }
    }
    return freed;
}

pynng_mpsc_queue_t *pynng_mpsc_queue_new(int write_fd);
void pynng_mpsc_queue_close(pynng_mpsc_queue_t *q);
void pynng_mpsc_queue_free(pynng_mpsc_queue_t *q);
pynng_aio_entry_t *pynng_aio_entry_new(void *aio, uintptr_t slot_id, pynng_mpsc_queue_t *q);
void pynng_aio_entry_set_slot_id(pynng_aio_entry_t *e, uintptr_t slot_id);
int pynng_aio_entry_is_idle(pynng_aio_entry_t *e);
void pynng_aio_entry_free(pynng_aio_entry_t *e);
void pynng_native_aio_complete(void *arg);
int pynng_mpsc_drain_batch(pynng_mpsc_queue_t *q, uintptr_t *out_slot_ids, int max_entries);

pynng_mpsc_queue_t *pynng_mpsc_queue_new(int write_fd) {
    pynng_mpsc_queue_t *q = (pynng_mpsc_queue_t *)malloc(sizeof(pynng_mpsc_queue_t));
    if (q) {
        q->head = NULL;
        q->tail = NULL;
        q->closed = 0;
        q->write_fd = write_fd;
        atomic_init(&q->refcount, 1);
#if defined(_WIN32)
        InitializeCriticalSection(&q->cs);
#else
        pthread_mutex_init(&q->lock, NULL);
#endif
    }
    return q;
}

/* ZERO-GIL MPSC PUSH - Thread-safe, non-blocking on uncontended mutex */
void pynng_native_aio_complete(void *arg) {
    pynng_aio_entry_t *entry = (pynng_aio_entry_t *)arg;
    if (!entry) return;
    pynng_mpsc_queue_t *q = (pynng_mpsc_queue_t *)entry->queue;
    if (!q) return;

    _pynng_mpsc_queue_lock(q);

    /* Atomically transition IDLE (0) -> QUEUED (1).
       If already QUEUED (1) or FREED (2), do not push a second time. */
    int expected = 0;
    if (!q->closed && atomic_compare_exchange_strong_explicit(
            &entry->state, &expected, 1,
            memory_order_acq_rel, memory_order_acquire)) {
        entry->next = NULL;
        if (q->tail) {
            q->tail->next = entry;
        } else {
            q->head = entry;
        }
        q->tail = entry;

        /* Written under the lock: pynng_mpsc_queue_close() takes the lock, so
           once it returns the owner can close the fd and no write can reach a
           reused descriptor. The fd is non-blocking. */
        if (q->write_fd >= 0) {
#if defined(_WIN32)
            (void)_write(q->write_fd, &_pynng_wake_byte, 1);
#else
            (void)write(q->write_fd, &_pynng_wake_byte, 1);
#endif
        }
    }

    _pynng_mpsc_queue_unlock(q);
}

void pynng_mpsc_queue_close(pynng_mpsc_queue_t *q) {
    if (!q) return;
    int count;
    _pynng_mpsc_queue_lock(q);
    q->closed = 1;
    q->write_fd = -1;
    size_t freed = _pynng_mpsc_queue_pop(q, NULL, 0, &count);
    _pynng_mpsc_queue_unlock(q);
    _pynng_mpsc_queue_release(q, freed);
}

void pynng_mpsc_queue_free(pynng_mpsc_queue_t *q) {
    if (!q) return;
    pynng_mpsc_queue_close(q);
    _pynng_mpsc_queue_release(q, 1);
}

int pynng_mpsc_drain_batch(pynng_mpsc_queue_t *q, uintptr_t *out_slot_ids, int max_entries) {
    if (!q || !out_slot_ids || max_entries <= 0) return 0;
    int count;
    _pynng_mpsc_queue_lock(q);
    size_t freed = _pynng_mpsc_queue_pop(q, out_slot_ids, max_entries, &count);
    _pynng_mpsc_queue_unlock(q);
    _pynng_mpsc_queue_release(q, freed);
    return count;
}

pynng_aio_entry_t *pynng_aio_entry_new(void *aio, uintptr_t slot_id, pynng_mpsc_queue_t *q) {
    pynng_aio_entry_t *e = (pynng_aio_entry_t *)malloc(sizeof(pynng_aio_entry_t));
    if (e) {
        e->aio = aio;
        atomic_init(&e->slot_id, slot_id);
        if (q) _pynng_mpsc_queue_retain(q);
        e->queue = q;
        e->next = NULL;
        atomic_init(&e->state, 0);
    }
    return e;
}

void pynng_aio_entry_set_slot_id(pynng_aio_entry_t *e, uintptr_t slot_id) {
    if (e) {
        atomic_store_explicit(&e->slot_id, slot_id, memory_order_release);
    }
}

int pynng_aio_entry_is_idle(pynng_aio_entry_t *e) {
    if (!e) return 0;
    return atomic_load_explicit(&e->state, memory_order_acquire) == 0;
}

void pynng_aio_entry_free(pynng_aio_entry_t *e) {
    if (!e) return;
    atomic_store_explicit(&e->slot_id, 0, memory_order_release);
    pynng_mpsc_queue_t *q = (pynng_mpsc_queue_t *)e->queue;
    if (q) {
        _pynng_mpsc_queue_lock(q);
        /* A QUEUED entry is freed by whoever unlinks it from the queue. */
        int prev_state = atomic_exchange_explicit(&e->state, 2, memory_order_acq_rel);
        if (prev_state == 0) {
            free(e);
        }
        _pynng_mpsc_queue_unlock(q);
        if (prev_state == 0) {
            _pynng_mpsc_queue_release(q, 1);
        }
    } else {
        free(e);
    }
}

#ifdef __cplusplus
}
#endif

#endif /* PYNNG_AIO_ENGINE_H */
