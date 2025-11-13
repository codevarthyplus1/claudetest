#!/bin/bash
# DistFS Cluster Deployment Script
# Deploys DistFS across multiple nodes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
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

usage() {
    cat << EOF
DistFS Cluster Deployment

Usage:
    $0 [options]

Options:
    --metadata-node <host>        Metadata server node (required)
    --storage-nodes <host1,host2> Comma-separated storage nodes (required)
    --ssh-user <user>             SSH user (default: current user)
    --ssh-key <path>              SSH key path (default: ~/.ssh/id_rsa)
    --install-deps                Install dependencies on nodes
    --help                        Show this help

Example:
    $0 --metadata-node 192.168.1.10 \\
       --storage-nodes 192.168.1.11,192.168.1.12,192.168.1.13 \\
       --install-deps

EOF
    exit 1
}

# Parse arguments
METADATA_NODE=""
STORAGE_NODES=""
SSH_USER="$USER"
SSH_KEY="$HOME/.ssh/id_rsa"
INSTALL_DEPS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --metadata-node)
            METADATA_NODE="$2"
            shift 2
            ;;
        --storage-nodes)
            STORAGE_NODES="$2"
            shift 2
            ;;
        --ssh-user)
            SSH_USER="$2"
            shift 2
            ;;
        --ssh-key)
            SSH_KEY="$2"
            shift 2
            ;;
        --install-deps)
            INSTALL_DEPS=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Validate arguments
[ -z "$METADATA_NODE" ] && error "Metadata node is required"
[ -z "$STORAGE_NODES" ] && error "Storage nodes are required"

# Convert comma-separated list to array
IFS=',' read -ra STORAGE_NODE_ARRAY <<< "$STORAGE_NODES"

info "Deployment configuration:"
info "  Metadata node: $METADATA_NODE"
info "  Storage nodes: ${STORAGE_NODE_ARRAY[*]}"
info "  SSH user: $SSH_USER"

# SSH command helper
ssh_exec() {
    local host=$1
    shift
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_USER@$host" "$@"
}

scp_file() {
    local src=$1
    local host=$2
    local dest=$3
    scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$src" "$SSH_USER@$host:$dest"
}

# Check connectivity to all nodes
check_connectivity() {
    info "Checking connectivity to all nodes..."

    for node in "$METADATA_NODE" "${STORAGE_NODE_ARRAY[@]}"; do
        if ssh_exec "$node" "echo 'Connection OK'" >/dev/null 2>&1; then
            info "  $node: OK"
        else
            error "Cannot connect to $node"
        fi
    done
}

# Copy files to nodes
copy_files() {
    local node=$1

    info "Copying DistFS files to $node..."

    # Create directory
    ssh_exec "$node" "mkdir -p /tmp/distfs"

    # Copy all Python files
    scp_file "$SCRIPT_DIR"/*.py "$node" /tmp/distfs/

    # Copy scripts
    scp_file "$SCRIPT_DIR"/setup.sh "$node" /tmp/distfs/

    # Copy kvm_integration directory
    ssh_exec "$node" "mkdir -p /tmp/distfs/kvm_integration"
    for file in "$SCRIPT_DIR"/kvm_integration/*; do
        if [ -f "$file" ]; then
            scp_file "$file" "$node" /tmp/distfs/kvm_integration/
        fi
    done
}

# Install dependencies
install_dependencies() {
    local node=$1

    info "Installing dependencies on $node..."

    if [ "$INSTALL_DEPS" = true ]; then
        ssh_exec "$node" "cd /tmp/distfs && bash setup.sh" || warn "Setup script failed on $node"
    fi

    # Ensure directories exist
    ssh_exec "$node" "sudo mkdir -p /var/distfs/{metadata,storage} && sudo chown -R $SSH_USER:$SSH_USER /var/distfs"
}

# Deploy metadata service
deploy_metadata_service() {
    info "Deploying metadata service on $METADATA_NODE..."

    copy_files "$METADATA_NODE"
    install_dependencies "$METADATA_NODE"

    # Copy files to /opt/distfs
    ssh_exec "$METADATA_NODE" "sudo mkdir -p /opt/distfs && sudo cp -r /tmp/distfs/* /opt/distfs/"

    # Create systemd service
    ssh_exec "$METADATA_NODE" "cat << 'EOF' | sudo tee /etc/systemd/system/distfs-metadata.service > /dev/null
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
EOF"

    # Start service
    ssh_exec "$METADATA_NODE" "sudo systemctl daemon-reload && sudo systemctl enable distfs-metadata && sudo systemctl restart distfs-metadata"

    info "Metadata service deployed and started"

    # Wait for service to start
    sleep 3

    # Check health
    if ssh_exec "$METADATA_NODE" "curl -s http://localhost:7001/health" | grep -q healthy; then
        info "Metadata service is healthy"
    else
        warn "Metadata service may not be running correctly"
    fi
}

# Deploy storage service
deploy_storage_service() {
    local node=$1

    info "Deploying storage service on $node..."

    copy_files "$node"
    install_dependencies "$node"

    # Copy files to /opt/distfs
    ssh_exec "$node" "sudo mkdir -p /opt/distfs && sudo cp -r /tmp/distfs/* /opt/distfs/"

    # Create systemd service
    ssh_exec "$node" "cat << EOF | sudo tee /etc/systemd/system/distfs-storage.service > /dev/null
[Unit]
Description=DistFS Storage Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/distfs
ExecStart=/usr/bin/python3 /opt/distfs/storage_server.py --data-dir /var/distfs/storage --metadata-server $METADATA_NODE:7001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"

    # Start service
    ssh_exec "$node" "sudo systemctl daemon-reload && sudo systemctl enable distfs-storage && sudo systemctl restart distfs-storage"

    info "Storage service deployed on $node"
}

# Verify cluster
verify_cluster() {
    info "Verifying cluster..."

    sleep 5

    # Check nodes via metadata server
    local nodes_json=$(ssh_exec "$METADATA_NODE" "curl -s http://localhost:7001/nodes")

    local node_count=$(echo "$nodes_json" | grep -o '"node_id"' | wc -l)

    info "Cluster has $node_count registered storage nodes"

    if [ "$node_count" -eq "${#STORAGE_NODE_ARRAY[@]}" ]; then
        info "All storage nodes registered successfully!"
    else
        warn "Expected ${#STORAGE_NODE_ARRAY[@]} nodes, but only $node_count are registered"
    fi
}

# Show cluster status
show_status() {
    info "Cluster deployed successfully!"
    echo ""
    echo "Cluster configuration:"
    echo "  Metadata server: $METADATA_NODE:7001"
    echo "  Storage nodes: ${#STORAGE_NODE_ARRAY[@]}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Check cluster health:"
    echo "   python3 distfs_client.py --metadata-server $METADATA_NODE:7001 health"
    echo ""
    echo "2. List storage nodes:"
    echo "   python3 distfs_client.py --metadata-server $METADATA_NODE:7001 list-nodes"
    echo ""
    echo "3. Create a volume:"
    echo "   python3 distfs_client.py --metadata-server $METADATA_NODE:7001 create-volume --name test --size 10G"
    echo ""
    echo "4. Create a VM (on any node with NBD access):"
    echo "   sudo python3 kvm_integration/distfs_vm_manager.py --metadata-server $METADATA_NODE:7001 create --name myvm --disk-size 20G"
    echo ""
}

# Main deployment flow
main() {
    check_connectivity

    deploy_metadata_service

    for storage_node in "${STORAGE_NODE_ARRAY[@]}"; do
        deploy_storage_service "$storage_node"
    done

    verify_cluster
    show_status
}

main
