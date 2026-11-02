# OpenAlgo Kubernetes Deployment

This directory contains Kubernetes manifests for deploying OpenAlgo algorithmic trading platform to a Kubernetes cluster.

## Architecture

OpenAlgo is deployed as a StatefulSet with persistent storage for:
- **Database**: SQLite database files (`/app/db`)
- **Logs**: Application and strategy logs (`/app/log`)
- **Strategies**: User Python trading strategies (`/app/strategies`)
- **Keys**: API keys and certificates (`/app/keys`)
- **Temp**: Temporary files for scipy/numba (`/app/tmp`)

The application exposes two ports:
- **5000**: Flask HTTP API
- **8765**: WebSocket for real-time updates

## Prerequisites

- Kubernetes cluster (v1.19+)
- kubectl configured to access your cluster
- Ingress controller installed (nginx, Traefik, etc.)
- StorageClass available for PersistentVolumes
- Docker image: `openalgo:latest` available in your cluster

## Quick Start

### 1. Build the Docker Image

```bash
# From the project root
docker build -t openalgo:latest .

# If using a private registry, tag and push:
docker tag openalgo:latest your-registry.com/openalgo:latest
docker push your-registry.com/openalgo:latest
```

### 2. Configure Secrets

Copy the secrets template and fill in your actual values:

```bash
cp kubernetes/secrets-template.yaml kubernetes/secrets.yaml

# Edit secrets.yaml with your actual configuration
# IMPORTANT: Add secrets.yaml to .gitignore!
nano kubernetes/secrets.yaml
```

Update the `.env` section with your broker API keys and other sensitive configuration.

### 3. Update Configuration

Edit `kubernetes/ingress.yaml` and replace `openalgo.yourdomain.com` with your actual domain.

Optionally, adjust storage sizes in `kubernetes/pvcs.yaml` based on your needs:
- Database: 5Gi (default)
- Logs: 2Gi (default)
- Strategies: 1Gi (default)
- Keys: 100Mi (default)
- Temp: 1Gi (default)

### 4. Deploy to Kubernetes

```bash
# Create namespace
kubectl apply -f kubernetes/namespace.yaml

# Create PersistentVolumeClaims
kubectl apply -f kubernetes/pvcs.yaml

# Create ConfigMap
kubectl apply -f kubernetes/configmap.yaml

# Create Secret (using your filled-in secrets.yaml)
kubectl apply -f kubernetes/secrets.yaml

# Deploy application
kubectl apply -f kubernetes/statefulset.yaml

# Create Service
kubectl apply -f kubernetes/service.yaml

# Create Ingress (for external access)
kubectl apply -f kubernetes/ingress.yaml
```

Or deploy everything at once:

```bash
kubectl apply  -k kubernetes/
```

### 5. Verify Deployment

```bash
# Check pods
kubectl get pods -n openalgo

# Check services
kubectl get svc -n openalgo

# Check ingress
kubectl get ingress -n openalgo

# View logs
kubectl logs -f statefulset/openalgo -n openalgo

# Check pod health
kubectl describe pod -n openalgo
```

### 6. Access the Application

Once deployed, access OpenAlgo via:
- **HTTP**: `http://openalgo.yourdomain.com` (or your configured domain)
- **HTTPS**: `https://openalgo.yourdomain.com` (if TLS is configured)

For local testing without a domain:

```bash
# Port forward
kubectl port-forward -n openalgo svc/openalgo 5000:5000

# Access at http://localhost:5000
```

## Configuration

### Environment Variables

Edit `kubernetes/configmap.yaml` for non-sensitive configuration:
- `FLASK_ENV`: Flask environment (production/development)
- `FLASK_DEBUG`: Enable Flask debug mode (0 or 1)
- `TZ`: Timezone (default: Asia/Kolkata)

### Secrets

All sensitive configuration goes in `kubernetes/secrets.yaml`:
- API keys and secrets
- Database credentials (if using external DB)
- Flask SECRET_KEY
- Any other sensitive values from your `.env` file

### Resource Limits

Adjust CPU and memory in `kubernetes/statefulset.yaml`:

```yaml
resources:
  requests:
    memory: "1Gi"   # Minimum required
    cpu: "500m"
  limits:
    memory: "4Gi"   # Maximum allowed
    cpu: "2000m"
```

### Storage Class

The manifests use `local-path` as the default StorageClass. Change this in `kubernetes/pvcs.yaml` if your cluster uses a different storage class:

```bash
# List available storage classes
kubectl get storageclass

# Common options:
# - local-path (K3s default)
# - standard (many cloud providers)
# - gp2, gp3 (AWS EBS)
# - pd-standard, pd-ssd (Google Cloud)
```

## Ingress Configuration

