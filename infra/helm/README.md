# M365 Statuspage Helm Chart

Kubernetes Helm Chart for deploying the M365 Statuspage application to Kubernetes clusters.

## Prerequisites

- Kubernetes 1.20+
- Helm 3.0+
- Docker image: `pyur-statuspage:latest` (built and pushed to registry)

## Installation

### 1. Basic Installation

```bash
# Add your Helm repo (if using a registry)
helm repo add statuspage https://your-registry.example.com
helm repo update

# Install with default values
helm install statuspage infra/helm/statuspage

# Or using namespace
helm install statuspage infra/helm/statuspage -n statuspage --create-namespace
```

### 2. Custom Configuration

Create a `values-prod.yaml` file with your production settings:

```yaml
replicaCount: 3

image:
  repository: ghcr.io/your-org/statuspage
  tag: "1.0.0"

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: status.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: status-tls
      hosts:
        - status.example.com

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70

persistence:
  enabled: true
  size: 5Gi
  storageClassName: fast-ssd

secrets:
  azureTenantId: "xxx-xxx-xxx"
  azureClientId: "xxx-xxx-xxx"
  azureClientSecret: "xxx-xxx-xxx"
  embedApiKey: "your-embed-key"
  monitoredServices: "Exchange Online,Microsoft Teams,OneDrive"

env:
  DEBUG: "false"
  POLL_INTERVAL_MINUTES: "10"
  DISABLE_AUTH: "false"
```

Install with custom values:

```bash
helm install statuspage infra/helm/statuspage -f values-prod.yaml
```

## Configuration

### Core Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `replicaCount` | 1 | Number of replicas |
| `image.repository` | pyur-statuspage | Image repository |
| `image.tag` | latest | Image tag |
| `service.type` | ClusterIP | Kubernetes Service type |
| `service.port` | 80 | Service port |

### Secrets (Required)

Secrets must be provided at deployment:

```bash
helm install statuspage infra/helm/statuspage \
  --set secrets.azureTenantId="xxx" \
  --set secrets.azureClientId="xxx" \
  --set secrets.azureClientSecret="xxx"
```

Or with `--set-file` for sensitive values in files:

```bash
helm install statuspage infra/helm/statuspage \
  --set-file secrets.azureTenantId=./azure-tenant-id.txt \
  --set-file secrets.azureClientSecret=./azure-secret.txt
```

### Persistence

SQLite database is stored in a PersistentVolume by default:

```yaml
persistence:
  enabled: true
  size: 1Gi
  storageClassName: standard
```

### Ingress

Enable HTTPS ingress with TLS:

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  hosts:
    - host: status.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: status-tls
      hosts:
        - status.example.com
```

### Auto-scaling

Enable HPA (Horizontal Pod Autoscaler):

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

## Deployment Examples

### Minikube (Development)

```bash
# Start Minikube
minikube start

# Build image locally
docker build -t pyur-statuspage:latest .

# Load into Minikube
minikube image load pyur-statuspage:latest

# Install with local image
helm install statuspage infra/helm/statuspage \
  --set image.pullPolicy=Never \
  --set image.tag=latest \
  --set secrets.azureTenantId="dev-tenant" \
  --set secrets.azureClientId="dev-client" \
  --set secrets.azureClientSecret="dev-secret"

# Port-forward to test
kubectl port-forward svc/statuspage 8000:80
```

### Docker Desktop Kubernetes

```bash
# Install chart
helm install statuspage infra/helm/statuspage \
  --namespace statuspage \
  --create-namespace \
  --values values-docker-desktop.yaml

# Port-forward
kubectl port-forward -n statuspage svc/statuspage 8000:80
```

### AWS EKS

```bash
# Create namespace and secrets
kubectl create namespace statuspage
kubectl create secret generic azure-creds \
  --from-file=tenant-id=./azure-tenant-id.txt \
  --from-file=client-id=./azure-client-id.txt \
  --from-file=client-secret=./azure-secret.txt \
  -n statuspage

