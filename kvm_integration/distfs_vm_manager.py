#!/usr/bin/env python3
"""
DistFS VM Manager

Manages KVM virtual machines with DistFS storage backend.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from distfs_client import DistFSClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('vm-manager')


class VMManager:
    """Manages VMs with DistFS storage"""

    def __init__(self, metadata_server: str):
        self.client = DistFSClient(metadata_server)
        self.metadata_server = metadata_server
        self.config_dir = os.path.expanduser('~/.distfs/vms')
        os.makedirs(self.config_dir, exist_ok=True)

    def create_vm(self, name: str, disk_size: str, memory: int = 2048, cpus: int = 2,
                  iso: str = None, replicas: int = 2) -> dict:
        """Create a new VM with DistFS storage"""

        logger.info(f"Creating VM '{name}'...")

        # Create volume for VM disk
        volume_name = f"vm-{name}-disk"

        try:
            volume = self.client.create_volume(volume_name, disk_size, replicas)
            logger.info(f"Created disk volume: {volume_name}")
        except Exception as e:
            logger.error(f"Failed to create volume: {e}")
            return None

        # Create VM configuration
        vm_config = {
            'name': name,
            'volume': volume_name,
            'memory': memory,
            'cpus': cpus,
            'iso': iso,
            'nbd_device': f'/dev/nbd{self._get_next_nbd_device()}',
            'nbd_port': self._get_next_nbd_port(),
            'created': volume['created_at']
        }

        # Save configuration
        config_file = os.path.join(self.config_dir, f'{name}.json')
        with open(config_file, 'w') as f:
            json.dump(vm_config, f, indent=2)

        logger.info(f"VM '{name}' created successfully")
        return vm_config

    def start_vm(self, name: str, vnc_port: int = None, daemonize: bool = True) -> bool:
        """Start a VM"""

        vm_config = self._load_vm_config(name)
        if not vm_config:
            logger.error(f"VM '{name}' not found")
            return False

        logger.info(f"Starting VM '{name}'...")

        # Start NBD server for the volume
        logger.info("Starting NBD server...")
        nbd_port = vm_config['nbd_port']

        nbd_cmd = [
            sys.executable,
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'nbd_server.py'),
            '--volume', vm_config['volume'],
            '--metadata-server', self.metadata_server,
            '--host', '127.0.0.1',
            '--port', str(nbd_port)
        ]

        # Start NBD server in background
        nbd_log = os.path.join(self.config_dir, f'{name}-nbd.log')
        with open(nbd_log, 'w') as log_file:
            nbd_process = subprocess.Popen(
                nbd_cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT
            )

        # Save NBD process PID
        vm_config['nbd_pid'] = nbd_process.pid
        self._save_vm_config(name, vm_config)

        # Wait for NBD server to start
        import time
        time.sleep(2)

        # Connect NBD client
        nbd_device = vm_config['nbd_device']
        logger.info(f"Connecting NBD device {nbd_device}...")

        try:
            subprocess.run([
                'nbd-client',
                '127.0.0.1',
                str(nbd_port),
                nbd_device
            ], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to connect NBD device: {e}")
            # Kill NBD server
            subprocess.run(['kill', str(nbd_process.pid)])
            return False

        # Build QEMU command
        qemu_cmd = self._build_qemu_command(vm_config, vnc_port)

        # Start QEMU
        logger.info("Starting QEMU...")

        qemu_log = os.path.join(self.config_dir, f'{name}-qemu.log')

        if daemonize:
            with open(qemu_log, 'w') as log_file:
                qemu_process = subprocess.Popen(
                    qemu_cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT
                )

            vm_config['qemu_pid'] = qemu_process.pid
            self._save_vm_config(name, vm_config)

            logger.info(f"VM '{name}' started successfully")
            logger.info(f"QEMU PID: {qemu_process.pid}")
            if vnc_port:
                logger.info(f"VNC available on port {vnc_port}")
        else:
            subprocess.run(qemu_cmd)

        return True

    def stop_vm(self, name: str) -> bool:
        """Stop a VM"""

        vm_config = self._load_vm_config(name)
        if not vm_config:
            logger.error(f"VM '{name}' not found")
            return False

        logger.info(f"Stopping VM '{name}'...")

        # Stop QEMU
        if 'qemu_pid' in vm_config:
            try:
                subprocess.run(['kill', str(vm_config['qemu_pid'])], check=False)
                logger.info("QEMU stopped")
            except Exception as e:
                logger.warning(f"Failed to stop QEMU: {e}")

        # Disconnect NBD
        if 'nbd_device' in vm_config:
            try:
                subprocess.run(['nbd-client', '-d', vm_config['nbd_device']], check=False)
                logger.info(f"NBD device {vm_config['nbd_device']} disconnected")
            except Exception as e:
                logger.warning(f"Failed to disconnect NBD: {e}")

        # Stop NBD server
        if 'nbd_pid' in vm_config:
            try:
                subprocess.run(['kill', str(vm_config['nbd_pid'])], check=False)
                logger.info("NBD server stopped")
            except Exception as e:
                logger.warning(f"Failed to stop NBD server: {e}")

        # Clean up PIDs from config
        if 'qemu_pid' in vm_config:
            del vm_config['qemu_pid']
        if 'nbd_pid' in vm_config:
            del vm_config['nbd_pid']
        self._save_vm_config(name, vm_config)

        logger.info(f"VM '{name}' stopped")
        return True

    def delete_vm(self, name: str, delete_disk: bool = False) -> bool:
        """Delete a VM"""

        vm_config = self._load_vm_config(name)
        if not vm_config:
            logger.error(f"VM '{name}' not found")
            return False

        # Stop VM if running
        self.stop_vm(name)

        # Delete disk volume if requested
        if delete_disk:
            logger.info(f"Deleting disk volume {vm_config['volume']}...")
            self.client.delete_volume(vm_config['volume'])

        # Delete configuration
        config_file = os.path.join(self.config_dir, f'{name}.json')
        os.remove(config_file)

        logger.info(f"VM '{name}' deleted")
        return True

    def list_vms(self) -> list:
        """List all VMs"""
        vms = []
        for config_file in os.listdir(self.config_dir):
            if config_file.endswith('.json') and not config_file.endswith('-nbd.log'):
                name = config_file[:-5]
                vm_config = self._load_vm_config(name)
                if vm_config:
                    vm_config['running'] = 'qemu_pid' in vm_config
                    vms.append(vm_config)
        return vms

    def _build_qemu_command(self, vm_config: dict, vnc_port: int = None) -> list:
        """Build QEMU command line"""

        cmd = [
            'qemu-system-x86_64',
            '-name', vm_config['name'],
            '-m', str(vm_config['memory']),
            '-smp', str(vm_config['cpus']),
            '-drive', f"file={vm_config['nbd_device']},format=raw,if=virtio,cache=none",
            '-net', 'nic,model=virtio',
            '-net', 'user',
        ]

        # Add ISO if provided
        if vm_config.get('iso'):
            cmd.extend(['-cdrom', vm_config['iso']])

        # Add VNC or display
        if vnc_port:
            cmd.extend(['-vnc', f':{vnc_port - 5900}'])
        else:
            cmd.extend(['-nographic'])

        # Enable KVM if available
        if os.path.exists('/dev/kvm'):
            cmd.extend(['-enable-kvm'])

        return cmd

    def _load_vm_config(self, name: str) -> dict:
        """Load VM configuration"""
        config_file = os.path.join(self.config_dir, f'{name}.json')
        if not os.path.exists(config_file):
            return None

        with open(config_file, 'r') as f:
            return json.load(f)

    def _save_vm_config(self, name: str, config: dict):
        """Save VM configuration"""
        config_file = os.path.join(self.config_dir, f'{name}.json')
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def _get_next_nbd_device(self) -> int:
        """Get next available NBD device number"""
        used = set()
        for vm in self.list_vms():
            if 'nbd_device' in vm:
                # Extract number from /dev/nbdX
                num = int(vm['nbd_device'].replace('/dev/nbd', ''))
                used.add(num)

        for i in range(16):
            if i not in used:
                return i
        return 0

    def _get_next_nbd_port(self) -> int:
        """Get next available NBD port"""
        base_port = 10809
        used = set()
        for vm in self.list_vms():
            if 'nbd_port' in vm:
                used.add(vm['nbd_port'])

        for i in range(100):
            port = base_port + i
            if port not in used:
                return port
        return base_port


def main():
    parser = argparse.ArgumentParser(description='DistFS VM Manager')
    parser.add_argument('--metadata-server', required=True, help='Metadata server address (host:port)')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Create VM
    create_parser = subparsers.add_parser('create', help='Create a new VM')
    create_parser.add_argument('--name', required=True, help='VM name')
    create_parser.add_argument('--disk-size', required=True, help='Disk size (e.g., 10G)')
    create_parser.add_argument('--memory', type=int, default=2048, help='Memory in MB (default: 2048)')
    create_parser.add_argument('--cpus', type=int, default=2, help='Number of CPUs (default: 2)')
    create_parser.add_argument('--iso', help='ISO file for installation')
    create_parser.add_argument('--replicas', type=int, default=2, help='Disk replicas (default: 2)')

    # Start VM
    start_parser = subparsers.add_parser('start', help='Start a VM')
    start_parser.add_argument('--name', required=True, help='VM name')
    start_parser.add_argument('--vnc-port', type=int, help='VNC port (e.g., 5900)')
    start_parser.add_argument('--foreground', action='store_true', help='Run in foreground')

    # Stop VM
    stop_parser = subparsers.add_parser('stop', help='Stop a VM')
    stop_parser.add_argument('--name', required=True, help='VM name')

    # Delete VM
    delete_parser = subparsers.add_parser('delete', help='Delete a VM')
    delete_parser.add_argument('--name', required=True, help='VM name')
    delete_parser.add_argument('--delete-disk', action='store_true', help='Also delete disk volume')

    # List VMs
    list_parser = subparsers.add_parser('list', help='List all VMs')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Check for root if needed
    if args.command in ['start', 'stop'] and os.geteuid() != 0:
        logger.error("This command requires root privileges (for NBD operations)")
        sys.exit(1)

    manager = VMManager(args.metadata_server)

    try:
        if args.command == 'create':
            vm_config = manager.create_vm(
                args.name,
                args.disk_size,
                args.memory,
                args.cpus,
                args.iso,
                args.replicas
            )
            if vm_config:
                print(json.dumps(vm_config, indent=2))

        elif args.command == 'start':
            success = manager.start_vm(args.name, args.vnc_port, not args.foreground)
            sys.exit(0 if success else 1)

        elif args.command == 'stop':
            success = manager.stop_vm(args.name)
            sys.exit(0 if success else 1)

        elif args.command == 'delete':
            success = manager.delete_vm(args.name, args.delete_disk)
            sys.exit(0 if success else 1)

        elif args.command == 'list':
            vms = manager.list_vms()
            if vms:
                print(f"\n{'Name':<20} {'Disk Volume':<30} {'Memory':<10} {'CPUs':<6} {'Status':<10}")
                print("-" * 85)
                for vm in vms:
                    status = 'Running' if vm.get('running') else 'Stopped'
                    print(f"{vm['name']:<20} {vm['volume']:<30} {vm['memory']:<10} "
                          f"{vm['cpus']:<6} {status:<10}")
            else:
                print("No VMs found")

    except Exception as e:
        logger.error(f"Command failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
