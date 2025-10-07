#!/bin/bash

# Sumo Logic MCP Server Deployment Script
set -e

# Configuration
IMAGE_NAME="sumologic-mcp"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="sumologic-mcp-server"
NETWORK_NAME="sumologic-network"

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

# Check if required environment variables are set
check_env_vars() {
    log_info "Checking required environment variables..."
    
    if [ -z "$SUMOLOGIC_ACCESS_ID" ]; then
        log_error "SUMOLOGIC_ACCESS_ID environment variable is required"
        exit 1
    fi
    
    if [ -z "$SUMOLOGIC_ACCESS_KEY" ]; then
        log_error "SUMOLOGIC_ACCESS_KEY environment variable is required"
        exit 1
    fi
    
    log_info "Environment variables check passed"
}

# Build Docker image
build_image() {
    log_info "Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}"
    
    cd "$(dirname "$0")/../.."
    docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
    
    log_info "Docker image built successfully"
}

# Create Docker network if it doesn't exist
create_network() {
    if ! docker network ls | grep -q "$NETWORK_NAME"; then
        log_info "Creating Docker network: $NETWORK_NAME"
        docker network create "$NETWORK_NAME"
    else
        log_info "Docker network $NETWORK_NAME already exists"
    fi
}

# Stop and remove existing container
cleanup_existing() {
    if docker ps -a | grep -q "$CONTAINER_NAME"; then
        log_info "Stopping and removing existing container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME" || true
        docker rm "$CONTAINER_NAME" || true
    fi
}

# Deploy container
deploy_container() {
    log_info "Deploying container: $CONTAINER_NAME"
    
    docker run -d \
        --name "$CONTAINER_NAME" \
        --network "$NETWORK_NAME" \
        --restart unless-stopped \
        -p 8000:8000 \
        -e SUMOLOGIC_ACCESS_ID="$SUMOLOGIC_ACCESS_ID" \
        -e SUMOLOGIC_ACCESS_KEY="$SUMOLOGIC_ACCESS_KEY" \
        -e SUMOLOGIC_ENDPOINT="${SUMOLOGIC_ENDPOINT:-https://api.sumologic.com/api}" \
        -e SUMOLOGIC_LOG_LEVEL="${SUMOLOGIC_LOG_LEVEL:-INFO}" \
        -e SUMOLOGIC_TIMEOUT="${SUMOLOGIC_TIMEOUT:-30}" \
        -e SUMOLOGIC_MAX_RETRIES="${SUMOLOGIC_MAX_RETRIES:-3}" \
        -e SUMOLOGIC_RATE_LIMIT_DELAY="${SUMOLOGIC_RATE_LIMIT_DELAY:-1.0}" \
        -v "$(pwd)/logs:/app/logs" \
        -v "$(pwd)/config:/app/config" \
        "${IMAGE_NAME}:${IMAGE_TAG}"
    
    log_info "Container deployed successfully"
}

# Health check
health_check() {
    log_info "Performing health check..."
    
    # Wait for container to start
    sleep 10
    
    # Check if container is running
    if ! docker ps | grep -q "$CONTAINER_NAME"; then
        log_error "Container is not running"
        docker logs "$CONTAINER_NAME"
        exit 1
    fi
    
    # Check container health
    for i in {1..30}; do
        if docker exec "$CONTAINER_NAME" python -c "import sumologic_mcp; print('OK')" >/dev/null 2>&1; then
            log_info "Health check passed"
            return 0
        fi
        log_info "Waiting for container to be ready... ($i/30)"
        sleep 2
    done
    
    log_error "Health check failed"
    docker logs "$CONTAINER_NAME"
    exit 1
}

# Show deployment info
show_info() {
    log_info "Deployment completed successfully!"
    echo
    echo "Container Name: $CONTAINER_NAME"
    echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
    echo "Network: $NETWORK_NAME"
    echo "Port: 8000"
    echo
    echo "To view logs: docker logs -f $CONTAINER_NAME"
    echo "To stop: docker stop $CONTAINER_NAME"
    echo "To restart: docker restart $CONTAINER_NAME"
}

# Main deployment function
main() {
    log_info "Starting Sumo Logic MCP Server deployment..."
    
    check_env_vars
    build_image
    create_network
    cleanup_existing
    deploy_container
    health_check
    show_info
}

# Parse command line arguments
case "${1:-deploy}" in
    "build")
        build_image
        ;;
    "deploy")
        main
        ;;
    "stop")
        log_info "Stopping container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME" || true
        ;;
    "restart")
        log_info "Restarting container: $CONTAINER_NAME"
        docker restart "$CONTAINER_NAME"
        ;;
    "logs")
        docker logs -f "$CONTAINER_NAME"
        ;;
    "cleanup")
        cleanup_existing
        log_info "Cleanup completed"
        ;;
    *)
        echo "Usage: $0 {build|deploy|stop|restart|logs|cleanup}"
        echo
        echo "Commands:"
        echo "  build    - Build Docker image only"
        echo "  deploy   - Full deployment (default)"
        echo "  stop     - Stop the container"
        echo "  restart  - Restart the container"
        echo "  logs     - Show container logs"
        echo "  cleanup  - Remove existing container"
        exit 1
        ;;
esac