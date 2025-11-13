# DistFS API Reference

Complete API reference for DistFS components.

## Metadata Service API

The metadata service runs on port 7001 (default) and provides a REST API.

Base URL: `http://<metadata-server>:7001`

### Health Check

Check service health.

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy"
}
```

### Volume Management

#### Create Volume

Create a new distributed volume.

**Endpoint:** `POST /volumes`

**Request Body:**
```json
{
  "name": "my-volume",
  "size": "10G",
  "replicas": 2
}
```

**Parameters:**
- `name` (string, required): Unique volume name
- `size` (string, required): Volume size (supports K/M/G/T units)
- `replicas` (integer, optional): Number of replicas (default: 2)

**Response:** (201 Created)
```json
{
  "name": "my-volume",
  "size_bytes": 10737418240,
  "replicas": 2,
  "chunk_size": 4194304,
  "num_chunks": 2560,
  "created_at": "2025-01-13T10:30:00.000000",
  "chunk_map": {
    "0": ["node-1", "node-2"],
    "1": ["node-2", "node-3"],
    ...
  }
}
```

#### List Volumes

Get all volumes in the cluster.

**Endpoint:** `GET /volumes`

**Response:**
```json
{
  "volumes": [
    {
      "name": "my-volume",
      "size_bytes": 10737418240,
      "replicas": 2,
      "chunk_size": 4194304,
      "num_chunks": 2560,
      "created_at": "2025-01-13T10:30:00.000000",
      "chunk_map": {...}
    }
  ]
}
```

#### Get Volume

Get details of a specific volume.

**Endpoint:** `GET /volumes/{volume_name}`

**Response:**
```json
{
  "name": "my-volume",
  "size_bytes": 10737418240,
  "replicas": 2,
  "chunk_size": 4194304,
  "num_chunks": 2560,
  "created_at": "2025-01-13T10:30:00.000000",
  "chunk_map": {...}
}
```

**Error Response:** (404 Not Found)
```json
{
  "error": "Volume not found"
}
```

#### Delete Volume

Delete a volume (metadata only, doesn't delete data on storage nodes).

**Endpoint:** `DELETE /volumes/{volume_name}`

**Response:**
```json
{
  "status": "deleted"
}
```

### Node Management

#### Register Node

Register a storage node with the cluster.

**Endpoint:** `POST /nodes/register`

**Request Body:**
```json
{
  "node_id": "storage-01",
  "host": "192.168.1.10",
  "port": 7002
}
```

**Response:** (201 Created)
```json
{
  "node_id": "storage-01",
  "host": "192.168.1.10",
  "port": 7002,
  "last_heartbeat": 1705142400.0,
  "status": "online",
  "capacity_bytes": 107374182400,
  "used_bytes": 5368709120
}
```

#### List Nodes

Get all storage nodes.

**Endpoint:** `GET /nodes`

**Response:**
```json
{
  "nodes": [
    {
      "node_id": "storage-01",
      "host": "192.168.1.10",
      "port": 7002,
      "last_heartbeat": 1705142400.0,
      "status": "online",
      "capacity_bytes": 107374182400,
      "used_bytes": 5368709120
    }
  ]
}
```

#### Node Heartbeat

Update node status and statistics.

**Endpoint:** `POST /nodes/heartbeat`

**Request Body:**
```json
{
  "node_id": "storage-01",
  "capacity": 107374182400,
  "used": 5368709120
}
```

**Response:**
```json
{
  "status": "ok"
}
```

### Chunk Location

#### Get Chunk Locations

Get storage node locations for a specific chunk.

**Endpoint:** `GET /chunks/{volume_name}/{chunk_id}`

**Response:**
```json
{
  "chunk_id": 0,
  "locations": [
    {
      "node_id": "storage-01",
      "host": "192.168.1.10",
      "port": 7002,
      "status": "online"
    },
    {
      "node_id": "storage-02",
      "host": "192.168.1.11",
      "port": 7002,
      "status": "online"
    }
  ]
}
```

## Storage Service API

Storage services run on port 7002 (default).

Base URL: `http://<storage-node>:7002`

### Health Check

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy"
}
```

### Storage Statistics

Get storage node statistics.

**Endpoint:** `GET /stats`

**Response:**
```json
{
  "node_id": "storage-01",
  "capacity_bytes": 107374182400,
  "used_bytes": 5368709120,
  "free_bytes": 102005473280
}
```

### Chunk Operations

#### Read Chunk

Read data from a chunk.

**Endpoint:** `GET /chunks/{volume_name}/{chunk_id}?offset={offset}&length={length}`

**Query Parameters:**
- `offset` (integer, optional): Byte offset within chunk (default: 0)
- `length` (integer, optional): Number of bytes to read (default: entire chunk)

**Response:** Binary data (application/octet-stream)

#### Write Chunk

Write data to a chunk.

**Endpoint:** `POST /chunks/{volume_name}/{chunk_id}?offset={offset}`

**Query Parameters:**
- `offset` (integer, optional): Byte offset within chunk (default: 0)

**Request Body:** Binary data

**Response:**
```json
{
  "status": "ok",
  "bytes_written": 4096
}
```

#### Delete Chunk

Delete a specific chunk.

**Endpoint:** `DELETE /chunks/{volume_name}/{chunk_id}`

**Response:**
```json
{
  "status": "deleted"
}
```

#### Delete Volume

Delete all chunks for a volume.

**Endpoint:** `DELETE /volumes/{volume_name}`

**Response:**
```json
{
  "status": "deleted"
}
```

## Python Client Library

### DistFSClient

High-level Python client for DistFS operations.

#### Constructor

```python
from distfs_client import DistFSClient

