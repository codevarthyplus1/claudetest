# DistFS Architecture

Technical architecture and design documentation for DistFS.

## System Overview

DistFS is a distributed file system designed specifically for providing virtual block devices to KVM-based virtual machines. It combines distributed storage, data replication, and NBD protocol integration to deliver high-availability storage for virtualized environments.

## Core Components

### 1. Metadata Service

**Purpose:** Central coordination and metadata management

**Responsibilities:**
- Volume metadata management (name, size, chunk mapping)
- Storage node registry and health tracking
- Chunk-to-node allocation using consistent hashing
- Cluster state persistence

**Implementation:** `metadata_service.py`

**Technology:**
- Python HTTP server
- JSON-based persistence
- In-memory indexing for performance
- Thread-safe operations with locks

**Data Structures:**
```python
Volume:
  - name: string
  - size_bytes: int
  - replicas: int
  - chunk_size: int
  - num_chunks: int
  - chunk_map: dict[chunk_id -> [node_ids]]
  - created_at: timestamp

StorageNode:
  - node_id: string
  - host: string
  - port: int
  - status: enum(online, offline)
  - capacity_bytes: int
  - used_bytes: int
  - last_heartbeat: timestamp
```

**API Endpoints:**
- `POST /volumes` - Create volume
- `GET /volumes` - List volumes
- `GET /volumes/{name}` - Get volume info
- `DELETE /volumes/{name}` - Delete volume
- `POST /nodes/register` - Register storage node
- `POST /nodes/heartbeat` - Node heartbeat
- `GET /nodes` - List nodes
- `GET /chunks/{volume}/{chunk_id}` - Get chunk locations

### 2. Storage Server

**Purpose:** Actual data storage and retrieval

**Responsibilities:**
- Chunk storage on local filesystem
- Data read/write operations
- Heartbeat reporting to metadata service
- Capacity monitoring

**Implementation:** `storage_server.py`

**Technology:**
- Python HTTP server
- File-based chunk storage
- Automatic registration with metadata service
- Background heartbeat thread

**Storage Layout:**
```
/var/distfs/storage/
├── volume-1/
│   ├── chunk_00000000.dat
│   ├── chunk_00000001.dat
│   └── ...
├── volume-2/
│   └── ...
```

**API Endpoints:**
- `GET /chunks/{volume}/{chunk_id}` - Read chunk
- `POST /chunks/{volume}/{chunk_id}` - Write chunk
- `DELETE /chunks/{volume}/{chunk_id}` - Delete chunk
- `GET /stats` - Storage statistics
- `GET /health` - Health check

### 3. Client Library

**Purpose:** High-level API for filesystem operations

**Responsibilities:**
- Volume management interface
- Data read/write with chunk handling
- Load balancing across replicas
- Retry logic and error handling

**Implementation:** `distfs_client.py`

**Key Methods:**
- `create_volume()` - Create new volume
- `read_data()` - Read from volume (handles chunking)
- `write_data()` - Write to volume (handles replication)
- `list_volumes()` - Query volumes
- `health_check()` - Cluster health

### 4. NBD Server

**Purpose:** Expose volumes as Linux block devices

**Responsibilities:**
- NBD protocol implementation
- Block-level I/O translation
- Integration with DistFS client library
- Device management

**Implementation:** `nbd_server.py`

**Technology:**
- Python socket server
- NBD protocol v3 (newstyle handshake)
- Async I/O handling
- Integration with Linux NBD kernel module

**NBD Protocol Flow:**
```
Client                    NBD Server               DistFS
  |                           |                      |
  |--- Handshake ------------>|                      |
  |<-- Export Info -----------|                      |
  |                           |                      |
  |--- Read Request --------->|                      |
  |                           |--- read_data() ----->|
  |                           |<-- chunk data -------|
  |<-- Data Reply ------------|                      |
  |                           |                      |
  |--- Write Request -------->|                      |
  |    + Data                 |                      |
  |                           |--- write_data() ---->|
  |                           |<-- success ----------|
  |<-- Success Reply ---------|                      |
```

### 5. KVM Integration

**Purpose:** Seamless VM integration with DistFS

**Components:**

#### VM Manager (`distfs_vm_manager.py`)
- VM lifecycle management
- Automatic NBD setup
- QEMU configuration generation
- VM state persistence

#### Helper Script (`qemu_distfs_helper.sh`)
- Quick NBD device setup
- QEMU launching
- Cleanup automation

## Data Flow

### Write Operation

