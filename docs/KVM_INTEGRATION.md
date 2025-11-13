# DistFS KVM/QEMU Integration Guide

Complete guide for using DistFS as a storage backend for KVM-based virtual machines.

## Overview

DistFS provides native block device support for KVM/QEMU through the Network Block Device (NBD) protocol. This allows VMs to use distributed, replicated storage with high availability and performance.

## Architecture

```
┌─────────────────────┐
│   QEMU/KVM VM       │
│                     │
│  ┌──────────────┐   │
│  │  Guest OS    │   │
│  │  /dev/vda    │   │
│  └──────┬───────┘   │
│         │           │
│  ┌──────▼───────┐   │
│  │ VirtIO Disk  │   │
│  └──────┬───────┘   │
└─────────┼───────────┘
          │
    ┌─────▼──────┐
    │ /dev/nbd0  │  (Host NBD device)
    └─────┬──────┘
          │
    ┌─────▼──────┐
    │ NBD Server │
    └─────┬──────┘
          │
    ┌─────▼──────┐
    │   DistFS   │  (Distributed storage)
    │  Cluster   │
    └────────────┘
```

## Setup Methods

### Method 1: VM Manager (Recommended)

The easiest way to manage VMs with DistFS:

#### Create a VM

```bash
sudo distfs-vm --metadata-server localhost:7001 create \
  --name production-web \
  --disk-size 50G \
  --memory 4096 \
  --cpus 4 \
  --iso /path/to/os-installer.iso \
  --replicas 3
```

Options:
- `--name`: Unique VM name
- `--disk-size`: Disk size (K/M/G/T units)
- `--memory`: RAM in MB
- `--cpus`: Number of virtual CPUs
- `--iso`: Path to ISO for installation (optional)
- `--replicas`: Number of disk replicas (default: 2)

#### Start a VM

```bash
# Start with VNC access
sudo distfs-vm --metadata-server localhost:7001 start \
  --name production-web \
  --vnc-port 5900

# Start without graphics (serial console only)
sudo distfs-vm --metadata-server localhost:7001 start \
  --name production-web
```

#### Manage VMs

```bash
# List all VMs
sudo distfs-vm --metadata-server localhost:7001 list

# Stop a VM
sudo distfs-vm --metadata-server localhost:7001 stop --name production-web

# Delete VM (keeps disk)
sudo distfs-vm --metadata-server localhost:7001 delete --name production-web

# Delete VM and disk
sudo distfs-vm --metadata-server localhost:7001 delete \
  --name production-web \
  --delete-disk
```

### Method 2: Helper Script

For quick testing and custom QEMU configurations:

```bash
sudo kvm_integration/qemu_distfs_helper.sh run \
  my-volume \
  localhost:7001 \
  -m 2048 \
  -smp 2 \
  -vnc :0 \
  -boot d \
  -cdrom ubuntu-22.04.iso
```

The helper script handles:
- NBD server startup
- Device connection
- QEMU launch
- Cleanup on exit

### Method 3: Manual Integration

For full control:

#### Step 1: Create a Volume

```bash
distfs --metadata-server localhost:7001 create-volume \
  --name vm-disk-web01 \
  --size 30G \
  --replicas 2
```

#### Step 2: Start NBD Server

```bash
sudo python3 nbd_server.py \
  --volume vm-disk-web01 \
  --metadata-server localhost:7001 \
  --host 127.0.0.1 \
  --port 10809 &
```

#### Step 3: Connect NBD Client

```bash
# Load NBD module if needed
sudo modprobe nbd

# Connect to NBD server
sudo nbd-client 127.0.0.1 10809 /dev/nbd0
```

#### Step 4: (Optional) Format the Device

For new disks:

```bash
sudo mkfs.ext4 /dev/nbd0
```

#### Step 5: Launch QEMU