# Install with AWS-specific settings
helm install statuspage infra/helm/statuspage \
  -n statuspage \
  -f values-aws-eks.yaml \
  --set image.repository=ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/statuspage

# Create LoadBalancer service
kubectl patch svc statuspage -n statuspage -p '{"spec": {"type": "LoadBalancer"}}'
```

### Azure AKS

```bash
# Create namespace
kubectl create namespace statuspage

# Install with Azure-specific settings
helm install statuspage infra/helm/statuspage \
  -n statuspage \
  -f values-azure-aks.yaml \
  --set persistence.storageClassName=managed-csi-premium

# Get LoadBalancer IP
kubectl get svc statuspage -n statuspage
```

## Secrets Management

### Option 1: Direct Secrets in Helm Values (Not Recommended)

```bash
helm install statuspage infra/helm/statuspage \
  --set secrets.azureClientSecret="actual-secret"
```

### Option 2: Using Kubernetes Secrets (Recommended)

Pre-create Kubernetes Secrets:

```bash
kubectl create secret generic statuspage-secrets \
  --from-literal=azure-tenant-id=xxx \
  --from-literal=azure-client-id=xxx \
  --from-literal=azure-client-secret=xxx \
  -n statuspage
```

Then use in Helm (modify deployment.yaml to reference existing secret).

### Option 3: Using External Secrets Operator

Install ESO:

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets-system --create-namespace
```

Create SecretStore and ExternalSecret (example for Azure Key Vault):

```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: azure-keyvault
  namespace: statuspage
spec:
  provider:
    azurekv:
      auth:
        workspaceIdentity: {}
      vaultUrl: "https://your-keyvault.vault.azure.net"
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: statuspage-secrets
  namespace: statuspage
spec:
  secretStoreRef:
    name: azure-keyvault
    kind: SecretStore
  target:
    name: statuspage-secrets
  data:
    - secretKey: azure-tenant-id
      remoteRef:
        key: azure-tenant-id
```

## Monitoring & Observability

### Prometheus Metrics

The chart includes annotations for Prometheus scraping:

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/api/v1/metrics"
```

Add ServiceMonitor (if using Prometheus Operator):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: statuspage
  namespace: statuspage
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: statuspage
  endpoints:
    - port: http
      path: /api/v1/metrics
      interval: 30s
```

### Logging

View logs:

```bash
kubectl logs -n statuspage deployment/statuspage
kubectl logs -n statuspage deployment/statuspage --tail=100 -f
```

## Upgrading

```bash
# Update chart repository
helm repo update

# Upgrade release
helm upgrade statuspage infra/helm/statuspage \
  -n statuspage \
  -f values-prod.yaml

# Rollback if needed
helm rollback statuspage 1
```

## Uninstall

```bash
helm uninstall statuspage -n statuspage
```

## Troubleshooting

### Pod won't start

```bash
# Check pod status
kubectl describe pod -n statuspage <pod-name>

# Check logs
kubectl logs -n statuspage <pod-name>

# Check events
kubectl get events -n statuspage
```

### Database permissions

```bash
# Verify PVC is bound
kubectl get pvc -n statuspage

# Check volume mount
kubectl exec -it -n statuspage <pod-name> -- ls -la /app/data
```

### Connectivity issues

```bash
# Test service DNS
kubectl run -it --rm debug --image=alpine --restart=Never -- \
  nslookup statuspage.statuspage.svc.cluster.local

# Port forward to test
kubectl port-forward -n statuspage svc/statuspage 8000:80
curl http://localhost:8000/api/v1/health
```

## Contributing

To modify the chart:

1. Update `values.yaml` for default values
2. Update templates in `templates/`
3. Test with: `helm lint infra/helm/statuspage`
4. Dry-run install: `helm install --dry-run statuspage infra/helm/statuspage`

## License

Same as parent project.