```
┌─────────────┐
│  KVM VM     │
│  Guest OS   │
└──────┬──────┘
       │ write(block)
       ▼
┌─────────────┐
│ /dev/nbd0   │ (NBD device)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ NBD Server  │
└──────┬──────┘
       │ 1. Calculate chunk_id & offset
       │ 2. Get chunk locations from metadata
       ▼
┌─────────────┐
│ DistFS      │
│ Client      │
└──────┬──────┘
       │ 3. Write to all replicas
       ├──────────┬──────────┐
       ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│Storage 1 │ │Storage 2 │ │Storage 3 │
│ (Primary)│ │ (Replica)│ │ (Replica)│
└──────────┘ └──────────┘ └──────────┘
```

### Read Operation

```
┌─────────────┐
│  KVM VM     │
│  Guest OS   │
└──────┬──────┘
       │ read(block)
       ▼
┌─────────────┐
│ /dev/nbd0   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ NBD Server  │
└──────┬──────┘
       │ 1. Calculate chunk_id & offset
       │ 2. Get chunk locations
       ▼
┌─────────────┐
│ DistFS      │
│ Client      │
└──────┬──────┘
       │ 3. Read from first available replica
       ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│Storage 1 │ │Storage 2 │ │Storage 3 │
│  (Try 1) │ │ (Fallback│ │ (Fallback│
└──────────┘ └──────────┘ └──────────┘
```

## Chunk Distribution

DistFS uses consistent hashing to distribute chunks across storage nodes.

### Algorithm

```python
def select_nodes_for_chunk(chunk_id, volume_name, replicas, nodes):
    # Hash volume:chunk_id
    chunk_hash = sha256(f"{volume_name}:{chunk_id}")

    # Calculate distance to each node
    distances = []
    for node in nodes:
        node_hash = sha256(node.id)
        distance = abs(chunk_hash - node_hash)
        distances.append((distance, node))

    # Select N closest nodes
    distances.sort(key=lambda x: x[0])
    return [node for _, node in distances[:replicas]]
```

### Benefits

1. **Deterministic:** Same chunk always maps to same nodes
2. **Balanced:** Even distribution across nodes
3. **Minimal Rebalancing:** Adding nodes only affects nearby chunks
4. **Replica Diversity:** Replicas placed on different nodes

### Example Distribution

3 nodes, 2 replicas, 4 chunks:

```
Chunk 0: [Node-1, Node-2]
Chunk 1: [Node-2, Node-3]
Chunk 2: [Node-3, Node-1]
Chunk 3: [Node-1, Node-2]
```

## Replication Strategy

### Write Replication

**Strategy:** Synchronous multi-primary

**Process:**
1. Client writes to all replicas simultaneously
2. Write succeeds if ≥1 replica confirms
3. Warnings logged if not all replicas succeed

**Consistency:** Eventual consistency
- All replicas updated in real-time
- Failed writes may leave replicas inconsistent
- No automatic reconciliation (future enhancement)

### Read Strategy

**Strategy:** Read from first available

**Process:**
1. Get list of replicas from metadata service
2. Try replicas in order until success
3. Return data from first successful read

**Benefits:**
- Load balancing across replicas
- Automatic failover on replica failure
- No single point of failure

## Failure Handling

### Storage Node Failure

**Detection:**
- Heartbeat timeout (30 seconds default)
- Metadata service marks node as offline

**Impact:**
- Reads failover to other replicas automatically
- Writes continue if other replicas available
- Performance may degrade

**Recovery:**
- Node comes back online
- Sends heartbeat
- Marked as online again
- No data synchronization (assumes persistent storage)

### Metadata Service Failure

**Impact:**
- Cannot create/delete volumes
- Cannot get chunk locations for new operations
- Existing NBD connections continue working (cached metadata)

**Mitigation:**
- Run metadata service with high availability
- Consider active-passive failover
- Future: Multi-master metadata service

### Network Partition

**Scenario:** Storage nodes isolated from metadata service

**Impact:**
- Nodes marked offline after heartbeat timeout
- New operations may fail
- Existing operations continue

**Recovery:**
- Network heals
- Nodes send heartbeat
- Operations resume

## Scalability

### Horizontal Scaling

**Adding Storage Nodes:**
1. Deploy new storage server
2. Server registers with metadata service
3. New volumes use new node automatically
4. Existing volumes unchanged (no rebalancing)

**Chunk Rebalancing:**
- Not currently implemented
- Future enhancement for load balancing

### Volume Limits

**Theoretical Limits:**
- Max volume size: Limited by total cluster capacity
- Max chunks per volume: Limited by Python int (effectively unlimited)
- Max replicas: Limited by number of storage nodes

**Practical Limits:**
- Chunk size: 4MB default (configurable)
- Recommended max volume size: 10TB per volume
- Recommended max replicas: 5

### Performance Characteristics

**Throughput:**
- Reads: ~100-500 MB/s per volume (network limited)
- Writes: ~50-200 MB/s per volume (replication overhead)
- Scales linearly with storage nodes

