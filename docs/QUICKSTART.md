# DistFS Quick Start Guide

Get up and running with DistFS in minutes!

## Prerequisites

- Linux system with kernel 3.10+ (for NBD support)
- Python 3.8 or higher
- Root/sudo access (for NBD operations)
- KVM/QEMU for virtual machine support

## Installation

### Single Node Setup

1. **Clone and setup:**

```bash
git clone <repository-url>
cd distfs
./setup.sh
```

The setup script will:
- Install dependencies (Python, NBD tools, QEMU)
- Create data directories
- Load kernel modules
- Install systemd services

2. **Start services:**

```bash
# Start metadata service
sudo systemctl start distfs-metadata

# Start storage service
sudo systemctl start distfs-storage

# Enable services to start on boot
sudo systemctl enable distfs-metadata distfs-storage
```

3. **Verify installation:**

```bash
distfs --metadata-server localhost:7001 health
```

Expected output:
```json
{
  "metadata_service": "healthy",
  "total_nodes": 1,
  "online_nodes": 1,
  "total_volumes": 0,
  "status": "healthy"
}
```

### Multi-Node Cluster Setup

For production deployments across multiple servers:

```bash
./deploy_cluster.sh \
  --metadata-node 192.168.1.10 \
  --storage-nodes 192.168.1.11,192.168.1.12,192.168.1.13 \
  --install-deps
```

See [CLUSTER_DEPLOYMENT.md](CLUSTER_DEPLOYMENT.md) for details.

## Basic Usage

### 1. Create a Volume

```bash
distfs --metadata-server localhost:7001 \
  create-volume \
  --name my-first-volume \
  --size 10G \
  --replicas 2
```

### 2. List Volumes

```bash
distfs --metadata-server localhost:7001 list-volumes
```

Output:
```
Name                 Size         Chunks   Replicas   Created
--------------------------------------------------------------------------------
my-first-volume      10.00 GB     2560     2          2025-01-13T10:30:00
```

### 3. Create and Start a VM

```bash
# Create VM
sudo distfs-vm --metadata-server localhost:7001 \
  create \
  --name ubuntu-vm \
  --disk-size 20G \
  --memory 2048 \
  --cpus 2 \
  --iso /path/to/ubuntu.iso

# Start VM
sudo distfs-vm --metadata-server localhost:7001 \
  start \
  --name ubuntu-vm \
  --vnc-port 5900
```

### 4. Connect to VM

```bash
# Via VNC
vncviewer localhost:5900

# Or via VNC client of your choice
```

### 5. Manage VMs

```bash
# List all VMs
sudo distfs-vm --metadata-server localhost:7001 list

# Stop a VM
sudo distfs-vm --metadata-server localhost:7001 stop --name ubuntu-vm

# Delete a VM (preserves disk)
sudo distfs-vm --metadata-server localhost:7001 delete --name ubuntu-vm

# Delete a VM and its disk
sudo distfs-vm --metadata-server localhost:7001 delete --name ubuntu-vm --delete-disk
```

## Using DistFS with QEMU Directly

### Method 1: Using the Helper Script

```bash
sudo kvm_integration/qemu_distfs_helper.sh run my-volume localhost:7001 \
  -m 2048 \
  -smp 2 \
  -vnc :0 \
  -cdrom ubuntu.iso
```

### Method 2: Manual NBD Setup

```bash
# Start NBD server
sudo python3 nbd_server.py \
  --volume my-volume \
  --metadata-server localhost:7001 \
  --port 10809 &

# Connect NBD client
sudo nbd-client 127.0.0.1 10809 /dev/nbd0

# Use with QEMU
qemu-system-x86_64 \
  -drive file=/dev/nbd0,format=raw,if=virtio \
  -m 2048 \
  -smp 2 \
  -enable-kvm

# Cleanup when done
sudo nbd-client -d /dev/nbd0
```

## Working with Block Devices

Once a volume is exposed via NBD, you can use it like any block device:

```bash
# Format with ext4
sudo mkfs.ext4 /dev/nbd0

# Mount
sudo mkdir /mnt/distfs
sudo mount /dev/nbd0 /mnt/distfs

# Use it
echo "Hello DistFS!" | sudo tee /mnt/distfs/test.txt

# Unmount
sudo umount /mnt/distfs
```

## Monitoring and Maintenance

### Check Cluster Health

```bash
distfs --metadata-server localhost:7001 health
```

### List Storage Nodes

```bash
distfs --metadata-server localhost:7001 list-nodes
```

Output:
```
Node ID                        Address                   Status     Capacity     Used
-----------------------------------------------------------------------------------------------
node-01-7002                  192.168.1.11:7002         online     100.00 GB    5.23 GB
node-02-7002                  192.168.1.12:7002         online     100.00 GB    5.18 GB
```

### View Volume Details

```bash
distfs --metadata-server localhost:7001 volume-info --name my-volume
```

### View Logs

```bash
# Metadata service logs
sudo journalctl -u distfs-metadata -f

# Storage service logs
sudo journalctl -u distfs-storage -f

# VM NBD logs
tail -f ~/.distfs/vms/ubuntu-vm-nbd.log
```

## Performance Tuning

### Increase Chunk Size

For large sequential I/O workloads:

```bash
# Start storage server with larger chunks
python3 storage_server.py \
  --chunk-size 16M \
  --data-dir /var/distfs/storage \
  --metadata-server localhost:7001
```

### Adjust Replication Factor

For higher availability, increase replicas:

```bash
distfs --metadata-server localhost:7001 \
  create-volume \
  --name critical-data \
  --size 50G \
  --replicas 3
```

For better performance with less redundancy:

```bash
distfs --metadata-server localhost:7001 \
  create-volume \
  --name temp-storage \
  --size 100G \
  --replicas 1
```

## Troubleshooting

### NBD Device Issues

If NBD devices are not available:

```bash
# Load NBD module
sudo modprobe nbd max_part=16

# Verify
ls /dev/nbd*
```

### Service Not Starting

Check logs:

```bash
sudo journalctl -u distfs-metadata -n 50
sudo journalctl -u distfs-storage -n 50
```

### Connection Refused

Verify services are listening:

```bash
# Metadata service (port 7001)
sudo netstat -tlnp | grep 7001

# Storage service (port 7002)
sudo netstat -tlnp | grep 7002
```

### Cannot Connect to Metadata Server

Check firewall rules:

```bash
# Allow metadata service
sudo ufw allow 7001/tcp

# Allow storage service
sudo ufw allow 7002/tcp
```

## Next Steps

- [KVM Integration Guide](KVM_INTEGRATION.md) - Deep dive into KVM/QEMU integration
- [API Reference](API.md) - Complete API documentation
- [Performance Guide](PERFORMANCE.md) - Optimization and tuning
- [Architecture](ARCHITECTURE.md) - System design and internals

## Getting Help

- Check logs: `sudo journalctl -u distfs-*`
- Verify cluster health: `distfs --metadata-server <server> health`
- Review documentation in the `docs/` directory

## Examples

See the `examples/` directory for:
- Sample VM configurations
- Cluster setup scripts
- Performance testing tools
- Integration examples
