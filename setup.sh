#!/bin/bash
# DistFS Setup Script
# Installs dependencies and sets up DistFS cluster

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

banner() {
    echo -e "${BLUE}"
    cat << "EOF"
    ____  _      __  ______
   / __ \(_)____/ /_/ ____/____
  / / / / / ___/ __/ /_  / ___/
 / /_/ / (__  ) /_/ __/ (__  )
/_____/_/____/\__/_/   /____/

Distributed File System for KVM
EOF
    echo -e "${NC}"
}

check_os() {
    info "Checking operating system..."

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
        info "Detected: $OS $VER"
    else
        error "Cannot detect OS. /etc/os-release not found."
    fi
}

install_dependencies() {
    info "Installing dependencies..."

    case "$OS" in
        ubuntu|debian)
            sudo apt-get update
            sudo apt-get install -y \
                python3 \
                python3-pip \
                nbd-client \
                nbd-server \
                qemu-kvm \
                qemu-system-x86 \
                libvirt-daemon-system \
                libvirt-clients \
                bridge-utils \
                || warn "Some packages failed to install"

            # Install Python dependencies
            pip3 install requests || sudo pip3 install requests
            ;;

        centos|rhel|fedora)
            sudo yum install -y \
                python3 \
                python3-pip \
                nbd \
                qemu-kvm \
                qemu-img \
                libvirt \
                libvirt-client \
                || warn "Some packages failed to install"

            pip3 install requests || sudo pip3 install requests
            ;;

        arch)
            sudo pacman -Sy --noconfirm \
                python \
                python-pip \
                nbd \
                qemu \
                libvirt \
                || warn "Some packages failed to install"

            pip3 install requests
            ;;

        *)
            warn "Unknown OS: $OS"
            warn "Please install manually:"
            echo "  - Python 3.8+"
            echo "  - python3-requests"
            echo "  - nbd-client"
            echo "  - qemu-kvm"
            ;;
    esac

    info "Dependencies installed"
}

setup_directories() {
    info "Setting up directories..."

    # Create data directories
    sudo mkdir -p /var/distfs/{metadata,storage}
    sudo chown -R $USER:$USER /var/distfs

    # Create config directories
    mkdir -p ~/.distfs/vms

    info "Directories created"
}

load_kernel_modules() {
    info "Loading kernel modules..."

    # Load NBD module
    if ! lsmod | grep -q nbd; then
        sudo modprobe nbd max_part=16
        info "NBD module loaded"
    else
        info "NBD module already loaded"
    fi

    # Make NBD module load on boot
    if [ ! -f /etc/modules-load.d/distfs.conf ]; then
        echo "nbd" | sudo tee /etc/modules-load.d/distfs.conf > /dev/null
        info "NBD module configured to load on boot"
    fi

    # Check KVM
    if [ -c /dev/kvm ]; then
        info "KVM available"
    else
        warn "KVM not available. VMs will run without hardware acceleration."
    fi
}

create_systemd_services() {
    info "Creating systemd service files..."

    # Metadata service
    cat << 'EOF' | sudo tee /etc/systemd/system/distfs-metadata.service > /dev/null
[Unit]
Description=DistFS Metadata Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/distfs
ExecStart=/usr/bin/python3 /opt/distfs/metadata_service.py --host 0.0.0.0 --port 7001 --data-dir /var/distfs/metadata
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Storage service
    cat << 'EOF' | sudo tee /etc/systemd/system/distfs-storage.service > /dev/null
[Unit]
Description=DistFS Storage Service
After=network.target distfs-metadata.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/distfs
ExecStart=/usr/bin/python3 /opt/distfs/storage_server.py --data-dir /var/distfs/storage --metadata-server localhost:7001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload

    info "Systemd services created"
}

install_distfs() {
    info "Installing DistFS..."

    # Copy files to /opt/distfs
    sudo mkdir -p /opt/distfs
    sudo cp -r . /opt/distfs/

    # Make scripts executable
    sudo chmod +x /opt/distfs/*.py
    sudo chmod +x /opt/distfs/kvm_integration/*.py
    sudo chmod +x /opt/distfs/kvm_integration/*.sh

    # Create symlinks
    sudo ln -sf /opt/distfs/distfs_client.py /usr/local/bin/distfs
    sudo ln -sf /opt/distfs/kvm_integration/distfs_vm_manager.py /usr/local/bin/distfs-vm

    info "DistFS installed to /opt/distfs"
}

show_next_steps() {
    echo ""
    info "DistFS installation complete!"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Start metadata service:"
    echo "   sudo systemctl start distfs-metadata"
    echo ""
    echo "2. Start storage service:"
    echo "   sudo systemctl start distfs-storage"
    echo ""
    echo "3. Check cluster health:"
    echo "   distfs --metadata-server localhost:7001 health"
    echo ""
    echo "4. Create a volume:"
    echo "   distfs --metadata-server localhost:7001 create-volume --name test-volume --size 10G"
    echo ""
    echo "5. Create a VM:"
    echo "   sudo distfs-vm --metadata-server localhost:7001 create --name myvm --disk-size 20G"
    echo ""
    echo "6. Start the VM:"
    echo "   sudo distfs-vm --metadata-server localhost:7001 start --name myvm"
    echo ""
    echo "For more information, see:"
    echo "  - README.md"
    echo "  - docs/QUICKSTART.md"
    echo "  - docs/KVM_INTEGRATION.md"
    echo ""
}

main() {
    banner

    if [ "$EUID" -eq 0 ]; then
        error "Please run this script as a regular user (it will use sudo when needed)"
    fi

    check_os
    install_dependencies
    setup_directories
    load_kernel_modules
    install_distfs
    create_systemd_services

    show_next_steps
}

# Run main if not sourced
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
