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

### Multi-Host Distributed Architecture

DistFS-KVM creates block devices that span multiple physical hosts. Any KVM host in the cluster can access any device, enabling seamless VM live migration.

```
┌─────────────────────────── DISTRIBUTED CLUSTER ───────────────────────────┐
│                                                                            │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌────────────────┐│
│  │   KVM Host 1        │    │   KVM Host 2        │    │   KVM Host 3   ││
│  │                     │    │                     │    │                ││
│  │ ┌─────────────────┐ │    │ ┌─────────────────┐ │    │ ┌────────────┐ ││
│  │ │ VM1             │ │    │ │ VM2             │ │    │ │ VM3        │ ││
│  │ │ /dev/vda        │ │    │ │ /dev/vda        │ │    │ │ /dev/vda   │ ││
│  │ └────────┬────────┘ │    │ └────────┬────────┘ │    │ └─────┬──────┘ ││
│  │          │          │    │          │          │    │       │        ││
│  │ ┌────────▼────────┐ │    │ ┌────────▼────────┐ │    │ ┌─────▼──────┐ ││
│  │ │ /dev/distfs-0   │ │    │ │ /dev/distfs-1   │ │    │ │/dev/distfs-││
│  │ │                 │ │    │ │                 │ │    │ │     0      │ ││
│  │ │ DistFS Module   │ │    │ │ DistFS Module   │ │    │ │ DistFS Mod │ ││
│  │ └────────┬────────┘ │    │ └────────┬────────┘ │    │ └─────┬──────┘ ││
│  └──────────┼──────────┘    └──────────┼──────────┘    └───────┼────────┘│
│             │                          │                        │         │
│             └──────────────┬───────────┴────────────────────────┘         │
│                            │ Cluster Network                              │
│            ┌───────────────┼────────────────────┐                         │
│            │               │                    │                         │
│     ┌──────▼──────┐ ┌─────▼──────┐     ┌──────▼──────┐                  │
│     │  Metadata   │ │  Storage   │     │  Storage    │                   │
│     │   Server    │ │   Node 1   │ ... │   Node N    │                   │
│     │             │ │            │     │             │                   │
│     │ - Volume    │ │ - Chunks:  │     │ - Chunks:   │                   │
│     │   registry  │ │   0,3,6... │     │   1,4,7...  │                   │
│     │ - Chunk     │ │ - Replicas │     │ - Replicas  │                   │
│     │   mapping   │ │            │     │             │                   │
│     └─────────────┘ └────────────┘     └─────────────┘                   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

Key Features of Multi-Host Design:
- Single device (e.g., /dev/distfs-0) accessible from ANY KVM host
- Chunks distributed across storage nodes for performance and redundancy
- VM can be live-migrated from Host1 → Host2 → Host3 seamlessly
- Same device name on all hosts (kernel module creates identical mapping)
- Storage nodes can be separate or co-located with KVM hosts
```

### How It Works

1. **Device Creation**: Create a device once via any host:
   ```bash
   # On any KVM host in cluster
   sudo distfs-kvm create -n vm1-disk -s 50G -r 3
   ```

2. **Automatic Availability**: Device appears on ALL KVM hosts:
   ```bash
   # On KVM Host 1
   ls /dev/distfs-0  # ✓ Available

   # On KVM Host 2
   ls /dev/distfs-0  # ✓ Available (same device!)

   # On KVM Host 3
   ls /dev/distfs-0  # ✓ Available (same device!)
   ```

3. **Data Distribution**: Chunks spread across storage nodes:
   ```
   Device: vm1-disk (50GB)
   ├─ Chunk 0 → Storage Nodes [1, 2, 3]
   ├─ Chunk 1 → Storage Nodes [2, 3, 4]
   ├─ Chunk 2 → Storage Nodes [3, 4, 1]
   └─ ... (chunks distributed with replicas)
   ```

