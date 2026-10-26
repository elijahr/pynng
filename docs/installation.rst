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
``libclang`` at build time. headerkit requires Python 3.11+; a build with
Python 3.10 uses CFFI declarations that are pre-generated for the bundled nng
versions and does not need ``libclang``.

On Ubuntu/Debian:

.. code-block:: bash

   sudo apt install ninja-build libclang-dev

On macOS, Xcode's bundled ``libclang`` is usually sufficient. If you encounter
issues with ``llvm-ranlib``, see the troubleshooting section below.

On Windows, the build process installs LLVM automatically via Chocolatey during
CI. For local builds, install LLVM from https://releases.llvm.org/.

Customizing the build
---------------------

pynng uses CMake cache variables to configure which versions of NNG and mbedTLS
are fetched and built. You can override these at install time using
`scikit-build-core config-settings <https://scikit-build-core.readthedocs.io/en/stable/configuration/>`_:

.. code-block:: bash

   # Build against a specific NNG version
   pip install -Ccmake.define.NNG_REV=v1.12 .

   # Build against a fork or custom repository
   pip install -Ccmake.define.NNG_REPO=https://github.com/myorg/nng .

   # Override mbedTLS version
   pip install -Ccmake.define.MBEDTLS_REV=v3.6.5 .

Available options:

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Default
     - Description
   * - ``NNG_REPO``
     - ``https://github.com/nanomsg/nng``
     - Git URL of the NNG repository to build from
   * - ``NNG_REV``
     - ``v1.12.5``
     - Git tag, branch, or commit of NNG to use
   * - ``MBEDTLS_REPO``
     - ``https://github.com/ARMmbed/mbedtls.git``
     - Git URL of the mbedTLS repository
   * - ``MBEDTLS_REV``
     - ``v3.6.5``
     - Git tag, branch, or commit of mbedTLS to use

Multiple options can be combined:

.. code-block:: bash

   pip install \
     -Ccmake.define.NNG_REPO=https://github.com/myorg/nng \
     -Ccmake.define.NNG_REV=my-branch \
     .

Troubleshooting
---------------

macOS: ``llvm-ranlib`` error
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the build fails with an error related to ``llvm-ranlib`` or static archive
symbol indexing on macOS, either configure CMake to use Apple's system ``ranlib``
or ensure Homebrew LLVM's bin directory is on your ``PATH``:

.. code-block:: bash

   pip install -Ccmake.define.CMAKE_RANLIB=/usr/bin/ranlib .
   # Or when using Homebrew LLVM:
   brew install llvm
   export PATH="/opt/homebrew/opt/llvm/bin:$PATH"

Linux: ``libclang`` not found
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If headerkit cannot find ``libclang``:

.. code-block:: bash

   sudo apt install libclang-dev
   # or install the headerkit helper:
   python -m headerkit.install_libclang