### Nginx Ingress Controller

The default configuration uses nginx. Key annotations:

```yaml
nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
nginx.ingress.kubernetes.io/websocket-services: "openalgo"
```

### Traefik Ingress Controller

For Traefik, update `kubernetes/ingress.yaml`:

```yaml
spec:
  ingressClassName: traefik
```

And use Traefik annotations:

```yaml
annotations:
  traefik.ingress.kubernetes.io/router.entrypoints: websecure
  traefik.ingress.kubernetes.io/router.tls: "true"
```

### TLS/HTTPS Setup

For automatic TLS with cert-manager:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
  - hosts:
    - openalgo.yourdomain.com
    secretName: openalgo-tls
```

## Scaling Considerations

**Important**: OpenAlgo uses SQLite as its database, which is file-based and does not support concurrent writes from multiple instances. Therefore:

- **Do not scale replicas > 1** with the current StatefulSet configuration
- For high availability, consider migrating to PostgreSQL or MySQL
- The StatefulSet ensures the single pod maintains a stable identity and persistent storage

If you need to scale horizontally:
1. Migrate from SQLite to PostgreSQL/MySQL
2. Update the Deployment to use an external database
3. Change from StatefulSet to Deployment
4. Increase replicas as needed

## Backup and Recovery

### Manual Backup

```bash
# Backup database
kubectl cp openalgo/openalgo-0:/app/db ./backup/db

# Backup strategies
kubectl cp openalgo/openalgo-0:/app/strategies ./backup/strategies

# Backup keys
kubectl cp openalgo/openalgo-0:/app/keys ./backup/keys
```

### Automated Backup

Consider using [Velero](https://velero.io/) for automated Kubernetes backup:

```bash
# Install Velero
velero install --provider <your-provider>

# Create backup schedule
velero schedule create openalgo-daily \
  --schedule="0 2 * * *" \
  --include-namespaces openalgo
```

### Restore from Backup

```bash
# Restore files to pod
kubectl cp ./backup/db openalgo/openalgo-0:/app/db
kubectl cp ./backup/strategies openalgo/openalgo-0:/app/strategies
kubectl cp ./backup/keys openalgo/openalgo-0:/app/keys

# Restart pod to apply changes
kubectl delete pod openalgo-0 -n openalgo
```

## Monitoring

### Check Pod Status

```bash
# Pod status
kubectl get pods -n openalgo -w

# Detailed pod information
kubectl describe pod openalgo-0 -n openalgo

# Pod events
kubectl get events -n openalgo --sort-by='.lastTimestamp'
```

### View Logs

```bash
# Current logs
kubectl logs -f openalgo-0 -n openalgo

# Previous logs (if pod restarted)
kubectl logs openalgo-0 -n openalgo --previous

# Logs from specific time
kubectl logs openalgo-0 -n openalgo --since=1h
```

### Health Checks

The application includes health checks at `/auth/check-setup`:

```bash
# Port forward
kubectl port-forward -n openalgo svc/openalgo 5000:5000

# Test health endpoint
curl http://localhost:5000/auth/check-setup
```

### Prometheus Integration (Optional)

If using Prometheus, create a ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: openalgo
  namespace: openalgo
spec:
  selector:
    matchLabels:
      app: openalgo
  endpoints:
  - port: http
    path: /metrics  # If metrics endpoint exists
    interval: 30s
```

## Troubleshooting

### Pod Fails to Start

```bash
# Check pod status
kubectl get pods -n openalgo

# View pod details
kubectl describe pod openalgo-0 -n openalgo

# Check logs
kubectl logs openalgo-0 -n openalgo
```

Common issues:
- **ImagePullBackOff**: Image not available. Check image name and pull secrets.
- **CrashLoopBackOff**: Application crashing. Check logs for errors.
- **Pending**: PVC not bound. Check PersistentVolumeClaims and StorageClass.

### PVC Not Binding

```bash
# Check PVC status
kubectl get pvc -n openalgo

# Describe PVC for details
kubectl describe pvc openalgo-db -n openalgo

# Check available storage classes
kubectl get storageclass
```

Fix: Update `storageClassName` in `pvcs.yaml` to match your cluster's storage class.

### Ingress Not Working

```bash
# Check ingress status
kubectl get ingress -n openalgo

# Describe ingress
kubectl describe ingress openalgo -n openalgo

# Check ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

Fix: Ensure:
1. Ingress controller is installed
2. Domain DNS points to your cluster
3. IngressClass matches your controller

### WebSocket Connection Issues

If WebSocket connections fail:

1. Verify ingress annotations for WebSocket support:
```yaml
nginx.ingress.kubernetes.io/websocket-services: "openalgo"
nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
```

2. Check service has sessionAffinity:
```yaml
sessionAffinity: ClientIP
```

3. Test WebSocket directly:
```bash
kubectl port-forward -n openalgo svc/openalgo 8765:8765
# Test WebSocket on localhost:8765
```

### Database Permission Issues

If seeing permission errors:

```bash
# Check PVC permissions
kubectl exec -it openalgo-0 -n openalgo -- ls -la /app/db

