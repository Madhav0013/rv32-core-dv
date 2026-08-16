#!/bin/bash
set -e

# The WSL ext4 filesystem is corrupted and failing with I/O errors under heavy disk use.
# We will download and extract directly to the Windows-mounted directory to bypass the corrupted VHDX.
TOOLS_DIR="/mnt/d/projects/rv32-core-dv/formal_tools"
mkdir -p "$TOOLS_DIR"
cd "$TOOLS_DIR"

echo "==> Downloading OSS CAD Suite..."
wget -q -O oss-cad-suite-linux-x64-20231201.tgz https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2023-12-01/oss-cad-suite-linux-x64-20231201.tgz

echo "==> Extracting OSS CAD Suite..."
tar -xzf oss-cad-suite-linux-x64-20231201.tgz

echo "==> Cloning riscv-formal..."
if [ ! -d "riscv-formal" ]; then
    git clone https://github.com/YosysHQ/riscv-formal.git
else
    echo "riscv-formal already exists, skipping clone."
fi

echo "==> Setup complete!"
echo "Source the environment using: source $TOOLS_DIR/oss-cad-suite/environment"