```bash
qemu-system-x86_64 \
  -name web01 \
  -m 2048 \
  -smp 2 \
  -drive file=/dev/nbd0,format=raw,if=virtio,cache=none \
  -net nic,model=virtio \
  -net user \
  -enable-kvm \
  -vnc :0
```

#### Step 6: Cleanup

```bash
# Disconnect NBD device
sudo nbd-client -d /dev/nbd0

# Stop NBD server
sudo pkill -f "nbd_server.py.*vm-disk-web01"
```

## Advanced Configuration

### Using libvirt

Create a libvirt domain XML with DistFS storage:

```xml
<domain type='kvm'>
  <name>distfs-vm</name>
  <memory unit='MiB'>2048</memory>
  <vcpu>2</vcpu>
  <os>
    <type arch='x86_64'>hvm</type>
    <boot dev='hd'/>
  </os>
  <devices>
    <disk type='block' device='disk'>
      <driver name='qemu' type='raw' cache='none'/>
      <source dev='/dev/nbd0'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='network'>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <graphics type='vnc' port='5900' listen='0.0.0.0'/>
  </devices>
</domain>
```

Use with virsh:

```bash
# Define the domain
virsh define distfs-vm.xml

# Start the VM
virsh start distfs-vm

# Connect console
virsh console distfs-vm
```

### Live Migration

DistFS supports VM live migration since storage is network-accessible:

#### Preparation

1. Ensure both hosts can access the metadata server
2. Both hosts should have NBD access to the volume
3. Configure shared networking

#### Migrate

```bash
# On source host: keep NBD connected

# On destination host: connect to same volume
sudo nbd-client 192.168.1.10 10809 /dev/nbd0

# Perform migration (if using libvirt)
virsh migrate --live distfs-vm qemu+ssh://dest-host/system

# Or with QEMU directly using the migrate command in monitor
```

### Snapshot and Backup

#### Create Volume Snapshot

While DistFS doesn't have built-in snapshots yet, you can:

1. **Create a new volume from existing:**

```bash
# Stop the VM
sudo distfs-vm --metadata-server localhost:7001 stop --name myvm

# Use dd over NBD to copy
sudo dd if=/dev/nbd0 | \
  python3 -c "
import sys
from distfs_client import DistFSClient

client = DistFSClient('localhost:7001')
client.create_volume('myvm-snapshot', '20G')

data = sys.stdin.buffer.read()
client.write_data('myvm-snapshot', 0, data)
"

# Restart VM
sudo distfs-vm --metadata-server localhost:7001 start --name myvm
```

2. **Export to image file:**

```bash
# Connected to /dev/nbd0
sudo qemu-img convert -f raw -O qcow2 /dev/nbd0 backup.qcow2
```

## Performance Optimization

### Cache Modes

Choose cache mode based on use case:

```bash
# No cache (safest for data integrity)
-drive file=/dev/nbd0,format=raw,cache=none

# Writeback (fastest, less safe)
-drive file=/dev/nbd0,format=raw,cache=writeback

# Writethrough (balanced)
-drive file=/dev/nbd0,format=raw,cache=writethrough
```

### I/O Threading

Enable I/O threads for better performance:

```bash
qemu-system-x86_64 \
  -object iothread,id=iothread0 \
  -drive file=/dev/nbd0,format=raw,if=none,id=drive0,cache=none,aio=native \
  -device virtio-blk-pci,drive=drive0,iothread=iothread0 \
  ...
```

### VirtIO SCSI

For better scalability with multiple disks:

```bash
qemu-system-x86_64 \
  -device virtio-scsi-pci,id=scsi0 \
  -drive file=/dev/nbd0,format=raw,if=none,id=hd0,cache=none \
  -device scsi-hd,drive=hd0,bus=scsi0.0 \
  ...
```

### Increase Replication for Performance

More replicas = more read sources:

```bash
distfs --metadata-server localhost:7001 create-volume \
  --name high-perf \
  --size 100G \
  --replicas 5
```

