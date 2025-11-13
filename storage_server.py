#!/usr/bin/env python3
"""
DistFS Storage Server

Handles actual data storage including:
- Chunk storage and retrieval
- Data replication
- Health reporting to metadata service
- HTTP API for data operations
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import socket
import threading
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('storage-server')


class StorageServer:
    """Storage server for DistFS"""

    def __init__(self, node_id: str, data_dir: str, metadata_server: str, chunk_size: int = 4 * 1024 * 1024):
        self.node_id = node_id
        self.data_dir = data_dir
        self.metadata_server = metadata_server
        self.chunk_size = chunk_size

        os.makedirs(data_dir, exist_ok=True)

        self.running = True

        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

        logger.info(f"Storage server initialized: {node_id}")
        logger.info(f"Data directory: {data_dir}")
        logger.info(f"Metadata server: {metadata_server}")

    def _get_chunk_path(self, volume_name: str, chunk_id: int) -> str:
        """Get file path for a chunk"""
        volume_dir = os.path.join(self.data_dir, volume_name)
        os.makedirs(volume_dir, exist_ok=True)
        return os.path.join(volume_dir, f"chunk_{chunk_id:08d}.dat")

    def write_chunk(self, volume_name: str, chunk_id: int, data: bytes, offset: int = 0) -> bool:
        """Write data to a chunk"""
        try:
            chunk_path = self._get_chunk_path(volume_name, chunk_id)

            # Ensure chunk file exists and is the right size
            if not os.path.exists(chunk_path):
                with open(chunk_path, 'wb') as f:
                    f.write(b'\x00' * self.chunk_size)

            # Write data at offset
            with open(chunk_path, 'r+b') as f:
                f.seek(offset)
                f.write(data)

            logger.debug(f"Wrote {len(data)} bytes to {volume_name}/chunk_{chunk_id} at offset {offset}")
            return True
        except Exception as e:
            logger.error(f"Error writing chunk: {e}")
            return False

    def read_chunk(self, volume_name: str, chunk_id: int, offset: int = 0, length: int = None) -> Optional[bytes]:
        """Read data from a chunk"""
        try:
            chunk_path = self._get_chunk_path(volume_name, chunk_id)

            if not os.path.exists(chunk_path):
                # Return zeros for unallocated chunks
                read_length = length if length else self.chunk_size - offset
                return b'\x00' * read_length

            with open(chunk_path, 'rb') as f:
                f.seek(offset)
                if length:
                    data = f.read(length)
                else:
                    data = f.read()

            logger.debug(f"Read {len(data)} bytes from {volume_name}/chunk_{chunk_id} at offset {offset}")
            return data
        except Exception as e:
            logger.error(f"Error reading chunk: {e}")
            return None

    def delete_chunk(self, volume_name: str, chunk_id: int) -> bool:
        """Delete a chunk"""
        try:
            chunk_path = self._get_chunk_path(volume_name, chunk_id)
            if os.path.exists(chunk_path):
                os.remove(chunk_path)
                logger.info(f"Deleted chunk {volume_name}/chunk_{chunk_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting chunk: {e}")
            return False

    def delete_volume(self, volume_name: str) -> bool:
        """Delete all chunks for a volume"""
        try:
            volume_dir = os.path.join(self.data_dir, volume_name)
            if os.path.exists(volume_dir):
                shutil.rmtree(volume_dir)
                logger.info(f"Deleted volume {volume_name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting volume: {e}")
            return False

    def get_storage_stats(self) -> dict:
        """Get storage statistics"""
        try:
            stat = os.statvfs(self.data_dir)
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            used = total - free

            return {
                'capacity_bytes': total,
                'used_bytes': used,
                'free_bytes': free,
                'node_id': self.node_id
            }
        except Exception as e:
            logger.error(f"Error getting storage stats: {e}")
            return {
                'capacity_bytes': 0,
                'used_bytes': 0,
                'free_bytes': 0,
                'node_id': self.node_id
            }

    def _heartbeat_loop(self):
        """Send periodic heartbeats to metadata server"""
        # First, register with metadata server
        self._register()

        while self.running:
            time.sleep(10)
            self._send_heartbeat()

    def _register(self):
        """Register with metadata server"""
        try:
            # Get local IP
            host = socket.gethostbyname(socket.gethostname())

            url = f"http://{self.metadata_server}/nodes/register"
            data = {
                'node_id': self.node_id,
                'host': host,
                'port': 7002  # Default storage server port
            }

            response = requests.post(url, json=data, timeout=5)
            if response.status_code in [200, 201]:
                logger.info(f"Registered with metadata server: {self.metadata_server}")
            else:
                logger.error(f"Failed to register: {response.status_code}")
        except Exception as e:
            logger.error(f"Error registering with metadata server: {e}")

    def _send_heartbeat(self):
        """Send heartbeat to metadata server"""
        try:
            stats = self.get_storage_stats()

            url = f"http://{self.metadata_server}/nodes/heartbeat"
            data = {
                'node_id': self.node_id,
                'capacity': stats['capacity_bytes'],
                'used': stats['used_bytes']
            }

            response = requests.post(url, json=data, timeout=5)
            if response.status_code != 200:
                logger.warning(f"Heartbeat failed: {response.status_code}")
        except Exception as e:
            logger.debug(f"Error sending heartbeat: {e}")

    def shutdown(self):
        """Shutdown the storage server"""
        self.running = False


class StorageHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for storage server API"""

    storage_server: StorageServer = None

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def _send_response(self, data: bytes, status: int = 200, content_type: str = 'application/octet-stream'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, data: dict, status: int = 200):
        json_data = json.dumps(data).encode()
        self._send_response(json_data, status, 'application/json')

    def do_GET(self):
        """Handle GET requests (read operations)"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/health':
            self._send_json({'status': 'healthy'})

        elif path == '/stats':
            stats = self.storage_server.get_storage_stats()
            self._send_json(stats)

        elif path.startswith('/chunks/'):
            # /chunks/{volume_name}/{chunk_id}?offset=X&length=Y
            parts = path.split('/')
            if len(parts) >= 4:
                volume_name = parts[2]
                chunk_id = int(parts[3])

                # Parse query parameters
                from urllib.parse import parse_qs
                query = parse_qs(parsed.query)
                offset = int(query.get('offset', [0])[0])
                length = int(query.get('length', [0])[0]) if 'length' in query else None

                data = self.storage_server.read_chunk(volume_name, chunk_id, offset, length)
                if data is not None:
                    self._send_response(data)
                else:
                    self._send_json({'error': 'Failed to read chunk'}, 500)
            else:
                self._send_json({'error': 'Invalid path'}, 400)

        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        """Handle POST requests (write operations)"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/chunks/'):
            # /chunks/{volume_name}/{chunk_id}?offset=X
            parts = path.split('/')
            if len(parts) >= 4:
                volume_name = parts[2]
                chunk_id = int(parts[3])

                # Parse query parameters
                from urllib.parse import parse_qs
                query = parse_qs(parsed.query)
                offset = int(query.get('offset', [0])[0])

                # Read data from request body
                content_length = int(self.headers.get('Content-Length', 0))
                data = self.rfile.read(content_length) if content_length > 0 else b''

                success = self.storage_server.write_chunk(volume_name, chunk_id, data, offset)
                if success:
                    self._send_json({'status': 'ok', 'bytes_written': len(data)})
                else:
                    self._send_json({'error': 'Failed to write chunk'}, 500)
            else:
                self._send_json({'error': 'Invalid path'}, 400)

        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_DELETE(self):
        """Handle DELETE requests"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/chunks/'):
            parts = path.split('/')
            if len(parts) >= 4:
                volume_name = parts[2]
                chunk_id = int(parts[3])

                success = self.storage_server.delete_chunk(volume_name, chunk_id)
                if success:
                    self._send_json({'status': 'deleted'})
                else:
                    self._send_json({'error': 'Failed to delete chunk'}, 500)

        elif path.startswith('/volumes/'):
            volume_name = path.split('/')[-1]
            success = self.storage_server.delete_volume(volume_name)
            if success:
                self._send_json({'status': 'deleted'})
            else:
                self._send_json({'error': 'Failed to delete volume'}, 500)

        else:
            self._send_json({'error': 'Not found'}, 404)


def main():
    parser = argparse.ArgumentParser(description='DistFS Storage Server')
    parser.add_argument('--node-id', help='Unique node ID (default: hostname)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=7002, help='Port to bind to')
    parser.add_argument('--data-dir', default='/var/distfs/storage', help='Data directory for chunk storage')
    parser.add_argument('--metadata-server', required=True, help='Metadata server address (host:port)')
    parser.add_argument('--chunk-size', default='4M', help='Chunk size (e.g., 4M, 1G)')

    args = parser.parse_args()

    # Generate node ID if not provided
    if not args.node_id:
        args.node_id = f"{socket.gethostname()}-{args.port}"

    # Parse chunk size
    def parse_size(size_str):
        units = {'K': 1024, 'M': 1024**2, 'G': 1024**3}
        size_str = size_str.upper()
        if size_str[-1] in units:
            return int(float(size_str[:-1]) * units[size_str[-1]])
        return int(size_str)

    chunk_size = parse_size(args.chunk_size)

    # Initialize storage server
    storage_server = StorageServer(args.node_id, args.data_dir, args.metadata_server, chunk_size)
    StorageHTTPHandler.storage_server = storage_server

    # Start HTTP server
    server = HTTPServer((args.host, args.port), StorageHTTPHandler)
    logger.info(f"Storage server started on {args.host}:{args.port}")
    logger.info(f"Node ID: {args.node_id}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down storage server")
        storage_server.shutdown()
        server.shutdown()


if __name__ == '__main__':
    main()
