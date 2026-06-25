# pynng

Python CFFI bindings for [nng](https://nng.nanomsg.org/) (nanomsg-next-gen), providing Pythonic access to the Scalability Protocols for inter-process and inter-machine messaging.

## Quick Reference

| Item | Value |
|------|-------|
| Version | 0.8.1+dev |
| Python | >= 3.6 |
| License | MIT |
| Upstream | codypiersall/pynng |
| This fork | elijahr/pynng |
| Build backend | scikit-build-core (CMake + CFFI) |
| Runtime deps | cffi, sniffio |
| Test command | `pytest test/` |
| Dev install | `pip install -v -e '.[dev]'` |

## Architecture

```
User Code
    |
pynng Python API  (pynng/nng.py, pynng/_aio.py, pynng/tls.py, ...)
    |
CFFI bindings     (pynng/_nng.so - generated at build time)
    |
nng C library     (static, fetched via CMake FetchContent)
    |
mbedTLS           (static, fetched via CMake FetchContent, provides TLS)
```

### Build Pipeline

1. CMake FetchContent downloads nng (from elijahr/nng fork) and mbedTLS
2. CMake builds nng as a static library with TLS enabled
3. `build_pynng.py` preprocesses nng C headers via `preprocess.py` (uses native C preprocessor + pycparser AST)
4. CFFI generates `_nng.c` from the preprocessed declarations
5. CMake compiles `_nng.c` and links it against static nng to produce `_nng.so`
6. scikit-build-core packages everything into a wheel

### Key Files

| File | Purpose |
|------|---------|
| `pynng/nng.py` | Core: Socket, all protocol subclasses, Context, Dialer, Listener, Pipe, Message, option descriptors |
| `pynng/_aio.py` | Async I/O: AIOHelper, asyncio/trio bridges, C callback dispatch |
| `pynng/exceptions.py` | Exception hierarchy mapped from nng errno values, `check_err()` |
| `pynng/options.py` | Low-level C option getter/setter dispatch |
| `pynng/tls.py` | TLSConfig wrapping nng_tls_config |
| `pynng/sockaddr.py` | Socket address type wrappers |
| `build_pynng.py` | CFFI FFI builder - preprocesses headers, generates cdef |
| `preprocess.py` | C header preprocessor (native preprocessor + pycparser AST cleaning) |
| `CMakeLists.txt` | CMake build: FetchContent for nng/mbedTLS, CFFI generation, extension linking |
| `pyproject.toml` | Build config (scikit-build-core), project metadata, test config, cibuildwheel |

## Build System

### Local Development Build

```bash
# Prerequisites: CMake >= 3.18, a C compiler, ninja (recommended)
pip install -v -e '.[dev]'
```

This invokes scikit-build-core which runs CMake. The build directory is `./build/{cache_tag}` (e.g., `build/cpython-312`).

### Clean Rebuild

Delete the build directory for your Python version:
```bash
rm -rf build/cpython-*
pip install -v -e '.[dev]'
```

### Platform Notes

- **macOS**: Builds universal2 (x86_64 + arm64). Uses clang as preprocessor. Requires `stubs/darwin-include/` for header preprocessing.
- **Linux**: Uses gcc/clang. May need `-latomic` on non-x86 architectures.
- **Windows**: Links Ws2_32, Advapi32, Bcrypt. Requires `bash .github/rmstuff.sh` between architecture builds.

## Fork and Upstream Context

This repo (`elijahr/pynng`) is a fork of `codypiersall/pynng`. The CMakeLists.txt fetches nng from `elijahr/nng` (branch `mbedtls-3.6.3-fix`) rather than upstream `nanomsg/nng` because the mbedTLS 3.6.3 handshake fix (PR #2128) has been merged to upstream `main` (NNG 2.0) but NOT backported to any stable release. The fork remains necessary until a stable NNG release includes the fix.

## Supported Protocols

| Protocol | Classes | Pattern |
|----------|---------|---------|
| Bus | Bus0 | Many-to-many mesh |
| Pair | Pair0, Pair1 | One-to-one (Pair1 supports polyamorous mode) |
| Pipeline | Push0, Pull0 | One-way with load balancing |
| Pub/Sub | Pub0, Sub0 | Topic-based publish/subscribe |
| Req/Rep | Req0, Rep0 | Request/response (supports Contexts for multiplexing) |
| Survey | Surveyor0, Respondent0 | One-to-many query/response |

## Key Design Patterns

### Error Handling
Every C function call is checked immediately with `check_err(ret)` which raises the appropriate `NNGException` subclass. Never check return values manually.

### Memory Management
Critical patterns that MUST be followed:
1. **Socket cleanup**: `close()` in `__del__` and `__exit__`. Guard with `hasattr(self, "_socket")`.
2. **Message single-use**: `Message._mem_freed` flag + lock prevents double-free SEGFAULT. Once sent, a Message's C memory is owned by nng.
3. **String option free**: `nng_strfree()` after `nng_*_get_string()`.
4. **AIO cleanup**: Set `self.aio = None` after `nng_aio_free()` to prevent double-free.
5. **Pipe copy**: Copy pipe struct value (`self._pipe[0] = lib_pipe`) to avoid memory corruption in callbacks.
6. **Global AIO map**: `_aio_map` dict keeps Python callbacks alive while C async operations are pending.

### Option Descriptors
Socket/Dialer/Listener/Pipe options use Python descriptors (`IntOption`, `MsOption`, `StringOption`, etc.) declared as class attributes. The descriptor's `__get__`/`__set__` dispatch to the correct `nng_{type}_{get|set}_{opttype}` C function.

### Async Support
`sniffio.current_async_library()` auto-detects asyncio/trio. `AIOHelper` wraps `nng_aio` and bridges C callbacks to the active event loop via `_aio_map` + `call_soon_threadsafe` (asyncio) or `run_sync_soon` (trio).

## CI

- **cibuildwheel.yml**: Builds wheels on ubuntu-20.04, windows-2019, macos-13. Tests with pytest.
- **smoketest.yml**: Fast CI on ubuntu-latest, Python 3.8 only.
- Concurrency: cancels in-progress runs on new pushes.

## stubs/ Directory

Contains fake C standard library headers for the preprocessor:
- `stubs/include/`: Cross-platform pycparser-compatible stubs (stdio.h, stdlib.h, etc.)
- `stubs/darwin-include/`: macOS-specific Darwin header stubs

These allow `preprocess.py` to run the native C preprocessor without pulling in platform-specific types that would break CFFI declarations.
