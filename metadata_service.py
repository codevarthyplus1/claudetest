#!/usr/bin/env python3
"""
DistFS Metadata Service

Manages distributed filesystem metadata including:
- Volume definitions and mappings
- Storage node registry and health
- Block allocation and replication
- Cluster coordination
"""

import argparse
import json
import logging
import os
import socket
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse
import hashlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('metadata-service')


class Volume:
    """Represents a distributed volume"""

    def __init__(self, name: str, size_bytes: int, replicas: int = 2, chunk_size: int = 4 * 1024 * 1024):
        self.name = name
        self.size_bytes = size_bytes
        self.replicas = replicas
        self.chunk_size = chunk_size
        self.num_chunks = (size_bytes + chunk_size - 1) // chunk_size
        self.created_at = datetime.utcnow().isoformat()
        self.chunk_map: Dict[int, List[str]] = {}  # chunk_id -> [node_ids]

    def to_dict(self):
        return {
            'name': self.name,
            'size_bytes': self.size_bytes,
            'replicas': self.replicas,
            'chunk_size': self.chunk_size,
            'num_chunks': self.num_chunks,
            'created_at': self.created_at,
            'chunk_map': self.chunk_map
        }

    @classmethod
    def from_dict(cls, data: dict):
        vol = cls(data['name'], data['size_bytes'], data['replicas'], data['chunk_size'])
        vol.num_chunks = data['num_chunks']
        vol.created_at = data['created_at']
        vol.chunk_map = data['chunk_map']
        return vol


class StorageNode:
    """Represents a storage node in the cluster"""

    def __init__(self, node_id: str, host: str, port: int):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.last_heartbeat = time.time()
        self.status = 'online'
        self.capacity_bytes = 0
        self.used_bytes = 0

    def update_heartbeat(self, capacity: int = 0, used: int = 0):
        self.last_heartbeat = time.time()
        self.status = 'online'
        if capacity > 0:
            self.capacity_bytes = capacity
            self.used_bytes = used

    def is_alive(self, timeout: int = 30) -> bool:
        return (time.time() - self.last_heartbeat) < timeout

    def to_dict(self):
        return {
            'node_id': self.node_id,
            'host': self.host,
            'port': self.port,
            'last_heartbeat': self.last_heartbeat,
            'status': self.status,
            'capacity_bytes': self.capacity_bytes,
            'used_bytes': self.used_bytes
        }

    @classmethod
    def from_dict(cls, data: dict):
        node = cls(data['node_id'], data['host'], data['port'])
        node.last_heartbeat = data['last_heartbeat']
        node.status = data['status']
        node.capacity_bytes = data.get('capacity_bytes', 0)
        node.used_bytes = data.get('used_bytes', 0)
        return node


