#!/bin/bash
# QEMU DistFS Helper Script
# Provides easy integration between QEMU and DistFS volumes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

error() {
    echo -e "${RED}Error: $1${NC}" >&2
    exit 1
}

info() {
    echo -e "${GREEN}$1${NC}"
}

warn() {
    echo -e "${YELLOW}$1${NC}"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "This script must be run as root (for NBD operations)"
    fi
}

check_dependencies() {
    local missing=()

    command -v qemu-system-x86_64 >/dev/null 2>&1 || missing+=("qemu-system-x86_64")
    command -v nbd-client >/dev/null 2>&1 || missing+=("nbd-client")
    command -v python3 >/dev/null 2>&1 || missing+=("python3")

    if [ ${#missing[@]} -gt 0 ]; then
        error "Missing dependencies: ${missing[*]}"
    fi
}

setup_nbd_volume() {
    local VOLUME_NAME=$1
    local METADATA_SERVER=$2
    local NBD_DEVICE=${3:-/dev/nbd0}
    local NBD_PORT=${4:-10809}

    info "Setting up NBD volume: $VOLUME_NAME"

    # Check if NBD module is loaded
    if ! lsmod | grep -q nbd; then
        info "Loading NBD kernel module..."
        modprobe nbd max_part=8
    fi

    # Start NBD server in background
    info "Starting NBD server on port $NBD_PORT..."
    python3 "$PARENT_DIR/nbd_server.py" \
        --volume "$VOLUME_NAME" \
        --metadata-server "$METADATA_SERVER" \
        --port "$NBD_PORT" \
        > "/tmp/distfs-nbd-${VOLUME_NAME}.log" 2>&1 &

    local NBD_PID=$!
    echo $NBD_PID > "/tmp/distfs-nbd-${VOLUME_NAME}.pid"

    # Wait for server to start
    sleep 2

    # Connect NBD client
    info "Connecting NBD device $NBD_DEVICE..."
    nbd-client 127.0.0.1 $NBD_PORT $NBD_DEVICE

    info "NBD device ready: $NBD_DEVICE"
    echo $NBD_DEVICE
}

cleanup_nbd_volume() {
    local VOLUME_NAME=$1
    local NBD_DEVICE=${2:-/dev/nbd0}

    info "Cleaning up NBD volume: $VOLUME_NAME"

    # Disconnect NBD device
    if [ -b "$NBD_DEVICE" ]; then
        info "Disconnecting $NBD_DEVICE..."
        nbd-client -d $NBD_DEVICE 2>/dev/null || true
    fi

    # Stop NBD server
    local PID_FILE="/tmp/distfs-nbd-${VOLUME_NAME}.pid"
    if [ -f "$PID_FILE" ]; then
        local NBD_PID=$(cat "$PID_FILE")
        if kill -0 $NBD_PID 2>/dev/null; then
            info "Stopping NBD server (PID: $NBD_PID)..."
            kill $NBD_PID 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi

    info "Cleanup complete"
}

launch_qemu() {
    local NBD_DEVICE=$1
    shift
    local QEMU_ARGS=("$@")

    info "Launching QEMU with DistFS volume..."

    # Build QEMU command
    local CMD=(
        qemu-system-x86_64
        -drive "file=${NBD_DEVICE},format=raw,if=virtio,cache=none"
    )

    # Add user arguments
    CMD+=("${QEMU_ARGS[@]}")

    # Enable KVM if available
    if [ -c /dev/kvm ]; then
        CMD+=(-enable-kvm)
    fi

    info "Running: ${CMD[*]}"
    "${CMD[@]}"
}

usage() {
    cat << EOF
QEMU DistFS Helper Script

Usage:
    $0 setup-nbd <volume-name> <metadata-server> [nbd-device] [nbd-port]
        Setup NBD device for a DistFS volume

    $0 cleanup-nbd <volume-name> [nbd-device]
        Cleanup NBD device and stop server

    $0 run <volume-name> <metadata-server> [qemu-args...]
        Setup NBD and launch QEMU in one command

    $0 attach <volume-name> <metadata-server> <nbd-device>
        Attach a DistFS volume to an NBD device

Examples:
    # Setup NBD device for volume 'myvm-disk'
    sudo $0 setup-nbd myvm-disk localhost:7001

    # Run QEMU with DistFS volume
    sudo $0 run myvm-disk localhost:7001 -m 2048 -smp 2 -vnc :0

    # Cleanup after done
    sudo $0 cleanup-nbd myvm-disk

Environment Variables:
    DISTFS_METADATA_SERVER    Default metadata server address
    DISTFS_NBD_DEVICE         Default NBD device

EOF
    exit 1
}

# Main command dispatcher
case "${1:-}" in
    setup-nbd)
        check_root
        check_dependencies
        [ $# -lt 3 ] && usage
        setup_nbd_volume "$2" "$3" "${4:-/dev/nbd0}" "${5:-10809}"
        ;;

    cleanup-nbd)
        check_root
        [ $# -lt 2 ] && usage
        cleanup_nbd_volume "$2" "${3:-/dev/nbd0}"
        ;;

    run)
        check_root
        check_dependencies
        [ $# -lt 3 ] && usage

        VOLUME_NAME=$2
        METADATA_SERVER=$3
        shift 3

        # Trap cleanup on exit
        NBD_DEVICE=/dev/nbd0
        trap "cleanup_nbd_volume $VOLUME_NAME $NBD_DEVICE" EXIT

        # Setup NBD
        setup_nbd_volume "$VOLUME_NAME" "$METADATA_SERVER" "$NBD_DEVICE"

        # Launch QEMU
        launch_qemu "$NBD_DEVICE" "$@"
        ;;

    attach)
        check_root
        check_dependencies
        [ $# -lt 4 ] && usage
        setup_nbd_volume "$2" "$3" "$4"
        ;;

    *)
        usage
        ;;
esac
