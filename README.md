# DistFS - Distributed File System with KVM Integration

A high-performance distributed file system that provides virtual block devices to KVM-based virtual machines.

## Architecture

DistFS consists of several key components:

### Core Components

1. **Storage Server** (`storage_server.py`)
   - Manages data storage across distributed nodes
   - Implements data replication (configurable replication factor)
   - Handles chunk-based storage with configurable chunk size
   - Provides network API for data operations

2. **Metadata Service** (`metadata_service.py`)
   - Manages filesystem metadata (files, blocks, locations)
   - Tracks node health and availability
   - Implements distributed consensus for metadata consistency
   - Handles volume management

3. **NBD Server** (`nbd_server.py`)
   - Exposes distributed storage as network block devices
   - Implements Linux NBD (Network Block Device) protocol
   - Provides block-level access to distributed volumes
   - Optimized for KVM/QEMU integration

4. **Client Library** (`distfs_client.py`)
   - High-level API for filesystem operations
   - Handles communication with storage and metadata services
   - Implements caching and prefetching
   - Provides volume management interface

5. **KVM Integration** (`kvm_integration/`)
   - Scripts for creating and managing VM disk images
   - QEMU configuration helpers
   - Performance tuning utilities

## Features

- **Distributed Storage**: Data distributed across multiple nodes with configurable replication
- **High Availability**: Automatic failover and data redundancy
- **Block Device Interface**: Native block device support via NBD
- **KVM/QEMU Integration**: Seamless VM disk image support
- **Scalability**: Add nodes dynamically without downtime
- **Performance**: Chunk-based storage with caching and parallel I/O

## Architecture Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   KVM VM    │     │   KVM VM    │     │   KVM VM    │
│             │     │             │     │             │
│  /dev/nbd0  │     │  /dev/nbd1  │     │  /dev/nbd2  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                    ┌──────▼──────┐
                    │  NBD Server  │
                    │ (Block I/O)  │
                    └──────┬──────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐
│  Metadata   │    │   Storage   │    │   Storage   │
│   Service   │    │   Server 1  │    │   Server 2  │
│             │    │             │    │             │
└─────────────┘    └─────────────┘    └─────────────┘
```

## System Requirements

- Linux kernel 3.10+ (for NBD support)
- Python 3.8+
- KVM/QEMU installed
- Network connectivity between nodes
- Root/sudo access for NBD operations

## Quick Start

### 1. Setup Storage Cluster

Start metadata service:
```bash
sudo python3 metadata_service.py --host 0.0.0.0 --port 7001 --data-dir /var/distfs/metadata
```

Start storage servers (on multiple nodes):
```bash
# Node 1
sudo python3 storage_server.py --host 0.0.0.0 --port 7002 --data-dir /var/distfs/storage1 --metadata-server 192.168.1.10:7001

# Node 2
sudo python3 storage_server.py --host 0.0.0.0 --port 7002 --data-dir /var/distfs/storage2 --metadata-server 192.168.1.10:7001
```

### 2. Create Virtual Block Device

Create a volume:
```bash
python3 distfs_client.py create-volume --name vm-disk-1 --size 10G --metadata-server 192.168.1.10:7001
```

Start NBD server:
```bash
sudo python3 nbd_server.py --volume vm-disk-1 --nbd-device /dev/nbd0 --metadata-server 192.168.1.10:7001
```

### 3. Use with KVM

Format the block device:
```bash
sudo mkfs.ext4 /dev/nbd0
```

Create KVM VM with the block device:
```bash
python3 kvm_integration/create_vm.py --name myvm --disk /dev/nbd0 --memory 2048 --cpus 2
```

Or use directly with QEMU:
```bash
qemu-system-x86_64 \
  -drive file=/dev/nbd0,format=raw,if=virtio \
  -m 2048 \
  -smp 2
```

## Configuration

### Replication Factor

Set replication factor when creating volumes:
```bash
python3 distfs_client.py create-volume --name myvolume --size 20G --replicas 3
```

### Chunk Size

Configure chunk size in storage servers:
```bash
python3 storage_server.py --chunk-size 4M --data-dir /var/distfs/storage
```

### Performance Tuning

See `docs/PERFORMANCE.md` for tuning guidelines.

## API Reference

See `docs/API.md` for complete API documentation.

## Security

- All network communication can be secured with TLS
- Access control via volume permissions
- Encryption at rest support

## License

MIT License
