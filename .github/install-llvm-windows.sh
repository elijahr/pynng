#!/bin/bash
# Install LLVM/libclang on Windows for cibuildwheel builds.
# Detects architecture and installs the matching LLVM build:
#   - ARM64: Downloads native woa64 installer from LLVM GitHub releases
#   - x64: Uses chocolatey
set -e

LLVM_VERSION="21.1.8"

if [ "$PROCESSOR_ARCHITECTURE" = "ARM64" ]; then
    echo "Detected ARM64 Windows, downloading native LLVM ${LLVM_VERSION}..."
    curl -sSL -o /tmp/llvm.exe \
        "https://github.com/llvm/llvm-project/releases/download/llvmorg-${LLVM_VERSION}/LLVM-${LLVM_VERSION}-woa64.exe"
    echo "Installing LLVM silently..."
    powershell -Command "Start-Process 'C:\tmp\llvm.exe' -ArgumentList '/S' -Wait"
    rm -f /tmp/llvm.exe
    echo "LLVM ${LLVM_VERSION} ARM64 installed."
else
    echo "Detected x64 Windows, installing LLVM via chocolatey..."
    choco install llvm -y
fi