class MetadataService:
    """Central metadata service for DistFS"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self.volumes: Dict[str, Volume] = {}
        self.nodes: Dict[str, StorageNode] = {}
        self.lock = threading.RLock()

        self.load_metadata()

        # Start background tasks
        self.running = True
        self.health_check_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        self.health_check_thread.start()

    def load_metadata(self):
        """Load metadata from disk"""
        volumes_file = os.path.join(self.data_dir, 'volumes.json')
        nodes_file = os.path.join(self.data_dir, 'nodes.json')

        if os.path.exists(volumes_file):
            with open(volumes_file, 'r') as f:
                data = json.load(f)
                self.volumes = {name: Volume.from_dict(vol) for name, vol in data.items()}
            logger.info(f"Loaded {len(self.volumes)} volumes from disk")

        if os.path.exists(nodes_file):
            with open(nodes_file, 'r') as f:
                data = json.load(f)
                self.nodes = {nid: StorageNode.from_dict(node) for nid, node in data.items()}
            logger.info(f"Loaded {len(self.nodes)} nodes from disk")

    def save_metadata(self):
        """Persist metadata to disk"""
        with self.lock:
            volumes_file = os.path.join(self.data_dir, 'volumes.json')
            nodes_file = os.path.join(self.data_dir, 'nodes.json')

            # Save volumes
            with open(volumes_file, 'w') as f:
                data = {name: vol.to_dict() for name, vol in self.volumes.items()}
                json.dump(data, f, indent=2)

            # Save nodes
            with open(nodes_file, 'w') as f:
                data = {nid: node.to_dict() for nid, node in self.nodes.items()}
                json.dump(data, f, indent=2)

    def create_volume(self, name: str, size_bytes: int, replicas: int = 2) -> Volume:
        """Create a new volume"""
        with self.lock:
            if name in self.volumes:
                raise ValueError(f"Volume {name} already exists")

            volume = Volume(name, size_bytes, replicas)

            # Allocate chunks to storage nodes
            available_nodes = [n for n in self.nodes.values() if n.is_alive()]
            if len(available_nodes) < replicas:
                raise ValueError(f"Not enough storage nodes (need {replicas}, have {len(available_nodes)})")

            # Use consistent hashing to distribute chunks
            for chunk_id in range(volume.num_chunks):
                selected_nodes = self._select_nodes_for_chunk(chunk_id, volume.name, replicas, available_nodes)
                volume.chunk_map[chunk_id] = [n.node_id for n in selected_nodes]

            self.volumes[name] = volume
            self.save_metadata()

            logger.info(f"Created volume {name}: {size_bytes} bytes, {volume.num_chunks} chunks, {replicas} replicas")
            return volume

    def _select_nodes_for_chunk(self, chunk_id: int, volume_name: str, replicas: int,
                                 available_nodes: List[StorageNode]) -> List[StorageNode]:
        """Select storage nodes for a chunk using consistent hashing"""
        # Hash the volume name and chunk ID
        hash_input = f"{volume_name}:{chunk_id}".encode()
        chunk_hash = int(hashlib.sha256(hash_input).hexdigest(), 16)

        # Sort nodes by hash distance
        node_distances = []
        for node in available_nodes:
            node_hash = int(hashlib.sha256(node.node_id.encode()).hexdigest(), 16)
            distance = abs(chunk_hash - node_hash)
            node_distances.append((distance, node))

        node_distances.sort(key=lambda x: x[0])

        # Select top N nodes
        return [node for _, node in node_distances[:replicas]]

    def get_volume(self, name: str) -> Optional[Volume]:
        """Get volume by name"""
        with self.lock:
            return self.volumes.get(name)

    def delete_volume(self, name: str) -> bool:
        """Delete a volume"""
        with self.lock:
            if name in self.volumes:
                del self.volumes[name]
                self.save_metadata()
                logger.info(f"Deleted volume {name}")
                return True
            return False

    def list_volumes(self) -> List[Volume]:
        """List all volumes"""
        with self.lock:
            return list(self.volumes.values())

    def register_node(self, node_id: str, host: str, port: int) -> StorageNode:
        """Register a storage node"""
        with self.lock:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                node.update_heartbeat()
            else:
                node = StorageNode(node_id, host, port)
                self.nodes[node_id] = node
                self.save_metadata()
                logger.info(f"Registered new storage node {node_id} at {host}:{port}")
            return node

    def heartbeat(self, node_id: str, capacity: int = 0, used: int = 0) -> bool:
        """Update node heartbeat"""
        with self.lock:
            if node_id in self.nodes:
                self.nodes[node_id].update_heartbeat(capacity, used)
                return True
            return False

    def get_chunk_locations(self, volume_name: str, chunk_id: int) -> List[StorageNode]:
        """Get storage nodes for a specific chunk"""
        with self.lock:
            volume = self.volumes.get(volume_name)
            if not volume:
                return []

            node_ids = volume.chunk_map.get(chunk_id, [])
            return [self.nodes[nid] for nid in node_ids if nid in self.nodes and self.nodes[nid].is_alive()]

    def list_nodes(self) -> List[StorageNode]:
        """List all storage nodes"""
        with self.lock:
            return list(self.nodes.values())

    def _health_check_loop(self):
        """Background task to check node health"""
        while self.running:
            time.sleep(10)

            with self.lock:
                for node in self.nodes.values():
                    if not node.is_alive():
                        if node.status == 'online':
                            node.status = 'offline'
                            logger.warning(f"Node {node.node_id} marked as offline")

    def shutdown(self):
        """Shutdown the metadata service"""
        self.running = False
        self.save_metadata()


class MetadataHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for metadata service API"""

    metadata_service: MetadataService = None

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _parse_size(self, size_str: str) -> int:
        """Parse size string (e.g., 10G, 500M) to bytes"""
        units = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        size_str = size_str.strip().upper()

        if size_str[-1] in units:
            return int(float(size_str[:-1]) * units[size_str[-1]])
        return int(size_str)

    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/health':
            self._send_json({'status': 'healthy'})

        elif path == '/volumes':
            volumes = self.metadata_service.list_volumes()
            self._send_json({
                'volumes': [vol.to_dict() for vol in volumes]
            })

        elif path.startswith('/volumes/'):
            vol_name = path.split('/')[-1]
            volume = self.metadata_service.get_volume(vol_name)
            if volume:
                self._send_json(volume.to_dict())
            else:
                self._send_json({'error': 'Volume not found'}, 404)

        elif path == '/nodes':
            nodes = self.metadata_service.list_nodes()
            self._send_json({
                'nodes': [node.to_dict() for node in nodes]
            })

        elif path.startswith('/chunks/'):
            # /chunks/{volume_name}/{chunk_id}
            parts = path.split('/')
            if len(parts) >= 4:
                vol_name = parts[2]
                chunk_id = int(parts[3])
                locations = self.metadata_service.get_chunk_locations(vol_name, chunk_id)
                self._send_json({
                    'chunk_id': chunk_id,
                    'locations': [node.to_dict() for node in locations]
                })
            else:
                self._send_json({'error': 'Invalid path'}, 400)

        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({'error': 'Invalid JSON'}, 400)
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/volumes':
            try:
                name = data.get('name')
                size_str = data.get('size', '1G')
                replicas = int(data.get('replicas', 2))

                if not name:
                    self._send_json({'error': 'Volume name required'}, 400)
                    return

                size_bytes = self._parse_size(size_str)
                volume = self.metadata_service.create_volume(name, size_bytes, replicas)
                self._send_json(volume.to_dict(), 201)
            except Exception as e:
                self._send_json({'error': str(e)}, 400)

        elif path == '/nodes/register':
            try:
                node_id = data.get('node_id')
                host = data.get('host')
                port = int(data.get('port', 7002))

                if not node_id or not host:
                    self._send_json({'error': 'node_id and host required'}, 400)
                    return

                node = self.metadata_service.register_node(node_id, host, port)
                self._send_json(node.to_dict(), 201)
            except Exception as e:
                self._send_json({'error': str(e)}, 400)

        elif path == '/nodes/heartbeat':
            try:
                node_id = data.get('node_id')
                capacity = int(data.get('capacity', 0))
                used = int(data.get('used', 0))

                if not node_id:
                    self._send_json({'error': 'node_id required'}, 400)
                    return

                success = self.metadata_service.heartbeat(node_id, capacity, used)
                if success:
                    self._send_json({'status': 'ok'})
                else:
                    self._send_json({'error': 'Node not found'}, 404)
            except Exception as e:
                self._send_json({'error': str(e)}, 400)

        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_DELETE(self):
        """Handle DELETE requests"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/volumes/'):
            vol_name = path.split('/')[-1]
            success = self.metadata_service.delete_volume(vol_name)
            if success:
                self._send_json({'status': 'deleted'})
            else:
                self._send_json({'error': 'Volume not found'}, 404)
        else:
            self._send_json({'error': 'Not found'}, 404)


def main():
    parser = argparse.ArgumentParser(description='DistFS Metadata Service')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=7001, help='Port to bind to')
    parser.add_argument('--data-dir', default='/var/distfs/metadata', help='Data directory for metadata storage')

    args = parser.parse_args()

    # Initialize metadata service
    metadata_service = MetadataService(args.data_dir)
    MetadataHTTPHandler.metadata_service = metadata_service

    # Start HTTP server
    server = HTTPServer((args.host, args.port), MetadataHTTPHandler)
    logger.info(f"Metadata service started on {args.host}:{args.port}")
    logger.info(f"Data directory: {args.data_dir}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down metadata service")
        metadata_service.shutdown()
        server.shutdown()


if __name__ == '__main__':
    main()