4. **Live Migration**:
   ```bash
   # VM running on Host 1 using /dev/distfs-0
   virsh migrate --live vm1 qemu+ssh://host2/system
   # VM now on Host 2, still using /dev/distfs-0 (same data!)
   ```

## Quick Start - Multi-Host Cluster

### Cluster Topology Example

```
Cluster Network: 192.168.1.0/24

┌──────────────────┬──────────────────┬──────────────────┐
│  192.168.1.10    │  192.168.1.20    │  192.168.1.30    │
│  Metadata Server │  KVM Host 1      │  KVM Host 2      │
│  + Storage       │  + Storage       │  + Storage       │
└──────────────────┴──────────────────┴──────────────────┘
```

### 1. Build and Install (on ALL KVM hosts)

```bash
# On each KVM host (192.168.1.20, 192.168.1.30, etc.)

# Build the kernel module
make

# Install
sudo make install
sudo depmod -a

# Load the module pointing to metadata server
sudo modprobe distfs-kvm metadata_server=192.168.1.10:7001

# Verify module loaded
lsmod | grep distfs_kvm
dmesg | tail -20
```

### 2. Start Cluster Services

**On Metadata Server (192.168.1.10):**
```bash
# Start metadata service
sudo distfs-kvmd --role metadata --bind 0.0.0.0:7001

# Also run storage on this node
sudo distfs-kvmd --role storage \
  --metadata 127.0.0.1:7001 \
  --storage-path /var/lib/distfs-kvm
```

**On KVM Host 1 (192.168.1.20):**
```bash
# Start storage service (co-located with KVM)
sudo distfs-kvmd --role storage \
  --metadata 192.168.1.10:7001 \
  --storage-path /var/lib/distfs-kvm
```

**On KVM Host 2 (192.168.1.30):**
```bash
# Start storage service (co-located with KVM)
sudo distfs-kvmd --role storage \
  --metadata 192.168.1.10:7001 \
  --storage-path /var/lib/distfs-kvm
```

### 3. Create Block Devices (from ANY host)

```bash
# Create device from KVM Host 1 (or any host)
sudo distfs-kvm create --name web-vm-disk --size 20G --replicas 3

# Device automatically appears on ALL hosts!

# On Host 1:
ls -l /dev/distfs-0  # ✓ Available

# On Host 2:
ls -l /dev/distfs-0  # ✓ Available (same device!)

# Create more devices
sudo distfs-kvm create --name db-vm-disk --size 100G --replicas 3
# Now /dev/distfs-1 available on all hosts
```

### 4. Use with VMs on Any Host

**On KVM Host 1 - Start a VM:**
```bash
# Use the block device with QEMU
qemu-system-x86_64 \
  -name web-vm \
  -drive file=/dev/distfs-0,format=raw,if=virtio \
  -m 2048 \
  -smp 2 \
  -enable-kvm

# Or with libvirt
virsh define web-vm.xml
virsh start web-vm
```

**On KVM Host 2 - Start another VM:**
```bash
# Use different device
qemu-system-x86_64 \
  -name db-vm \
  -drive file=/dev/distfs-1,format=raw,if=virtio \
  -m 4096 \
  -smp 4 \
  -enable-kvm
```

### 5. Live Migration Between Hosts

```bash
# VM running on Host 1 using /dev/distfs-0

# Migrate to Host 2 (storage follows automatically!)
virsh migrate --live web-vm qemu+ssh://192.168.1.30/system

# VM now running on Host 2, still accessing /dev/distfs-0
# No storage migration needed - same distributed device!

# Can migrate back to Host 1 or to any other host
virsh migrate --live web-vm qemu+ssh://192.168.1.20/system
```

### 6. Verify Cluster Status

```bash
# From any host, check cluster health
sudo distfs-kvm health

# List all devices (visible from all hosts)
sudo distfs-kvm list

# View statistics
cat /proc/distfs-kvm/stats
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
