#!/usr/bin/env python3
"""
DistFS NBD (Network Block Device) Server

Exposes DistFS volumes as Linux block devices using the NBD protocol.
This allows KVM/QEMU to use distributed storage as virtual disks.

NBD Protocol: https://github.com/NetworkBlockDevice/nbd/blob/master/doc/proto.md
"""

import argparse
import logging
import socket
import struct
import threading
from typing import Optional
import sys
import os

from distfs_client import DistFSClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('nbd-server')

# NBD Protocol Constants
NBD_MAGIC = 0x4e42444d41474943  # "NBDMAGIC"
NBD_OPTS_MAGIC = 0x49484156454F5054  # "IHAVEOPT"
NBD_REP_MAGIC = 0x3e889045565a9  # Reply magic
NBD_REQUEST_MAGIC = 0x25609513
NBD_REPLY_MAGIC = 0x67446698

# NBD Commands
NBD_CMD_READ = 0
NBD_CMD_WRITE = 1
NBD_CMD_DISC = 2
NBD_CMD_FLUSH = 3
NBD_CMD_TRIM = 4

# NBD Options
NBD_OPT_EXPORT_NAME = 1
NBD_OPT_ABORT = 2
NBD_OPT_LIST = 3
NBD_OPT_GO = 7

# NBD Reply Types
NBD_REP_ACK = 1
NBD_REP_SERVER = 2
NBD_REP_ERR_UNSUP = 2**31 + 1

# NBD Flags
NBD_FLAG_HAS_FLAGS = (1 << 0)
NBD_FLAG_READ_ONLY = (1 << 1)
NBD_FLAG_SEND_FLUSH = (1 << 2)
NBD_FLAG_SEND_FUA = (1 << 3)
NBD_FLAG_ROTATIONAL = (1 << 4)
NBD_FLAG_SEND_TRIM = (1 << 5)

# NBD Handshake Flags
NBD_FLAG_FIXED_NEWSTYLE = (1 << 0)
NBD_FLAG_NO_ZEROES = (1 << 1)

# Error codes
NBD_SUCCESS = 0
NBD_EPERM = 1
NBD_EIO = 5
NBD_ENOMEM = 12
NBD_EINVAL = 22
NBD_ENOSPC = 28


