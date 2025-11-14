# Multi-Host Cluster Setup Guide

Complete guide for deploying DistFS-KVM across multiple KVM hosts for shared storage and live migration.

## Overview

DistFS-KVM enables multiple KVM hosts to share the same block devices, with data distributed across storage nodes. This provides:

- **Shared storage** - All hosts access the same devices
- **Live migration** - Move VMs between hosts without storage migration
- **High availability** - Survive host and storage node failures
- **Load balancing** - Distribute VMs across multiple hosts

## Architecture Models

### Model 1: Separate Storage Cluster

Best for: Large deployments, dedicated storage hardware

```
┌─────────────────────────────────────────────────────┐
│               KVM Compute Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ KVM Host 1   │  │ KVM Host 2   │  │ KVM Host N│ │
│  │ DistFS Module│  │ DistFS Module│  │ DistFS Mod│ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘ │
└─────────┼──────────────────┼────────────────┼───────┘
          │                  │                │
          └──────────────────┴────────────────┘
                             │
          ┌──────────────────┴────────────────┐
          │       Storage Network             │
          └──────────────────┬────────────────┘
                             │
┌────────────────────────────┴─────────────────────────┐
│             Storage Cluster                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │Metadata  │  │Storage 1 │  │Storage 2...N     │   │
│  │ Server   │  │          │  │                  │   │
│  └──────────┘  └──────────┘  └──────────────────┘   │
└──────────────────────────────────────────────────────┘
```

### Model 2: Hyper-Converged (Recommended for small-medium setups)

Best for: Small to medium deployments, efficient resource use

```
┌────────────────────────────────────────────────────┐
│           Hyper-Converged Node 1                   │
│  ┌─────────────┐  ┌─────────────┐                  │
│  │ KVM VMs     │  │ Storage     │                  │
│  │ DistFS Mod  │  │ Service     │                  │
│  └─────────────┘  └─────────────┘                  │
└────────────────────────┬───────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
┌────────▼─────────┐ ┌──▼──────────┐ ┌──▼──────────┐
│  Node 2          │ │  Node 3     │ │ Metadata    │
│  KVM + Storage   │ │ KVM+Storage │ │ Server      │
└──────────────────┘ └─────────────┘ └─────────────┘
```

## Deployment Steps

### Prerequisites

**Hardware Requirements (per host):**
- CPU: x86_64 with virtualization support (Intel VT-x / AMD-V)
- RAM: 4GB minimum (8GB+ recommended)
- Network: Dedicated 1GbE+ for storage traffic (10GbE recommended)
- Storage: SSD recommended for storage nodes

**Software Requirements (per host):**
- Linux kernel 4.14+ (5.4+ recommended)
- KVM/QEMU installed
- Kernel headers installed
- Network connectivity between all hosts

**Network Planning:**
- Dedicated storage network (separate VLAN recommended)
- Low latency network (<1ms between hosts)
- Sufficient bandwidth for VM workloads

### Step 1: Prepare All Hosts

**On each KVM host:**

```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install dependencies
sudo apt-get install -y build-essential linux-headers-$(uname -r) \
  qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils

# Enable and start libvirt
sudo systemctl enable libvirtd
sudo systemctl start libvirtd

# Verify KVM
lsmod | grep kvm
ls -l /dev/kvm

# Configure network (example for dedicated storage network)
# Assign static IP on storage network interface
# Example: eth1 for storage network

cat <<EOF | sudo tee /etc/netplan/60-storage.yaml
network:
  version: 2
  ethernets:
    eth1:
      addresses:
        - 10.0.1.20/24  # Adjust per host
      routes:
        - to: 10.0.1.0/24
          via: 10.0.1.1
EOF

sudo netplan apply
```

### Step 2: Build and Install DistFS-KVM

**On EACH host:**

```bash
# Clone or copy DistFS-KVM source
cd /usr/src
sudo git clone https://github.com/distfs/distfs-kvm.git
cd distfs-kvm

# Build
make

# Install
sudo make install
sudo make install-tools
sudo depmod -a

# Verify installation
ls -l /lib/modules/$(uname -r)/extra/distfs-kvm.ko
which distfs-kvm
```

### Step 3: Set Up Metadata Server

**Choose one host as metadata server** (e.g., 10.0.1.10)

```bash
# Create metadata directory
sudo mkdir -p /var/lib/distfs-kvm/metadata

# Create systemd service for metadata
cat <<EOF | sudo tee /etc/systemd/system/distfs-metadata.service
[Unit]
Description=DistFS-KVM Metadata Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/distfs-kvmd --role metadata --bind 0.0.0.0:7001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable distfs-metadata
sudo systemctl start distfs-metadata

# Verify
sudo systemctl status distfs-metadata
sudo journalctl -u distfs-metadata -f
```

