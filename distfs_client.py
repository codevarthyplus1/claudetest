#!/usr/bin/env python3
"""
DistFS Client Library

High-level API for interacting with DistFS including:
- Volume management
- Data read/write operations
- Metadata queries
- CLI interface
"""

import argparse
import json
import logging
import sys
from typing import List, Optional
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('distfs-client')


class DistFSClient:
    """Client for DistFS operations"""

    def __init__(self, metadata_server: str):
        self.metadata_server = metadata_server
        self.metadata_url = f"http://{metadata_server}"

    def _parse_size(self, size_str: str) -> int:
        """Parse size string (e.g., 10G, 500M) to bytes"""
        units = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        size_str = size_str.strip().upper()

        if size_str[-1] in units:
            return int(float(size_str[:-1]) * units[size_str[-1]])
        return int(size_str)

    def _format_size(self, bytes: int) -> str:
        """Format bytes to human-readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes < 1024.0:
                return f"{bytes:.2f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.2f} PB"

    def create_volume(self, name: str, size: str, replicas: int = 2) -> dict:
        """Create a new volume"""
        try:
            url = f"{self.metadata_url}/volumes"
            data = {
                'name': name,
                'size': size,
                'replicas': replicas
            }

            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            volume = response.json()
            logger.info(f"Created volume '{name}': {self._format_size(volume['size_bytes'])}, "
                       f"{volume['num_chunks']} chunks, {replicas} replicas")
            return volume
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create volume: {e}")
            raise

    def delete_volume(self, name: str) -> bool:
        """Delete a volume"""
        try:
            url = f"{self.metadata_url}/volumes/{name}"
            response = requests.delete(url, timeout=10)
            response.raise_for_status()

            logger.info(f"Deleted volume '{name}'")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to delete volume: {e}")
            return False

    def get_volume(self, name: str) -> Optional[dict]:
        """Get volume information"""
        try:
            url = f"{self.metadata_url}/volumes/{name}"
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get volume: {e}")
            return None

    def list_volumes(self) -> List[dict]:
        """List all volumes"""
        try:
            url = f"{self.metadata_url}/volumes"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data.get('volumes', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list volumes: {e}")
            return []

    def list_nodes(self) -> List[dict]:
        """List all storage nodes"""
        try:
            url = f"{self.metadata_url}/nodes"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data.get('nodes', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list nodes: {e}")
            return []

    def get_chunk_locations(self, volume_name: str, chunk_id: int) -> List[dict]:
        """Get storage locations for a chunk"""
        try:
            url = f"{self.metadata_url}/chunks/{volume_name}/{chunk_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data.get('locations', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get chunk locations: {e}")
            return []

    def read_data(self, volume_name: str, offset: int, length: int) -> Optional[bytes]:
        """Read data from a volume"""
        volume = self.get_volume(volume_name)
        if not volume:
            logger.error(f"Volume '{volume_name}' not found")
            return None

        chunk_size = volume['chunk_size']
        result = bytearray()

        while length > 0:
            chunk_id = offset // chunk_size
            chunk_offset = offset % chunk_size
            read_length = min(length, chunk_size - chunk_offset)

            # Get chunk data
            chunk_data = self._read_chunk(volume_name, chunk_id, chunk_offset, read_length)
            if chunk_data is None:
                return None

            result.extend(chunk_data)
            offset += read_length
            length -= read_length

        return bytes(result)

    def _read_chunk(self, volume_name: str, chunk_id: int, offset: int, length: int) -> Optional[bytes]:
        """Read data from a specific chunk"""
        locations = self.get_chunk_locations(volume_name, chunk_id)
        if not locations:
            logger.error(f"No locations found for chunk {chunk_id}")
            return None

        # Try each location until successful
        for location in locations:
            try:
                url = f"http://{location['host']}:{location['port']}/chunks/{volume_name}/{chunk_id}"
                params = {'offset': offset, 'length': length}

                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()

                return response.content
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to read from {location['node_id']}: {e}")
                continue

        logger.error(f"Failed to read chunk {chunk_id} from all locations")
        return None

    def write_data(self, volume_name: str, offset: int, data: bytes) -> bool:
        """Write data to a volume"""
        volume = self.get_volume(volume_name)
        if not volume:
            logger.error(f"Volume '{volume_name}' not found")
            return False

        chunk_size = volume['chunk_size']
        data_offset = 0
        data_length = len(data)

        while data_length > 0:
            chunk_id = offset // chunk_size
            chunk_offset = offset % chunk_size
            write_length = min(data_length, chunk_size - chunk_offset)

            chunk_data = data[data_offset:data_offset + write_length]

            # Write to chunk
            if not self._write_chunk(volume_name, chunk_id, chunk_offset, chunk_data):
                return False

            offset += write_length
            data_offset += write_length
            data_length -= write_length

        return True

    def _write_chunk(self, volume_name: str, chunk_id: int, offset: int, data: bytes) -> bool:
        """Write data to a specific chunk (all replicas)"""
        locations = self.get_chunk_locations(volume_name, chunk_id)
        if not locations:
            logger.error(f"No locations found for chunk {chunk_id}")
            return False

        success_count = 0

        # Write to all replicas
        for location in locations:
            try:
                url = f"http://{location['host']}:{location['port']}/chunks/{volume_name}/{chunk_id}"
                params = {'offset': offset}

                response = requests.post(url, params=params, data=data, timeout=10)
                response.raise_for_status()

                success_count += 1
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to write to {location['node_id']}: {e}")
                continue

        # Require at least one successful write
        if success_count == 0:
            logger.error(f"Failed to write chunk {chunk_id} to any location")
            return False

        if success_count < len(locations):
            logger.warning(f"Wrote chunk {chunk_id} to {success_count}/{len(locations)} replicas")

        return True

    def health_check(self) -> dict:
        """Check cluster health"""
        try:
            url = f"{self.metadata_url}/health"
            response = requests.get(url, timeout=5)
            response.raise_for_status()

            nodes = self.list_nodes()
            volumes = self.list_volumes()

            online_nodes = [n for n in nodes if n['status'] == 'online']

            return {
                'metadata_service': 'healthy',
                'total_nodes': len(nodes),
                'online_nodes': len(online_nodes),
                'total_volumes': len(volumes),
                'status': 'healthy' if len(online_nodes) > 0 else 'degraded'
            }
        except Exception as e:
            return {
                'metadata_service': 'unreachable',
                'error': str(e),
                'status': 'unhealthy'
            }


def main():
    parser = argparse.ArgumentParser(description='DistFS Client')
    parser.add_argument('--metadata-server', required=True, help='Metadata server address (host:port)')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Create volume
    create_parser = subparsers.add_parser('create-volume', help='Create a new volume')
    create_parser.add_argument('--name', required=True, help='Volume name')
    create_parser.add_argument('--size', required=True, help='Volume size (e.g., 10G, 500M)')
    create_parser.add_argument('--replicas', type=int, default=2, help='Number of replicas (default: 2)')

    # Delete volume
    delete_parser = subparsers.add_parser('delete-volume', help='Delete a volume')
    delete_parser.add_argument('--name', required=True, help='Volume name')

    # List volumes
    list_vol_parser = subparsers.add_parser('list-volumes', help='List all volumes')

    # Get volume info
    info_parser = subparsers.add_parser('volume-info', help='Get volume information')
    info_parser.add_argument('--name', required=True, help='Volume name')

    # List nodes
    list_nodes_parser = subparsers.add_parser('list-nodes', help='List storage nodes')

    # Health check
    health_parser = subparsers.add_parser('health', help='Check cluster health')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    client = DistFSClient(args.metadata_server)

    try:
        if args.command == 'create-volume':
            volume = client.create_volume(args.name, args.size, args.replicas)
            print(json.dumps(volume, indent=2))

        elif args.command == 'delete-volume':
            success = client.delete_volume(args.name)
            sys.exit(0 if success else 1)

        elif args.command == 'list-volumes':
            volumes = client.list_volumes()
            if volumes:
                print(f"\n{'Name':<20} {'Size':<12} {'Chunks':<8} {'Replicas':<10} {'Created':<20}")
                print("-" * 80)
                for vol in volumes:
                    size = client._format_size(vol['size_bytes'])
                    print(f"{vol['name']:<20} {size:<12} {vol['num_chunks']:<8} "
                          f"{vol['replicas']:<10} {vol['created_at']:<20}")
            else:
                print("No volumes found")

        elif args.command == 'volume-info':
            volume = client.get_volume(args.name)
            if volume:
                print(json.dumps(volume, indent=2))
            else:
                print(f"Volume '{args.name}' not found")
                sys.exit(1)

        elif args.command == 'list-nodes':
            nodes = client.list_nodes()
            if nodes:
                print(f"\n{'Node ID':<30} {'Address':<25} {'Status':<10} {'Capacity':<12} {'Used':<12}")
                print("-" * 95)
                for node in nodes:
                    address = f"{node['host']}:{node['port']}"
                    capacity = client._format_size(node.get('capacity_bytes', 0))
                    used = client._format_size(node.get('used_bytes', 0))
                    print(f"{node['node_id']:<30} {address:<25} {node['status']:<10} "
                          f"{capacity:<12} {used:<12}")
            else:
                print("No nodes found")

        elif args.command == 'health':
            health = client.health_check()
            print(json.dumps(health, indent=2))
            sys.exit(0 if health['status'] == 'healthy' else 1)

    except Exception as e:
        logger.error(f"Command failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