# Fix permissions if needed
kubectl exec -it openalgo-0 -n openalgo -- chown -R 1000:1000 /app/db
```

### Memory Issues

If pods are OOMKilled:

1. Increase memory limits in `statefulset.yaml`:
```yaml
resources:
  limits:
    memory: "8Gi"  # Increase from 4Gi
```

2. Check shared memory usage (2Gi emptyDir):
```bash
kubectl exec -it openalgo-0 -n openalgo -- df -h /dev/shm
```

## Upgrading

### Update Application

```bash
# Build new image
docker build -t openalgo:v2.0.0 .
docker tag openalgo:v2.0.0 your-registry.com/openalgo:v2.0.0
docker push your-registry.com/openalgo:v2.0.0

# Update StatefulSet image
kubectl set image statefulset/openalgo openalgo=your-registry.com/openalgo:v2.0.0 -n openalgo

# Or edit statefulset directly
kubectl edit statefulset openalgo -n openalgo

# Monitor rollout
kubectl rollout status statefulset/openalgo -n openalgo
```

### Rollback

```bash
# View revision history
kubectl rollout history statefulset/openalgo -n openalgo

# Rollback to previous version
kubectl rollout undo statefulset/openalgo -n openalgo

# Rollback to specific revision
kubectl rollout undo statefulset/openalgo -n openalgo --to-revision=2
```

## Security Best Practices

1. **Don't commit secrets**: Add `kubernetes/secrets.yaml` to `.gitignore`
2. **Use external secret management**: Consider using sealed-secrets, Vault, or cloud provider secret managers
3. **Enable TLS**: Always use HTTPS in production
4. **Network policies**: Restrict traffic between namespaces
5. **RBAC**: Create service accounts with minimal permissions
6. **Security scanning**: Scan images with Trivy or similar tools
7. **Keep updated**: Regularly update the application and base images

### Example NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: openalgo-netpol
  namespace: openalgo
spec:
  podSelector:
    matchLabels:
      app: openalgo
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx  # Only allow ingress controller
    ports:
    - protocol: TCP
      port: 5000
    - protocol: TCP
      port: 8765
```

## Uninstalling

```bash
# Delete all resources
kubectl delete -f kubernetes/

# Or delete namespace (removes everything)
kubectl delete namespace openalgo

# Warning: This will delete all data!
# Backup first if needed.
```

## Production Checklist

Before deploying to production:

- [ ] Backup strategy in place
- [ ] TLS/HTTPS configured
- [ ] Secrets properly secured (not in git)
- [ ] Resource limits tested and tuned
- [ ] Monitoring and alerting configured
- [ ] Health checks validated
- [ ] Ingress and DNS configured
- [ ] Storage class appropriate for production
- [ ] Network policies configured (if required)
- [ ] Documentation updated with environment-specific details

## Support

For issues, questions, or contributions:
- GitHub Issues: https://github.com/marketcalls/openalgo/issues
- Documentation: https://docs.openalgo.in
- Community: [Add community links]

## License

Same as OpenAlgo project license.



## ⚠️ Important: Configure Secrets First

The `secrets-template.yaml` is intentionally **NOT** included in `kustomization.yaml` to prevent accidental deployment with placeholder credentials.

**Before deploying, you MUST:**

1. Copy the template:
```bash
   cp kubernetes/secrets-template.yaml kubernetes/secrets.yaml
```

2. Edit `secrets.yaml` with your actual broker credentials and API keys:
```bash
   nano kubernetes/secrets.yaml  # or use your preferred editor
```

3. Ensure `secrets.yaml` is in `.gitignore`:
```bash
   echo "kubernetes/secrets.yaml" >> .gitignore
```

4. **Only then** proceed with deployment:
```bash
   kubectl apply -k kubernetes/
```

**Why this matters:** Deploying with placeholder secrets expose your deployment to security risks. The deployment will fail without proper secrets configured - this is by design.
### NetworkPolicy Support

**⚠️ Important for K3s users:**

K3s with default Flannel CNI does **not** support NetworkPolicy enforcement. The policy will be created but not enforced. 

If you need NetworkPolicy enforcement, you must:
- Use K3s with Calico: `curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--flannel-backend=none --disable-network-policy" sh -`
- Then install Calico or Cilium

For testing/homelab use, NetworkPolicy enforcement is optional. For production, it's highly recommended.