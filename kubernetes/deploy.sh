#!/bin/bash
# OpenAlgo Kubernetes Deployment Script

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="openalgo"
KUBECTL="kubectl"

# Functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    print_info "Checking prerequisites..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl not found. Please install kubectl first."
        exit 1
    fi
    
    # Check cluster connection
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to Kubernetes cluster. Check your kubeconfig."
        exit 1
    fi
    
    print_info "Prerequisites check passed!"
}

check_secrets() {
    if [ ! -f "secrets.yaml" ]; then
        print_error "secrets.yaml not found!"
        print_warn "Please copy secrets-template.yaml to secrets.yaml and fill in your values:"
        print_warn "  cp secrets-template.yaml secrets.yaml"
        print_warn "  nano secrets.yaml"
        exit 1
    fi
    
    # Check if secrets still contain template values
    if grep -q "change-this-to-secure-random-string" secrets.yaml; then
        print_warn "secrets.yaml still contains template values!"
        print_warn "Please update secrets.yaml with your actual configuration."
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

deploy() {
    print_info "Deploying OpenAlgo to Kubernetes..."
    
    # Create namespace
    print_info "Creating namespace: $NAMESPACE"
    $KUBECTL apply -f namespace.yaml
    
    # Create PVCs
    print_info "Creating PersistentVolumeClaims..."
    $KUBECTL apply -f pvcs.yaml
    
    # Wait for PVCs to bind
    print_info "Waiting for PVCs to bind..."
    $KUBECTL wait --for=jsonpath='{.status.phase}'=Bound pvc --all -n $NAMESPACE --timeout=60s || {
        print_warn "Some PVCs are not bound yet. This might be normal if using dynamic provisioning."
    }
    
    # Create ConfigMap
    print_info "Creating ConfigMap..."
    $KUBECTL apply -f configmap.yaml
    
    # Create Secrets
    print_info "Creating Secrets..."
    $KUBECTL apply -f secrets.yaml
    
    # Deploy application
    print_info "Deploying application StatefulSet..."
    $KUBECTL apply -f statefulset.yaml
    
    # Create Service
    print_info "Creating Service..."
    $KUBECTL apply -f service.yaml
    
    # Create Ingress
    print_info "Creating Ingress..."
    $KUBECTL apply -f ingress.yaml
    
    print_info "Deployment initiated successfully!"
    print_info "Waiting for pod to be ready..."
    
    $KUBECTL wait --for=condition=ready pod -l app=openalgo -n $NAMESPACE --timeout=300s || {
        print_warn "Pod not ready after 5 minutes. Check pod status:"
        print_warn "  kubectl get pods -n $NAMESPACE"
        print_warn "  kubectl logs -f statefulset/openalgo -n $NAMESPACE"
    }
}

status() {
    print_info "Checking OpenAlgo deployment status..."
    
    echo
    print_info "Pods:"
    $KUBECTL get pods -n $NAMESPACE
    
    echo
    print_info "Services:"
    $KUBECTL get svc -n $NAMESPACE
    
    echo
    print_info "Ingress:"
    $KUBECTL get ingress -n $NAMESPACE
    
    echo
    print_info "PersistentVolumeClaims:"
    $KUBECTL get pvc -n $NAMESPACE
    
    echo
    print_info "To view logs:"
    echo "  kubectl logs -f statefulset/openalgo -n $NAMESPACE"
    
    echo
    print_info "To access the application:"
    echo "  kubectl port-forward -n $NAMESPACE svc/openalgo 5000:5000"
    echo "  Then open http://localhost:5000"
}

undeploy() {
    print_warn "This will delete all OpenAlgo resources including data!"
    read -p "Are you sure? (yes/NO) " -r
    echo
    if [[ ! $REPLY == "yes" ]]; then
        print_info "Cancelled."
        exit 0
    fi
    
    print_info "Undeploying OpenAlgo..."
    
    $KUBECTL delete -f ingress.yaml || true
    $KUBECTL delete -f service.yaml || true
    $KUBECTL delete -f statefulset.yaml || true
    $KUBECTL delete -f secrets.yaml || true
    $KUBECTL delete -f configmap.yaml || true
    $KUBECTL delete -f pvcs.yaml || true
    $KUBECTL delete -f namespace.yaml || true
    
    print_info "OpenAlgo undeployed successfully!"
}

logs() {
    print_info "Streaming logs from OpenAlgo..."
    $KUBECTL logs -f statefulset/openalgo -n $NAMESPACE
}

shell() {
    print_info "Opening shell in OpenAlgo pod..."
    $KUBECTL exec -it openalgo-0 -n $NAMESPACE -- /bin/bash
}

# Main script
case "${1:-}" in
    deploy)
        check_prerequisites
        check_secrets
        deploy
        echo
        status
        ;;
    status)
        check_prerequisites
        status
        ;;
    undeploy)
        check_prerequisites
        undeploy
        ;;
    logs)
        check_prerequisites
        logs
        ;;
    shell)
        check_prerequisites
        shell
        ;;
    *)
        echo "OpenAlgo Kubernetes Deployment Script"
        echo
        echo "Usage: $0 {deploy|status|undeploy|logs|shell}"
        echo
        echo "Commands:"
        echo "  deploy    - Deploy OpenAlgo to Kubernetes"
        echo "  status    - Check deployment status"
        echo "  undeploy  - Remove OpenAlgo from Kubernetes (deletes data!)"
        echo "  logs      - Stream application logs"
        echo "  shell     - Open shell in OpenAlgo pod"
        echo
        exit 1
        ;;
esac