client = DistFSClient(metadata_server='localhost:7001')
```

#### Volume Operations

##### create_volume()

```python
volume = client.create_volume(
    name='my-volume',
    size='10G',
    replicas=2
)
```

**Returns:** Volume dictionary

##### delete_volume()

```python
success = client.delete_volume(name='my-volume')
```

**Returns:** Boolean

##### get_volume()

```python
volume = client.get_volume(name='my-volume')
```

**Returns:** Volume dictionary or None

##### list_volumes()

```python
volumes = client.list_volumes()
```

**Returns:** List of volume dictionaries

#### Data Operations

##### read_data()

```python
data = client.read_data(
    volume_name='my-volume',
    offset=0,
    length=4096
)
```

**Returns:** Bytes or None

##### write_data()

```python
success = client.write_data(
    volume_name='my-volume',
    offset=0,
    data=b'Hello, DistFS!'
)
```

**Returns:** Boolean

#### Node Operations

##### list_nodes()

```python
nodes = client.list_nodes()
```

**Returns:** List of node dictionaries

##### get_chunk_locations()

```python
locations = client.get_chunk_locations(
    volume_name='my-volume',
    chunk_id=0
)
```

**Returns:** List of node dictionaries

##### health_check()

```python
health = client.health_check()
```

**Returns:** Health status dictionary

### Usage Example

```python
from distfs_client import DistFSClient

# Initialize client
client = DistFSClient('localhost:7001')

# Create a volume
volume = client.create_volume('test-vol', '1G', replicas=2)
print(f"Created volume: {volume['name']}")

# Write data
data = b'Hello, DistFS!' * 1000
client.write_data('test-vol', offset=0, data=data)

# Read data back
read_data = client.read_data('test-vol', offset=0, length=len(data))
assert read_data == data

# List volumes
volumes = client.list_volumes()
for vol in volumes:
    print(f"{vol['name']}: {vol['size_bytes']} bytes")

# Check health
health = client.health_check()
print(f"Cluster status: {health['status']}")

# Cleanup
client.delete_volume('test-vol')
```

## NBD Protocol Integration

DistFS implements the NBD (Network Block Device) protocol for block device access.

### NBD Server

Start an NBD server for a volume:

```python
from nbd_server import NBDServer

server = NBDServer(
    volume_name='my-volume',
    metadata_server='localhost:7001',
    read_only=False
)
```

### NBD Client Connection

Connect using standard NBD client:

```bash
# Connect
nbd-client <host> <port> /dev/nbd0

# Disconnect
nbd-client -d /dev/nbd0
```

## Command Line Interface

### distfs_client.py

Main CLI for volume management.

```bash
# Create volume
python3 distfs_client.py --metadata-server localhost:7001 \
    create-volume --name test --size 10G --replicas 2

# List volumes
python3 distfs_client.py --metadata-server localhost:7001 \
    list-volumes

# Volume info
python3 distfs_client.py --metadata-server localhost:7001 \
    volume-info --name test

# List nodes
python3 distfs_client.py --metadata-server localhost:7001 \
    list-nodes

# Health check
python3 distfs_client.py --metadata-server localhost:7001 \
    health

# Delete volume
python3 distfs_client.py --metadata-server localhost:7001 \
    delete-volume --name test
```

### distfs_vm_manager.py

VM management CLI.

```bash
# Create VM
sudo python3 kvm_integration/distfs_vm_manager.py \
    --metadata-server localhost:7001 \
    create --name myvm --disk-size 20G --memory 2048 --cpus 2

# Start VM
sudo python3 kvm_integration/distfs_vm_manager.py \
    --metadata-server localhost:7001 \
    start --name myvm --vnc-port 5900

# List VMs
sudo python3 kvm_integration/distfs_vm_manager.py \
    --metadata-server localhost:7001 \
    list

# Stop VM
sudo python3 kvm_integration/distfs_vm_manager.py \
    --metadata-server localhost:7001 \
    stop --name myvm

# Delete VM
sudo python3 kvm_integration/distfs_vm_manager.py \
    --metadata-server localhost:7001 \
    delete --name myvm --delete-disk
```

### nbd_server.py

NBD server for exposing volumes.

```bash
# Start NBD server
sudo python3 nbd_server.py \
    --volume my-volume \
    --metadata-server localhost:7001 \
    --host 127.0.0.1 \
    --port 10809 \
    --nbd-device /dev/nbd0

# Read-only mode
sudo python3 nbd_server.py \
    --volume my-volume \
    --metadata-server localhost:7001 \
    --read-only
```

## Error Codes

### HTTP Status Codes

- `200 OK`: Request successful
- `201 Created`: Resource created successfully
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error

### NBD Error Codes

- `0`: Success
- `1`: EPERM (Permission denied)
- `5`: EIO (I/O error)
- `12`: ENOMEM (Out of memory)
- `22`: EINVAL (Invalid argument)
- `28`: ENOSPC (No space left)

## Rate Limiting

Currently, DistFS does not implement rate limiting. For production use, consider:

1. Using a reverse proxy (nginx, HAProxy) with rate limiting
2. Implementing client-side rate limiting
3. Monitoring and alerting on excessive requests

## Authentication & Authorization

Current version does not include authentication. For production:

1. Use network segmentation and firewalls
2. Implement TLS for all connections
3. Use VPN or private networks for cluster communication
4. Consider implementing token-based auth in future versions

## Versioning

API version is not currently included in URLs. Breaking changes will be documented in release notes.

## Support

For API issues and questions:
- Check logs: `journalctl -u distfs-*`
- Review documentation in `docs/`
- Open an issue on GitHub
