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

Build Requirements
------------------

pynng uses `scikit-build-core <https://scikit-build-core.readthedocs.io>`_ and
`headerkit <https://github.com/axiomantic/headerkit>`_ for building. The build
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
