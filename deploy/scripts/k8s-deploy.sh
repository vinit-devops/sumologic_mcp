#!/bin/bash

# Kubernetes deployment script for Sumo Logic MCP Server
set -e

# Configuration
NAMESPACE="${NAMESPACE:-default}"
IMAGE_NAME="sumologic-mcp"
IMAGE_TAG="${IMAGE_TAG:-latest}"

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

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if kubectl is installed
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if we can connect to cluster
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    # Check required environment variables
    if [ -z "$SUMOLOGIC_ACCESS_ID" ]; then
        log_error "SUMOLOGIC_ACCESS_ID environment variable is required"
        exit 1
    fi
    
    if [ -z "$SUMOLOGIC_ACCESS_KEY" ]; then
        log_error "SUMOLOGIC_ACCESS_KEY environment variable is required"
        exit 1
    fi
    
    log_info "Prerequisites check passed"
}

# Create namespace if it doesn't exist
create_namespace() {
    if [ "$NAMESPACE" != "default" ]; then
        if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
            log_info "Creating namespace: $NAMESPACE"
            kubectl create namespace "$NAMESPACE"
        else
            log_info "Namespace $NAMESPACE already exists"
        fi
    fi
}

# Create secret with Sumo Logic credentials
create_secret() {
    log_info "Creating Sumo Logic credentials secret..."
    
    # Delete existing secret if it exists
    kubectl delete secret sumologic-credentials -n "$NAMESPACE" --ignore-not-found=true
    
    # Create new secret
    kubectl create secret generic sumologic-credentials \
        --from-literal=access-id="$SUMOLOGIC_ACCESS_ID" \
        --from-literal=access-key="$SUMOLOGIC_ACCESS_KEY" \
        -n "$NAMESPACE"
    
    log_info "Secret created successfully"
}

# Apply Kubernetes manifests
apply_manifests() {
    log_info "Applying Kubernetes manifests..."
    
    cd "$(dirname "$0")/../kubernetes"
    
    # Apply ConfigMaps
    kubectl apply -f configmap.yaml -n "$NAMESPACE"
    
    # Apply Service
    kubectl apply -f service.yaml -n "$NAMESPACE"
    
    # Apply Deployment
    kubectl apply -f deployment.yaml -n "$NAMESPACE"
    
    log_info "Manifests applied successfully"
}

# Wait for deployment to be ready
wait_for_deployment() {
    log_info "Waiting for deployment to be ready..."
    
    kubectl rollout status deployment/sumologic-mcp-server -n "$NAMESPACE" --timeout=300s
    
    log_info "Deployment is ready"
}

# Health check
health_check() {
    log_info "Performing health check..."
    
    # Get pod name
    POD_NAME=$(kubectl get pods -l app=sumologic-mcp-server -n "$NAMESPACE" -o jsonpath='{.items[0].metadata.name}')
    
    if [ -z "$POD_NAME" ]; then
        log_error "No pods found for sumologic-mcp-server"
        exit 1
    fi
    
    # Check pod health
    for i in {1..30}; do
        if kubectl exec "$POD_NAME" -n "$NAMESPACE" -- python -c "import sumologic_mcp; print('OK')" >/dev/null 2>&1; then
            log_info "Health check passed"
            return 0
        fi
        log_info "Waiting for pod to be ready... ($i/30)"
        sleep 2
    done
    
    log_error "Health check failed"
    kubectl logs "$POD_NAME" -n "$NAMESPACE"
    exit 1
}

# Show deployment info
show_info() {
    log_info "Deployment completed successfully!"
    echo
    echo "Namespace: $NAMESPACE"
    echo "Deployment: sumologic-mcp-server"
    echo "Service: sumologic-mcp-service"
    echo
    echo "To view pods: kubectl get pods -n $NAMESPACE"
    echo "To view logs: kubectl logs -l app=sumologic-mcp-server -n $NAMESPACE -f"
    echo "To port-forward: kubectl port-forward service/sumologic-mcp-service 8000:8000 -n $NAMESPACE"
    
    # Show service info
    kubectl get service sumologic-mcp-service -n "$NAMESPACE"
}

# Main deployment function
deploy() {
    log_info "Starting Kubernetes deployment..."
    
    check_prerequisites
    create_namespace
    create_secret
    apply_manifests
    wait_for_deployment
    health_check
    show_info
}

# Cleanup function
cleanup() {
    log_info "Cleaning up Kubernetes resources..."
    
    cd "$(dirname "$0")/../kubernetes"
    
    kubectl delete -f deployment.yaml -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete -f service.yaml -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete -f configmap.yaml -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete secret sumologic-credentials -n "$NAMESPACE" --ignore-not-found=true
    
    if [ "$NAMESPACE" != "default" ]; then
        kubectl delete namespace "$NAMESPACE" --ignore-not-found=true
    fi
    
    log_info "Cleanup completed"
}

# Parse command line arguments
case "${1:-deploy}" in
    "deploy")
        deploy
        ;;
    "cleanup")
        cleanup
        ;;
    "status")
        kubectl get all -l app=sumologic-mcp-server -n "$NAMESPACE"
        ;;
    "logs")
        kubectl logs -l app=sumologic-mcp-server -n "$NAMESPACE" -f
        ;;
    "port-forward")
        kubectl port-forward service/sumologic-mcp-service 8000:8000 -n "$NAMESPACE"
        ;;
    *)
        echo "Usage: $0 {deploy|cleanup|status|logs|port-forward}"
        echo
        echo "Commands:"
        echo "  deploy       - Deploy to Kubernetes (default)"
        echo "  cleanup      - Remove all resources"
        echo "  status       - Show deployment status"
        echo "  logs         - Show container logs"
        echo "  port-forward - Forward local port 8000 to service"
        echo
        echo "Environment variables:"
        echo "  NAMESPACE            - Kubernetes namespace (default: default)"
        echo "  SUMOLOGIC_ACCESS_ID  - Sumo Logic Access ID (required)"
        echo "  SUMOLOGIC_ACCESS_KEY - Sumo Logic Access Key (required)"
        exit 1
        ;;
esac