### Step 4: Set Up Storage Nodes

**On each host that will provide storage** (can be all hosts in hyper-converged):

```bash
# Create storage directory
sudo mkdir -p /var/lib/distfs-kvm/storage

# Create systemd service for storage
cat <<EOF | sudo tee /etc/systemd/system/distfs-storage.service
[Unit]
Description=DistFS-KVM Storage Node
After=network.target distfs-metadata.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/distfs-kvmd \
  --role storage \
  --metadata 10.0.1.10:7001 \
  --storage-path /var/lib/distfs-kvm/storage
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable distfs-storage
sudo systemctl start distfs-storage

# Verify
sudo systemctl status distfs-storage
sudo journalctl -u distfs-storage -f
```

### Step 5: Load Kernel Module on All KVM Hosts

**On EACH KVM host:**

```bash
# Load module with metadata server parameter
sudo modprobe distfs-kvm metadata_server=10.0.1.10:7001 debug=0

# Verify module loaded
lsmod | grep distfs_kvm
dmesg | grep distfs-kvm

# Make it auto-load on boot
echo "distfs-kvm" | sudo tee /etc/modules-load.d/distfs-kvm.conf

# Set module parameters
cat <<EOF | sudo tee /etc/modprobe.d/distfs-kvm.conf
options distfs-kvm metadata_server=10.0.1.10:7001 debug=0 max_devices=256
EOF
```

### Step 6: Verify Cluster Health

**From any host:**

```bash
# Check cluster health
sudo distfs-kvm health

# Expected output:
# Cluster Status: Healthy
# Metadata Server: 10.0.1.10:7001 (connected)
# Storage Nodes: 3 online, 0 offline
# Devices: 0

# List storage nodes
sudo distfs-kvm nodes

# Expected output:
# Node ID              Address           Status    Capacity    Used
# node-10.0.1.10      10.0.1.10:7002     online    100GB       0GB
# node-10.0.1.20      10.0.1.20:7002     online    100GB       0GB
# node-10.0.1.30      10.0.1.30:7002     online    100GB       0GB
```

### Step 7: Create First Shared Device

**From any host:**

```bash
# Create a 50GB device with 3 replicas
sudo distfs-kvm create --name test-vm-disk --size 50G --replicas 3

# Verify device appears
ls -l /dev/distfs-0

# Check from other hosts
# On host 2:
ssh 10.0.1.20 'ls -l /dev/distfs-0'  # Should exist!

# On host 3:
ssh 10.0.1.30 'ls -l /dev/distfs-0'  # Should exist!

# View device info
sudo distfs-kvm info --name test-vm-disk

# Expected output:
# Device: test-vm-disk
# Block Device: /dev/distfs-0
# Size: 50GB
# Chunks: 12800 (4MB each)
# Replicas: 3
# Status: Online
# Chunk Distribution:
#   Node 10.0.1.10: 4267 chunks
#   Node 10.0.1.20: 4267 chunks
#   Node 10.0.1.30: 4266 chunks
```

### Step 8: Test with a VM

**On KVM Host 1 (10.0.1.20):**

```bash
# Create a VM using the shared device
virt-install \
  --name test-vm \
  --ram 2048 \
  --vcpus 2 \
  --disk path=/dev/distfs-0,device=disk,bus=virtio \
  --network network=default \
  --graphics vnc \
  --os-variant ubuntu20.04 \
  --cdrom /path/to/ubuntu.iso

# Start VM
virsh start test-vm

# Verify VM is using the device
virsh domblklist test-vm
```

**Live migrate to Host 2:**

```bash
# Migrate VM from Host 1 to Host 2
virsh migrate --live test-vm qemu+ssh://10.0.1.30/system

# VM now running on Host 2, still using /dev/distfs-0!
# Check on Host 2:
ssh 10.0.1.30 'virsh list --all'
```

## Configuration Best Practices

### 1. Network Configuration

**Dedicated Storage Network:**
```bash
# Separate storage traffic to dedicated network
# Use 10GbE or faster
# Enable jumbo frames for better performance

# Set MTU to 9000 on storage interfaces
ip link set eth1 mtu 9000

# Verify
ip link show eth1
```

**Firewall Rules:**
```bash
# Allow storage traffic
sudo ufw allow from 10.0.1.0/24 to any port 7001 proto tcp  # Metadata
sudo ufw allow from 10.0.1.0/24 to any port 7002 proto tcp  # Storage
```