class NBDServer:
    """NBD Server for exposing DistFS volumes as block devices"""

    def __init__(self, volume_name: str, metadata_server: str, read_only: bool = False):
        self.volume_name = volume_name
        self.read_only = read_only
        self.client = DistFSClient(metadata_server)

        # Get volume information
        self.volume = self.client.get_volume(volume_name)
        if not self.volume:
            raise ValueError(f"Volume '{volume_name}' not found")

        self.size = self.volume['size_bytes']
        self.chunk_size = self.volume['chunk_size']

        logger.info(f"NBD server initialized for volume '{volume_name}'")
        logger.info(f"Volume size: {self.size} bytes ({self.size / (1024**3):.2f} GB)")
        logger.info(f"Read-only: {read_only}")

    def handle_client(self, client_socket: socket.socket, address):
        """Handle NBD client connection"""
        logger.info(f"Client connected from {address}")

        try:
            # NBD Handshake
            if not self._handshake(client_socket):
                logger.error("Handshake failed")
                return

            # Handle requests
            self._handle_requests(client_socket)

        except Exception as e:
            logger.error(f"Error handling client: {e}")
        finally:
            client_socket.close()
            logger.info(f"Client disconnected from {address}")

    def _handshake(self, sock: socket.socket) -> bool:
        """Perform NBD handshake"""
        try:
            # Send initial greeting
            # NBDMAGIC + IHAVEOPT + handshake flags
            flags = NBD_FLAG_FIXED_NEWSTYLE | NBD_FLAG_NO_ZEROES
            greeting = struct.pack('>QQH', NBD_MAGIC, NBD_OPTS_MAGIC, flags)
            sock.sendall(greeting)

            # Read client flags
            client_flags_data = sock.recv(4)
            if len(client_flags_data) != 4:
                return False

            client_flags = struct.unpack('>I', client_flags_data)[0]
            logger.debug(f"Client flags: {client_flags:#x}")

            # Handle options
            while True:
                # Read option header: IHAVEOPT + option + length
                opt_header = sock.recv(16)
                if len(opt_header) != 16:
                    return False

                magic, option, length = struct.unpack('>QII', opt_header)

                if magic != NBD_OPTS_MAGIC:
                    logger.error(f"Invalid option magic: {magic:#x}")
                    return False

                # Read option data
                opt_data = b''
                if length > 0:
                    opt_data = sock.recv(length)

                logger.debug(f"Received option: {option}, length: {length}")

                if option == NBD_OPT_EXPORT_NAME:
                    # Client wants to use the export
                    export_name = opt_data.decode('utf-8')
                    logger.info(f"Client requesting export: '{export_name}'")

                    # Send export info: size + transmission flags
                    trans_flags = NBD_FLAG_HAS_FLAGS | NBD_FLAG_SEND_FLUSH
                    if self.read_only:
                        trans_flags |= NBD_FLAG_READ_ONLY

                    export_info = struct.pack('>QH', self.size, trans_flags)
                    sock.sendall(export_info)

                    # No trailing zeroes with NBD_FLAG_NO_ZEROES
                    return True

                elif option == NBD_OPT_ABORT:
                    logger.info("Client aborted")
                    return False

                elif option == NBD_OPT_LIST:
                    # Send list of exports
                    self._send_option_reply(sock, option, NBD_REP_SERVER, self.volume_name.encode())
                    self._send_option_reply(sock, option, NBD_REP_ACK, b'')

                elif option == NBD_OPT_GO:
                    # Modern way to start transmission
                    export_name = opt_data.decode('utf-8')
                    logger.info(f"Client GO request for: '{export_name}'")

                    # Send export info in reply
                    trans_flags = NBD_FLAG_HAS_FLAGS | NBD_FLAG_SEND_FLUSH
                    if self.read_only:
                        trans_flags |= NBD_FLAG_READ_ONLY

                    # Send NBD_INFO_EXPORT
                    info_type = 0  # NBD_INFO_EXPORT
                    info_data = struct.pack('>QH', self.size, trans_flags)
                    self._send_option_reply(sock, option, NBD_REP_ACK, struct.pack('>H', info_type) + info_data)

                    return True

                else:
                    # Unsupported option
                    logger.warning(f"Unsupported option: {option}")
                    self._send_option_reply(sock, option, NBD_REP_ERR_UNSUP, b'')

        except Exception as e:
            logger.error(f"Handshake error: {e}")
            return False

    def _send_option_reply(self, sock: socket.socket, option: int, reply_type: int, data: bytes):
        """Send option reply"""
        reply = struct.pack('>QII', NBD_REP_MAGIC, option, reply_type)
        reply += struct.pack('>I', len(data))
        reply += data
        sock.sendall(reply)

    def _handle_requests(self, sock: socket.socket):
        """Handle NBD read/write requests"""
        while True:
            try:
                # Read request header: magic + flags + type + handle + offset + length
                header = sock.recv(28)
                if len(header) != 28:
                    break

                magic, flags, cmd_type, handle, offset, length = struct.unpack('>IHHQQI', header)

                if magic != NBD_REQUEST_MAGIC:
                    logger.error(f"Invalid request magic: {magic:#x}")
                    break

                logger.debug(f"Request: type={cmd_type}, offset={offset}, length={length}")

                if cmd_type == NBD_CMD_READ:
                    self._handle_read(sock, handle, offset, length)

                elif cmd_type == NBD_CMD_WRITE:
                    self._handle_write(sock, handle, offset, length)

                elif cmd_type == NBD_CMD_DISC:
                    logger.info("Client requested disconnect")
                    break

                elif cmd_type == NBD_CMD_FLUSH:
                    self._handle_flush(sock, handle)

                elif cmd_type == NBD_CMD_TRIM:
                    # Trim/discard - just acknowledge
                    self._send_reply(sock, handle, NBD_SUCCESS)

                else:
                    logger.warning(f"Unsupported command: {cmd_type}")
                    self._send_reply(sock, handle, NBD_EINVAL)

            except Exception as e:
                logger.error(f"Error handling request: {e}")
                break

    def _handle_read(self, sock: socket.socket, handle: int, offset: int, length: int):
        """Handle read request"""
        try:
            # Read data from DistFS
            data = self.client.read_data(self.volume_name, offset, length)

            if data is None:
                self._send_reply(sock, handle, NBD_EIO)
                return

            # Ensure we have the right amount of data
            if len(data) < length:
                data += b'\x00' * (length - len(data))

            # Send reply with data
            self._send_reply(sock, handle, NBD_SUCCESS, data)

        except Exception as e:
            logger.error(f"Read error: {e}")
            self._send_reply(sock, handle, NBD_EIO)

    def _handle_write(self, sock: socket.socket, handle: int, offset: int, length: int):
        """Handle write request"""
        try:
            if self.read_only:
                self._send_reply(sock, handle, NBD_EPERM)
                return

            # Read data from socket
            data = b''
            while len(data) < length:
                chunk = sock.recv(length - len(data))
                if not chunk:
                    raise Exception("Connection closed while reading data")
                data += chunk

            # Write data to DistFS
            success = self.client.write_data(self.volume_name, offset, data)

            if success:
                self._send_reply(sock, handle, NBD_SUCCESS)
            else:
                self._send_reply(sock, handle, NBD_EIO)

        except Exception as e:
            logger.error(f"Write error: {e}")
            self._send_reply(sock, handle, NBD_EIO)

    def _handle_flush(self, sock: socket.socket, handle: int):
        """Handle flush request"""
        # For now, just acknowledge (data is written immediately)
        self._send_reply(sock, handle, NBD_SUCCESS)

    def _send_reply(self, sock: socket.socket, handle: int, error: int, data: bytes = b''):
        """Send NBD reply"""
        reply = struct.pack('>IIQ', NBD_REPLY_MAGIC, error, handle)
        sock.sendall(reply + data)


