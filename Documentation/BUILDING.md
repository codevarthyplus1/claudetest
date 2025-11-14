# Building DistFS-KVM

## Prerequisites

### System Requirements

- Linux kernel 4.14 or later (5.4+ recommended)
- Kernel headers for your running kernel
- GCC compiler
- Make
- Root/sudo access for module loading

### Install Prerequisites

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install build-essential linux-headers-$(uname -r)
```

**RHEL/CentOS/Fedora:**
```bash
sudo yum install gcc make kernel-devel kernel-headers
# or on Fedora:
sudo dnf install gcc make kernel-devel kernel-headers
```

**Arch Linux:**
```bash
sudo pacman -S base-devel linux-headers
```

## Building

### Quick Build

```bash
# Clone repository
git clone https://github.com/distfs/distfs-kvm.git
cd distfs-kvm

# Build everything
make

# This builds:
# - Kernel module: distfs-kvm.ko
# - Management tool: tools/distfs-kvm
# - Cluster daemon: tools/distfs-kvmd
```

### Build Options

**Debug build with symbols:**
```bash
make DEBUG=1
```

**Build for specific kernel:**
```bash
make KERNEL_DIR=/usr/src/linux-headers-5.15.0-generic
```

**Build only kernel module:**
```bash
make module
```

**Build only userspace tools:**
```bash
make tools
```

## Installing

### Install Kernel Module

```bash
sudo make install
```

This installs the module to `/lib/modules/$(uname -r)/extra/`

### Install Userspace Tools

```bash
sudo make install-tools
```

This installs tools to:
- `/usr/local/bin/distfs-kvm`
- `/usr/local/sbin/distfs-kvmd`

## Loading the Module

### Manual Loading

```bash
# Load module
sudo modprobe distfs-kvm

# Verify it's loaded
lsmod | grep distfs_kvm

# Check dmesg for initialization messages
dmesg | tail -20
```

### Load with Parameters

```bash
sudo modprobe distfs-kvm debug=1 max_devices=128
```

### Auto-load on Boot

Create `/etc/modules-load.d/distfs-kvm.conf`:
```
distfs-kvm
```

Create `/etc/modprobe.d/distfs-kvm.conf` for parameters:
```
options distfs-kvm debug=0 max_devices=256
```

## Testing the Build

```bash
# Quick test (builds and tests loading)
make test

# This will:
# 1. Build the module
# 2. Load it with debug=1
# 3. Show dmesg output
# 4. Show module info
# 5. Unload it
```

## Troubleshooting Build Issues

### Kernel Headers Not Found

**Error:**
```
make: *** /lib/modules/5.x.x/build: No such file or directory
```

**Solution:**
```bash
# Install kernel headers matching your kernel
sudo apt-get install linux-headers-$(uname -r)
```

### Compilation Errors

**Check kernel version:**
```bash
uname -r  # Should be 4.14+
```

**Ensure headers match running kernel:**
```bash
ls -l /lib/modules/$(uname -r)/build
```

### Module Won't Load

**Check dmesg for errors:**
```bash
dmesg | tail -50
```

**Verify module info:**
```bash
modinfo distfs-kvm.ko
```

**Check for missing symbols:**
```bash
sudo modprobe -v distfs-kvm
```

## Development Build

For development with debugging:

```bash
# Build with debug symbols and logging
make clean
make DEBUG=1

# Load with debug output
sudo insmod distfs-kvm.ko debug=1

# Watch kernel log
sudo dmesg -w | grep distfs-kvm
```

## Code Style Check

```bash
# Check code style against kernel standards
make checkpatch
```

## Cleaning

```bash
# Clean all build artifacts
make clean

# This removes:
# - *.o, *.ko files
# - Temporary build files
# - Compiled tools
```

## Cross-Compilation

To build for a different architecture:

```bash
# Set ARCH and CROSS_COMPILE
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     KERNEL_DIR=/path/to/kernel/headers
```

## Next Steps

After building and installing:

1. Load the module: `sudo modprobe distfs-kvm`
2. Set up cluster services: See `README.md`
3. Create a block device: `sudo distfs-kvm create -n test -s 10G`
4. Use with KVM: See `Documentation/KVM_USAGE.md`