### 2. Storage Sizing

**Replication Factor:**
- 2 replicas: Minimum, can survive 1 node failure
- 3 replicas: Recommended, can survive 2 node failures
- 4-5 replicas: High availability, can survive multiple failures

**Example for 3-node cluster:**
```bash
# With 3 nodes, each with 1TB storage
# Using 3 replicas
# Usable capacity = (3 * 1TB) / 3 = 1TB

# Create devices with appropriate replication
sudo distfs-kvm create -n prod-db -s 500G -r 3      # Critical
sudo distfs-kvm create -n dev-vm -s 200G -r 2       # Development
sudo distfs-kvm create -n test-vm -s 100G -r 2      # Testing
```

### 3. Performance Tuning

**Module Parameters:**
```bash
# For high-performance workloads
options distfs-kvm chunk_size=8388608   # 8MB chunks
options distfs-kvm max_devices=512      # Support more devices

# For low-latency workloads
options distfs-kvm chunk_size=2097152   # 2MB chunks (smaller = lower latency)
```

**Device-Specific Tuning:**
```bash
# For sequential workloads (database, large files)
sudo distfs-kvm create -n seq-disk -s 100G --chunk-size 16M

# For random workloads (VM OS disk)
sudo distfs-kvm create -n random-disk -s 50G --chunk-size 2M
```

### 4. Monitoring

**Set up monitoring:**
```bash
# Create monitoring script
cat <<'EOF' | sudo tee /usr/local/bin/distfs-monitor.sh
#!/bin/bash
while true; do
  echo "=== DistFS-KVM Status ==="
  date
  sudo distfs-kvm health
  cat /proc/distfs-kvm/stats
  echo ""
  sleep 60
done
EOF

chmod +x /usr/local/bin/distfs-monitor.sh

# Run in background or as systemd service
nohup /usr/local/bin/distfs-monitor.sh > /var/log/distfs-monitor.log 2>&1 &
```

## Troubleshooting

### Device Not Appearing on All Hosts

```bash
# Check module is loaded on all hosts
ssh host1 'lsmod | grep distfs_kvm'
ssh host2 'lsmod | grep distfs_kvm'

# Check metadata server connectivity
ssh host1 'ping -c 3 10.0.1.10'

# Check kernel module logs
ssh host1 'dmesg | grep distfs-kvm'

# Reload module if needed
ssh host1 'sudo modprobe -r distfs-kvm && sudo modprobe distfs-kvm metadata_server=10.0.1.10:7001'
```

### Storage Node Not Registering

```bash
# Check storage service
sudo systemctl status distfs-storage

# Check connectivity to metadata server
telnet 10.0.1.10 7001

# Check logs
sudo journalctl -u distfs-storage -n 100
```

### Poor Performance

```bash
# Check network latency
ping -c 100 10.0.1.20 | tail -1

# Should be <1ms for good performance

# Check network bandwidth
iperf3 -s  # On one host
iperf3 -c 10.0.1.20  # On another

# Check I/O statistics
iostat -x 1

# Monitor chunk distribution
sudo distfs-kvm info --name mydevice
```

## Advanced Topics

### Adding Hosts to Existing Cluster

```bash
# On new host:
# 1. Build and install DistFS-KVM (same version!)
# 2. Load module pointing to metadata server
# 3. Start storage service
# 4. Devices automatically appear

# No restart of existing hosts required
```

### Removing a Host

```bash
# 1. Migrate all VMs off the host
# 2. Stop storage service
sudo systemctl stop distfs-storage

# 3. Unload module
sudo modprobe -r distfs-kvm

# 4. Metadata server will mark node as offline
# 5. Chunks will failover to other replicas
```

### Disaster Recovery

```bash
# If metadata server fails:
# 1. Promote another node to metadata server
# 2. Update metadata_server parameter on all hosts
# 3. Reload modules

# If storage node fails:
# - System continues with remaining replicas
# - Rebuild from remaining replicas when node returns
```

## Production Checklist

- [ ] All hosts have matching kernel versions
- [ ] Dedicated storage network configured
- [ ] Firewall rules configured
- [ ] Metadata server has redundancy/backup
- [ ] Storage nodes have sufficient capacity
- [ ] Replication factor ≥ 2 for all devices
- [ ] Monitoring and alerting configured
- [ ] Tested live migration between hosts
- [ ] Tested failure scenarios
- [ ] Documentation for operations team
- [ ] Backup/DR procedures documented

## Next Steps

- See `PERFORMANCE.md` for optimization guide
- See `MONITORING.md` for monitoring setup
- See `HA_SETUP.md` for high availability configuration
