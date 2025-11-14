# DistFS-KVM - Distributed Block Storage for KVM Virtual Machines

A Linux kernel module providing distributed block devices specifically designed for KVM virtual machines.

## Overview

DistFS-KVM is a distributed block device driver that provides replicated, high-available storage for KVM/QEMU virtual machines. Unlike traditional filesystem-based storage, DistFS-KVM operates at the block layer, providing raw block devices backed by distributed storage cluster.

**Key Features:**
- **KVM-optimized** - Purpose-built for virtual machine workloads
- **Distributed storage** - Data automatically replicated across nodes
- **High availability** - Automatic failover on node failures
- **Native performance** - Kernel-space implementation for minimal overhead
- **Live migration support** - Storage accessible from any cluster node
- **Simple management** - Easy device creation and management

## Architecture

```
┌──────────────────────────────────────────────────┐
│           KVM/QEMU Virtual Machine               │
│                                                  │
│   ┌──────────────────────────────────────────┐   │
│   │  Guest OS (sees /dev/vda, /dev/vdb, etc) │   │
│   └────────────────┬─────────────────────────┘   │
│                    │ virtio-blk                   │
└────────────────────┼──────────────────────────────┘
                     │
┌────────────────────▼──────────────────────────────┐
│              Host Linux Kernel                    │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │   /dev/distfs-0, /dev/distfs-1, ...      │    │
│  │   (Block devices for VMs)                │    │
│  └────────────────┬─────────────────────────┘    │
│  ┌────────────────▼─────────────────────────┐    │
│  │     DistFS-KVM Kernel Module             │    │
│  │  ┌────────────────────────────────────┐  │    │
│  │  │  Block Device Layer (blk-mq)       │  │    │
│  │  └───────────┬────────────────────────┘  │    │
│  │  ┌───────────▼────────────────────────┐  │    │
│  │  │  Chunk Manager & Replication       │  │    │
│  │  └───────────┬────────────────────────┘  │    │
│  │  ┌───────────▼────────────────────────┐  │    │
│  │  │  Network Layer (cluster comm)      │  │    │
│  │  └────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────┘    │
└───────────────────┬───────────────────────────────┘
                    │ Network (TCP/IP)
        ┌───────────┼───────────┐
        │           │           │
┌───────▼────┐ ┌───▼──────┐ ┌──▼───────┐
│  Storage   │ │ Storage  │ │ Storage  │
│  Node 1    │ │  Node 2  │ │  Node 3  │
│            │ │          │ │          │
│  Chunks    │ │ Chunks   │ │ Chunks   │
│  (replica) │ │ (replica)│ │ (replica)│
└────────────┘ └──────────┘ └──────────┘
```

## Quick Start

### 1. Build and Install

```bash
# Build the kernel module
make

# Install
sudo make install
sudo depmod -a

# Load the module
sudo modprobe distfs-kvm
```

### 2. Start Cluster Services

```bash
# On metadata server (one node)
sudo distfs-kvmd --role metadata --bind 0.0.0.0:7001

# On storage nodes (multiple nodes)
sudo distfs-kvmd --role storage \
  --metadata 192.168.1.10:7001 \
  --storage-path /var/lib/distfs-kvm
```

### 3. Create a Block Device for VM

```bash
# Create a 20GB block device
sudo distfs-kvm create --name vm1-disk --size 20G --replicas 3

# Block device appears at /dev/distfs-0
ls -l /dev/distfs-*
```

### 4. Use with KVM/QEMU

```bash
# Use the block device with QEMU
qemu-system-x86_64 \
  -drive file=/dev/distfs-0,format=raw,if=virtio \
  -m 2048 \
  -smp 2 \
  -enable-kvm

# Or with libvirt (edit VM XML)
<disk type='block' device='disk'>
  <driver name='qemu' type='raw' cache='none' io='native'/>
  <source dev='/dev/distfs-0'/>
  <target dev='vda' bus='virtio'/>
</disk>
```

## Why KVM-Specific?

Traditional distributed filesystems (Ceph, GlusterFS) provide POSIX filesystem interfaces, which adds overhead for VM workloads that only need block storage. DistFS-KVM is optimized for KVM by:

1. **No filesystem layer** - Direct block device, no POSIX overhead
2. **Optimized I/O path** - Minimal latency for VM disk operations
3. **VM-aware features** - Snapshots, clones, live migration support
4. **Simplified architecture** - Easier to deploy and manage for VM-only use
5. **Better performance** - Kernel-space, zero filesystem overhead

## Features

### Distributed Block Devices

```bash
# Create devices with various sizes and replication
sudo distfs-kvm create --name web-vm-disk --size 50G --replicas 2
sudo distfs-kvm create --name db-vm-disk --size 500G --replicas 3

# List all devices
sudo distfs-kvm list

# Get device info
sudo distfs-kvm info --name web-vm-disk

# Delete device
sudo distfs-kvm delete --name web-vm-disk
```

### Live Migration Support

Since storage is network-accessible, VMs can be migrated between nodes:

```bash
# On source node - VM using /dev/distfs-0

# On destination node - same device available
ls -l /dev/distfs-0

# Perform live migration
virsh migrate --live vm1 qemu+ssh://desthost/system
```

### Snapshots and Clones

```bash
# Create snapshot of a device
sudo distfs-kvm snapshot --device vm1-disk --name vm1-snap1

# Create clone from snapshot
sudo distfs-kvm clone --from vm1-snap1 --name vm2-disk

# List snapshots
sudo distfs-kvm snapshot-list --device vm1-disk
```