def setup_nbd_device(nbd_device: str, server_host: str, server_port: int):
    """Setup NBD kernel module and connect device"""
    import subprocess

    try:
        # Load NBD kernel module
        logger.info("Loading NBD kernel module...")
        subprocess.run(['modprobe', 'nbd'], check=True)

        # Connect NBD device
        logger.info(f"Connecting {nbd_device} to {server_host}:{server_port}...")
        subprocess.run(['nbd-client', server_host, str(server_port), nbd_device], check=True)

        logger.info(f"NBD device {nbd_device} ready!")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to setup NBD device: {e}")
        return False


def disconnect_nbd_device(nbd_device: str):
    """Disconnect NBD device"""
    import subprocess

    try:
        logger.info(f"Disconnecting {nbd_device}...")
        subprocess.run(['nbd-client', '-d', nbd_device], check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to disconnect NBD device: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='DistFS NBD Server')
    parser.add_argument('--volume', required=True, help='Volume name to expose')
    parser.add_argument('--metadata-server', required=True, help='Metadata server address (host:port)')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=10809, help='Port to bind to (default: 10809)')
    parser.add_argument('--read-only', action='store_true', help='Export volume as read-only')
    parser.add_argument('--nbd-device', help='NBD device to setup (e.g., /dev/nbd0)')
    parser.add_argument('--foreground', action='store_true', help='Run in foreground')

    args = parser.parse_args()

    try:
        # Initialize NBD server
        nbd_server = NBDServer(args.volume, args.metadata_server, args.read_only)

        # Start TCP server
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((args.host, args.port))
        server_socket.listen(5)

        logger.info(f"NBD server listening on {args.host}:{args.port}")

        # Setup NBD device if requested
        if args.nbd_device:
            if os.geteuid() != 0:
                logger.error("NBD device setup requires root privileges")
                sys.exit(1)

            # Start server in background thread for device setup
            def accept_clients():
                while True:
                    client_sock, addr = server_socket.accept()
                    client_thread = threading.Thread(
                        target=nbd_server.handle_client,
                        args=(client_sock, addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()

            server_thread = threading.Thread(target=accept_clients, daemon=True)
            server_thread.start()

            # Give server time to start
            import time
            time.sleep(1)

            # Setup NBD device
            if setup_nbd_device(args.nbd_device, args.host, args.port):
                logger.info(f"\nNBD device ready: {args.nbd_device}")
                logger.info(f"You can now use {args.nbd_device} as a block device")
                logger.info(f"\nExample usage:")
                logger.info(f"  mkfs.ext4 {args.nbd_device}")
                logger.info(f"  mount {args.nbd_device} /mnt")

                # Keep running
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    logger.info("\nShutting down...")
                    disconnect_nbd_device(args.nbd_device)
            else:
                sys.exit(1)
        else:
            # Accept connections
            logger.info("Waiting for NBD client connections...")
            logger.info(f"\nTo connect, run:")
            logger.info(f"  sudo nbd-client {args.host} {args.port} /dev/nbd0")

            while True:
                client_sock, addr = server_socket.accept()
                client_thread = threading.Thread(
                    target=nbd_server.handle_client,
                    args=(client_sock, addr)
                )
                client_thread.daemon = not args.foreground
                client_thread.start()

    except KeyboardInterrupt:
        logger.info("\nShutting down NBD server")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