## Monitoring

### Check Disk I/O

Inside the VM:

```bash
iostat -x 1
```

### Monitor NBD Performance

On the host:

```bash
# Watch I/O stats
iostat -x /dev/nbd0 1

# Check process stats
pidstat -d 1 -p $(pgrep nbd_server)
```

### DistFS Metrics

```bash
# Check storage node stats
curl http://storage-node:7002/stats

# Check cluster health
distfs --metadata-server localhost:7001 health
```

## Troubleshooting

### VM Won't Start

1. **Check NBD device:**

```bash
ls -l /dev/nbd0
# Should show block device
```

2. **Verify NBD connection:**

```bash
sudo nbd-client -c /dev/nbd0
# Should show: Connected
```

3. **Check QEMU logs:**

```bash
tail -f ~/.distfs/vms/myvm-qemu.log
```

### Poor Performance

1. **Check cache mode:**

Use `cache=none` for best performance with DistFS.

2. **Verify KVM is enabled:**

```bash
qemu-system-x86_64 ... -enable-kvm

# Check if KVM is available
ls -l /dev/kvm
```

3. **Monitor network latency:**

```bash
ping -c 100 metadata-server
```

### NBD Connection Lost

If NBD disconnects:

```bash
# Reconnect
sudo nbd-client -d /dev/nbd0
sudo nbd-client 127.0.0.1 10809 /dev/nbd0

# Restart VM
sudo distfs-vm --metadata-server localhost:7001 start --name myvm
```

## Best Practices

1. **Use VirtIO drivers** in guests for best performance
2. **Set cache=none** for data consistency
3. **Enable KVM** for hardware acceleration
4. **Use multiple replicas** (≥2) for production VMs
5. **Monitor disk I/O** regularly
6. **Plan for network latency** in distributed setups
7. **Use dedicated network** for storage traffic in production
8. **Regular backups** using volume snapshots or exports
9. **Test failover** scenarios before production use
10. **Use VNC or serial console** for remote access

## Examples

### Example 1: Development VM

```bash
# Quick development VM with minimal resources
sudo distfs-vm --metadata-server localhost:7001 create \
  --name dev-vm \
  --disk-size 20G \
  --memory 2048 \
  --cpus 2

sudo distfs-vm --metadata-server localhost:7001 start \
  --name dev-vm \
  --vnc-port 5900
```

### Example 2: Production Database Server

```bash
# High-availability database VM
sudo distfs-vm --metadata-server prod-metadata:7001 create \
  --name db-primary \
  --disk-size 500G \
  --memory 16384 \
  --cpus 8 \
  --replicas 3

# Start with custom QEMU options
sudo kvm_integration/qemu_distfs_helper.sh run \
  vm-db-primary-disk \
  prod-metadata:7001 \
  -m 16384 \
  -smp 8 \
  -cpu host \
  -enable-kvm \
  -drive file=/dev/nbd0,format=raw,cache=none,aio=native,if=virtio
```

### Example 3: Multi-Disk VM

```bash
# Create multiple volumes
distfs --metadata-server localhost:7001 create-volume --name vm-os --size 50G
distfs --metadata-server localhost:7001 create-volume --name vm-data --size 200G

# Start NBD servers on different ports
sudo python3 nbd_server.py --volume vm-os --port 10809 --nbd-device /dev/nbd0 &
sudo python3 nbd_server.py --volume vm-data --port 10810 --nbd-device /dev/nbd1 &

# Launch QEMU with both disks
qemu-system-x86_64 \
  -drive file=/dev/nbd0,format=raw,if=virtio \
  -drive file=/dev/nbd1,format=raw,if=virtio \
  -m 4096 \
  -smp 4 \
  -enable-kvm
```

## Next Steps

- [Performance Tuning](PERFORMANCE.md)
- [High Availability Setup](HA_SETUP.md)
- [API Reference](API.md)
