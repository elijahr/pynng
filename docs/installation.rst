Installation
============

From PyPI
---------

.. code-block:: bash

   pip install pynng

From source (development)
-------------------------

.. code-block:: bash

   git clone https://github.com/codypiersall/pynng
   cd pynng
   uv pip install -e '.[dev]'

Build Options
-------------

TLS Engine
^^^^^^^^^^

pynng supports multiple TLS engines. The default is mbedTLS, which is fetched and
built from source automatically. You can select a different engine at build time
via the ``PYNNG_TLS_ENGINE`` CMake option:

.. code-block:: bash

   # mbedTLS (default) -- fetched and built from source
   pip install pynng

   # wolfSSL -- fetched and built from source
   pip install pynng -C cmake.args="-DPYNNG_TLS_ENGINE=wolf"

   # OpenSSL 3.5+ -- uses system OpenSSL (nng v2 only; v1 built without TLS)
   pip install pynng -C cmake.args="-DPYNNG_TLS_ENGINE=openssl"

   # No TLS -- disables TLS entirely
   pip install pynng -C cmake.args="-DPYNNG_TLS_ENGINE=none"

.. list-table:: TLS Engine Support
   :header-rows: 1

   * - Engine
     - NNG v1
     - NNG v2
     - Source
   * - ``mbed`` (default)
     - Yes
     - Yes
     - Built from source
   * - ``wolf``
     - Yes
     - Yes
     - Built from source
   * - ``openssl``
     - No
     - Yes (3.5+)
     - System library
   * - ``none``
     - --
     - --
     - N/A

.. note::

   When ``openssl`` is selected, NNG v1 is built without TLS support because
   NNG v1 has no OpenSSL backend. NNG v2 sockets will have full TLS support
   via the system OpenSSL.

Disabling NNG v2
^^^^^^^^^^^^^^^^

By default, both NNG v1 and v2 CFFI modules are built. To build only v1:

.. code-block:: bash

   pip install pynng -C cmake.args="-DBUILD_NNG_V2=OFF"

Build Requirements
------------------

pynng uses `scikit-build-core <https://scikit-build-core.readthedocs.io>`_ and
`headerkit <https://github.com/codypiersall/headerkit>`_ for building. The build
process parses NNG C headers to auto-generate CFFI bindings, which requires
``libclang`` at build time.

On Ubuntu/Debian:

.. code-block:: bash

   sudo apt install ninja-build libclang-dev

On macOS, Xcode's bundled ``libclang`` is usually sufficient. If you encounter
issues with ``llvm-ranlib``, see the troubleshooting section below.

On Windows, the build process installs LLVM automatically via Chocolatey during
CI. For local builds, install LLVM from https://releases.llvm.org/.

Troubleshooting
---------------

macOS: ``llvm-ranlib`` error
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the build fails with an error related to ``llvm-ranlib``, you may need to
install LLVM via Homebrew and configure your path:

.. code-block:: bash

   brew install llvm
   export PATH="/opt/homebrew/opt/llvm/bin:$PATH"

Linux: ``libclang`` not found
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If headerkit cannot find ``libclang``:

.. code-block:: bash

   sudo apt install libclang-dev
   # or install the headerkit helper:
   python -m headerkit.install_libclang