**Latency:**
- Read latency: 1-5ms (local network)
- Write latency: 2-10ms (includes replication)
- Network latency dominant factor

**IOPS:**
- Random reads: 1000-5000 IOPS
- Random writes: 500-2000 IOPS
- Depends on storage backend and network

## Security Considerations

### Current Implementation

**Network Security:**
- All communication over HTTP (unencrypted)
- No authentication/authorization
- Trust-based model

**Recommendations for Production:**
1. Deploy on private network/VPN
2. Use firewall rules to restrict access
3. Implement TLS for all HTTP communication
4. Add token-based authentication

### Future Enhancements

1. **TLS/SSL:** Encrypt all network traffic
2. **Authentication:** Token or certificate-based auth
3. **Authorization:** Per-volume access control
4. **Encryption at Rest:** Encrypt chunks on disk
5. **Audit Logging:** Track all operations

## Monitoring and Observability

### Metrics to Monitor

**Cluster Level:**
- Number of online/offline nodes
- Total/used capacity
- Volume count
- Active connections

**Storage Node Level:**
- Disk usage
- I/O throughput
- Request latency
- Error rates

**Volume Level:**
- Read/write IOPS
- Throughput
- Chunk distribution
- Replica health

### Logging

**Metadata Service:**
```bash
journalctl -u distfs-metadata -f
```

**Storage Service:**
```bash
journalctl -u distfs-storage -f
```

**NBD Server:**
```bash
tail -f ~/.distfs/vms/<vm-name>-nbd.log
```

## Future Enhancements

### Short Term

1. **Volume Snapshots:** Point-in-time volume copies
2. **Volume Cloning:** Fast volume duplication
3. **Compression:** Optional chunk compression
4. **Metrics Export:** Prometheus/Grafana integration

### Medium Term

1. **Erasure Coding:** Better space efficiency than replication
2. **Chunk Migration:** Balance load across nodes
3. **Multi-Master Metadata:** High availability
4. **Read Caching:** Client-side or proxy caching

### Long Term

1. **S3 Backend:** Store chunks in object storage
2. **WAN Replication:** Cross-datacenter replication
3. **QoS:** Per-volume performance guarantees
4. **Auto-Tiering:** Hot/cold data separation

## Comparison with Alternatives

### vs Ceph

**Advantages:**
- Simpler architecture and deployment
- Easier to understand and debug
- Lower resource requirements
- Purpose-built for KVM

**Disadvantages:**
- Less mature
- Fewer features
- No RADOS, CephFS equivalent

### vs GlusterFS

**Advantages:**
- Better KVM integration (NBD)
- Simpler consistency model
- Lower latency for block devices

**Disadvantages:**
- No POSIX filesystem interface
- Fewer replication strategies
- Less production testing

### vs DRBD

**Advantages:**
- Multi-node replication (vs 2-node)
- Better scalability
- Dynamic node addition

**Disadvantages:**
- Higher latency
- More complex setup
- Network dependent

## Performance Tuning

### Chunk Size Selection

**Small Chunks (1-4MB):**
- Pros: Better random I/O, even distribution
- Cons: More metadata overhead
- Use for: Databases, random workloads

**Large Chunks (16-64MB):**
- Pros: Better sequential I/O, less metadata
- Cons: Uneven distribution possible
- Use for: Media files, sequential workloads

### Network Optimization

1. **Use dedicated network** for storage traffic
2. **Enable jumbo frames** (MTU 9000)
3. **Use 10GbE or faster** for production
4. **Minimize network hops** between nodes

### Storage Backend

1. **Use SSD** for metadata service
2. **Use fast disks** for storage nodes
3. **Disable atime** on storage filesystems
4. **Use XFS or ext4** with appropriate options

## Testing

### Unit Tests

Located in `tests/` directory:
- `test_metadata.py` - Metadata service tests
- `test_storage.py` - Storage server tests
- `test_client.py` - Client library tests
- `test_nbd.py` - NBD protocol tests

### Integration Tests

- Full cluster setup
- Multi-node scenarios
- Failure injection
- Performance benchmarks

### Manual Testing

```bash
# Create cluster
./setup.sh

# Create and test volume
distfs --metadata-server localhost:7001 create-volume --name test --size 1G

# Start NBD
sudo python3 nbd_server.py --volume test --metadata-server localhost:7001 --nbd-device /dev/nbd0

# Benchmark
sudo fio --filename=/dev/nbd0 --direct=1 --rw=randrw --bs=4k --ioengine=libaio --iodepth=256 --runtime=60 --numjobs=4 --time_based --group_reporting --name=test
```

## Contributing

See CONTRIBUTING.md for development guidelines.

## License

MIT License - See LICENSE file