### High Availability

- Automatic replica placement across nodes
- Automatic failover on node failure
- Continues operation with degraded replicas
- Background replica synchronization

## Management

### Device Operations

```bash
# Create 100GB device with 3 replicas
sudo distfs-kvm create -n myvm-disk -s 100G -r 3

# Resize device (online resize supported)
sudo distfs-kvm resize -n myvm-disk -s 200G

# Change replication factor
sudo distfs-kvm set-replicas -n myvm-disk -r 5

# Delete device
sudo distfs-kvm delete -n myvm-disk
```

### Cluster Management

```bash
# List cluster nodes
sudo distfs-kvm nodes

# Check cluster health
sudo distfs-kvm health

# Add storage node
sudo distfs-kvmd --role storage --metadata 192.168.1.10:7001

# Remove node (graceful drain)
sudo distfs-kvm node-remove --id node-02
```

### Monitoring

```bash
# Show device statistics
sudo distfs-kvm stats -n myvm-disk

# Monitor cluster performance
sudo distfs-kvm monitor

# View kernel module stats
cat /proc/distfs-kvm/stats
cat /sys/module/distfs_kvm/parameters/*
```

## Configuration

### Module Parameters

```bash
# Load with custom parameters
sudo modprobe distfs-kvm \
  debug=1 \
  max_devices=256 \
  chunk_size=8388608

# Available parameters:
# - debug: Enable debug logging (0/1)
# - max_devices: Maximum number of devices (default: 256)
# - chunk_size: Chunk size in bytes (default: 4MB)
# - max_replicas: Maximum replicas per device (default: 8)
# - network_timeout: Network timeout in seconds (default: 30)
```

### Device Creation Options

```bash
# Full options example
sudo distfs-kvm create \
  --name production-db \
  --size 1T \
  --replicas 5 \
  --chunk-size 16M \
  --read-only false \
  --cache-mode writeback
```

## Performance Tuning

### For Sequential Workloads

```bash
# Larger chunk size
sudo distfs-kvm create -n seq-disk -s 100G --chunk-size 32M

# Adjust read-ahead
sudo blockdev --setra 16384 /dev/distfs-0
```

### For Random Workloads

```bash
# Smaller chunk size for better distribution
sudo distfs-kvm create -n random-disk -s 100G --chunk-size 2M

# Use none I/O scheduler
echo none > /sys/block/distfs0/queue/scheduler
```

### For Databases

```bash
# High replication for safety
sudo distfs-kvm create -n db-disk -s 500G -r 5

# Direct I/O, no cache
qemu-system-x86_64 \
  -drive file=/dev/distfs-0,format=raw,cache=none,aio=native
```

## Networking

### Port Usage

- **7001**: Metadata service
- **7002**: Storage node data transfer
- **7003**: Management API

### Firewall Configuration

```bash
# On all nodes
sudo firewall-cmd --permanent --add-port=7001-7003/tcp
sudo firewall-cmd --reload

# Or with iptables
sudo iptables -A INPUT -p tcp --dport 7001:7003 -j ACCEPT
```

## Troubleshooting

### Module Won't Load

```bash
# Check dependencies
modinfo distfs-kvm

# View load errors
dmesg | grep distfs-kvm

# Verify kernel version
uname -r  # Should be 4.14+
```

### Device Not Appearing

```bash
# Check if module loaded
lsmod | grep distfs_kvm

# View device creation logs
dmesg | tail -50

# Check cluster connectivity
sudo distfs-kvm health
```

### Poor Performance

```bash
# Check network latency to storage nodes
ping -c 100 <storage-node-ip>

# Monitor I/O stats
iostat -x 1 /dev/distfs-0

# Check for degraded replicas
sudo distfs-kvm info -n myvm-disk
```

### Connection Issues

```bash
# Test metadata server
telnet <metadata-server> 7001

# Check storage node connectivity
sudo distfs-kvm nodes

# View network errors
cat /proc/distfs-kvm/network_stats
```

## Development

### Building from Source

```bash
git clone https://github.com/distfs/distfs-kvm.git
cd distfs-kvm
make

# Debug build
make DEBUG=1

# With specific kernel
make KERNEL_DIR=/usr/src/linux-headers-5.15.0
```

### Testing

```bash
# Run unit tests
make test

# Integration tests
make integration-test

# Performance benchmarks
make bench
```

## System Requirements

- Linux kernel 4.14 or later (5.4+ recommended)
- x86_64 architecture
- Root/sudo access
- Network connectivity between cluster nodes
- Minimum 1GB RAM per storage node
- SSD recommended for metadata storage

## Security

- Deploy on private network or VPN
- Use firewall rules to restrict access
- Future: TLS encryption for network traffic
- Future: Authentication and authorization

## Roadmap

- [ ] Encryption at rest
- [ ] Encryption in transit (TLS)
- [ ] Authentication/authorization
- [ ] Erasure coding support
- [ ] Compression support
- [ ] Thin provisioning
- [ ] Storage tiering (SSD/HDD)
- [ ] NVMe-oF integration

## License

GPL v2 (required for Linux kernel modules)

## Documentation

- `Documentation/design.md` - Architecture and design
- `Documentation/protocol.md` - Network protocol specification
- `Documentation/performance.md` - Performance tuning guide
- `Documentation/kvm-libvirt.md` - Libvirt integration guide

## Support

- GitHub Issues: https://github.com/distfs/distfs-kvm/issues
- Mailing List: distfs-kvm@lists.example.com
- IRC: #distfs-kvm on Libera.Chat
