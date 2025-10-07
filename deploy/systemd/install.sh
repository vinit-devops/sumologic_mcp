#!/bin/bash

# SystemD installation script for Sumo Logic MCP Server
set -e

# Configuration
SERVICE_NAME="sumologic-mcp"
SERVICE_USER="sumologic"
SERVICE_GROUP="sumologic"
INSTALL_DIR="/opt/sumologic-mcp"
CONFIG_DIR="/etc/sumologic-mcp"
LOG_DIR="/var/log/sumologic-mcp"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

# Create system user and group
create_user() {
    if ! id "$SERVICE_USER" &>/dev/null; then
        log_info "Creating system user: $SERVICE_USER"
        useradd --system --home-dir "$INSTALL_DIR" --shell /bin/false "$SERVICE_USER"
    else
        log_info "User $SERVICE_USER already exists"
    fi
}

# Create directories
create_directories() {
    log_info "Creating directories..."
    
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$INSTALL_DIR/logs"
    
    # Set ownership
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR"
    chown -R root:root "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"
}

# Install Python application
install_application() {
    log_info "Installing Python application..."
    
    # Create virtual environment
    python3 -m venv "$INSTALL_DIR/venv"
    
    # Copy application files
    cp -r ../sumologic_mcp "$INSTALL_DIR/"
    cp ../requirements.txt "$INSTALL_DIR/"
    cp ../pyproject.toml "$INSTALL_DIR/"
    
    # Install dependencies
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    
    # Set ownership
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
}

# Install systemd service
install_service() {
    log_info "Installing systemd service..."
    
    # Copy service file
    cp sumologic-mcp.service /etc/systemd/system/
    
    # Reload systemd
    systemctl daemon-reload
    
    log_info "Service installed successfully"
}

# Create configuration template
create_config() {
    log_info "Creating configuration template..."
    
    cat > "$CONFIG_DIR/environment" << EOF
# Sumo Logic MCP Server Configuration
# Copy this file and customize for your environment

# Required: Sumo Logic API credentials
SUMOLOGIC_ACCESS_ID=your-access-id-here
SUMOLOGIC_ACCESS_KEY=your-access-key-here

# Optional: Sumo Logic API endpoint (default: https://api.sumologic.com/api)
SUMOLOGIC_ENDPOINT=https://api.sumologic.com/api

# Optional: Logging configuration
SUMOLOGIC_LOG_LEVEL=INFO

# Optional: Performance tuning
SUMOLOGIC_TIMEOUT=30
SUMOLOGIC_MAX_RETRIES=3
SUMOLOGIC_RATE_LIMIT_DELAY=1.0
EOF

    chmod 600 "$CONFIG_DIR/environment"
    
    log_info "Configuration template created at $CONFIG_DIR/environment"
    log_warn "Please edit $CONFIG_DIR/environment with your Sumo Logic credentials"
}

# Create log rotation configuration
create_logrotate() {
    log_info "Creating log rotation configuration..."
    
    cat > /etc/logrotate.d/sumologic-mcp << EOF
$LOG_DIR/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 $SERVICE_USER $SERVICE_GROUP
    postrotate
        systemctl reload-or-restart sumologic-mcp
    endscript
}
EOF
}

# Show installation summary
show_summary() {
    log_info "Installation completed successfully!"
    echo
    echo "Service: $SERVICE_NAME"
    echo "User: $SERVICE_USER"
    echo "Install Directory: $INSTALL_DIR"
    echo "Config Directory: $CONFIG_DIR"
    echo "Log Directory: $LOG_DIR"
    echo
    echo "Next steps:"
    echo "1. Edit $CONFIG_DIR/environment with your Sumo Logic credentials"
    echo "2. Enable the service: systemctl enable $SERVICE_NAME"
    echo "3. Start the service: systemctl start $SERVICE_NAME"
    echo "4. Check status: systemctl status $SERVICE_NAME"
    echo "5. View logs: journalctl -u $SERVICE_NAME -f"
}

# Uninstall function
uninstall() {
    log_info "Uninstalling Sumo Logic MCP Server..."
    
    # Stop and disable service
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" || true
    
    # Remove service file
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
    
    # Remove directories
    rm -rf "$INSTALL_DIR"
    rm -rf "$LOG_DIR"
    
    # Remove user (optional)
    if id "$SERVICE_USER" &>/dev/null; then
        log_warn "User $SERVICE_USER still exists. Remove manually if needed: userdel $SERVICE_USER"
    fi
    
    # Remove config (optional)
    log_warn "Configuration directory $CONFIG_DIR preserved. Remove manually if needed."
    
    log_info "Uninstallation completed"
}

# Main installation function
install() {
    log_info "Starting installation of Sumo Logic MCP Server..."
    
    check_root
    create_user
    create_directories
    install_application
    install_service
    create_config
    create_logrotate
    show_summary
}

# Parse command line arguments
case "${1:-install}" in
    "install")
        install
        ;;
    "uninstall")
        uninstall
        ;;
    *)
        echo "Usage: $0 {install|uninstall}"
        echo
        echo "Commands:"
        echo "  install   - Install Sumo Logic MCP Server (default)"
        echo "  uninstall - Remove Sumo Logic MCP Server"
        exit 1
        ;;
esac