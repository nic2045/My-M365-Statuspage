# Infrastructure & Configuration Guide

Complete guide to configuring and deploying M365 Statuspage in various environments.

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Docker Compose Deployment](#docker-compose-deployment)
3. [Kubernetes Deployment](#kubernetes-deployment)
4. [Terraform Deployment](#terraform-deployment)
5. [Configuration Management](#configuration-management)
6. [Secrets Management](#secrets-management)
7. [Monitoring & Observability](#monitoring--observability)
8. [Backup & Recovery](#backup--recovery)

---

## Environment Setup

### Local Development

```bash
# Clone repository
git clone https://github.com/nic2045/My-M365-Statuspage.git
cd My-M365-Statuspage

# Install dependencies
make install

# Copy environment template
cp .env.example .env

# Configure local development variables
cat > .env << EOF
DEBUG=true
DISABLE_AUTH=true
POLL_INTERVAL_MINUTES=10
MONITORED_SERVICES=Exchange Online,Microsoft Teams,OneDrive
EOF

# Start development server
make dev

# Access application
open http://localhost:8000
```

### Windows Development (Docker Desktop)

Windows uses Docker Desktop; no WSL setup is required. `make` is usually not
available on Windows, so run the Compose commands directly:

- macOS/Linux: `make docker`
- Windows (PowerShell / Git Bash): `npm run build:css; docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`

---

## Docker Compose Deployment

### Development Environment

```bash
# Start all services with development compose file
docker-compose -f docker-compose.dev.yml up -d

# View logs
docker-compose -f docker-compose.dev.yml logs -f statuspage

# Stop services
docker-compose -f docker-compose.dev.yml down
```

Configuration: `docker-compose.dev.yml`

Services:
- FastAPI application on port 8000
- SQLite database in volume

### Production Environment

```bash
# Create .env.production with secrets
cat > .env.production << EOF
DEBUG=false
DISABLE_AUTH=false
POLL_INTERVAL_MINUTES=10
MONITORED_SERVICES=Exchange Online,Microsoft Teams,OneDrive

# Entra ID (Azure AD) OAuth
AZURE_TENANT_ID=xxx-xxx-xxx
AZURE_CLIENT_ID=xxx-xxx-xxx
AZURE_CLIENT_SECRET=xxx-xxx-xxx

# Admin access
ADMIN_ROLE=Admin
ADMIN_EMAILS=admin@example.com

# Embed API (optional)
EMBED_API_KEY=your-secure-embed-key

# SMTP for notifications
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=noreply@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=noreply@example.com
EOF

# Build and start production environment
docker-compose -f infra/examples/docker-compose.production.yml up -d

# Check service health
curl http://localhost:8000/api/v1/health
```

Configuration: `infra/examples/docker-compose.production.yml`

Services:
- FastAPI application on port 8000
- PostgreSQL database (optional, for scaling)
- Redis cache (optional, for performance)
- Prometheus metrics scraper
- Volume persistence for data

### Environment Variables by Tier

| Variable | Development | Staging | Production |
|----------|-------------|---------|------------|
| DEBUG | true | false | false |
| DISABLE_AUTH | true | false | false |
| POLL_INTERVAL | 10 min | 10 min | 10 min |
| REPLICA_COUNT | 1 | 2 | 3+ |
| DATABASE | SQLite | PostgreSQL | PostgreSQL |
| CACHE | None | Redis | Redis |
| LOG_LEVEL | DEBUG | INFO | WARN |
| TLS | No | Yes | Yes |

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes 1.20+
- Helm 3.0+
- kubectl configured
- Image pushed to registry

### Installation

See `infra/helm/README.md` for detailed Helm documentation.

```bash
# Create namespace
kubectl create namespace statuspage

# Create secrets
kubectl create secret generic statuspage-secrets \
  --from-literal=azure-tenant-id=xxx \
  --from-literal=azure-client-id=xxx \
  --from-literal=azure-client-secret=xxx \
  -n statuspage

# Install Helm chart
helm install statuspage infra/helm/statuspage \
  -n statuspage \
  -f infra/helm/values-production.yaml

# Verify installation
kubectl get pods -n statuspage
kubectl get svc -n statuspage
```

### Production Deployment

Create `values-production.yaml`:

```yaml
replicaCount: 3

image:
  repository: your-registry.com/statuspage
  tag: "1.0.0"
  pullPolicy: IfNotPresent

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: status.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: statuspage-tls
      hosts:
        - status.example.com

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

persistence:
  enabled: true
  size: 10Gi
  storageClassName: fast-ssd

resources:
  requests:
    cpu: 500m
    memory: 256Mi
  limits:
    cpu: 1000m
    memory: 512Mi
```

Deploy:

```bash
helm install statuspage infra/helm/statuspage \
  -n statuspage \
  -f values-production.yaml
```

---

## Terraform Deployment

### AWS EKS Setup

See `infra/terraform/` directory.

```bash
# Navigate to terraform directory
cd infra/terraform

# Initialize Terraform
terraform init

# Create terraform.tfvars
cat > terraform.tfvars << EOF
aws_region             = "eu-central-1"
kubernetes_version     = "1.28"
node_desired_size      = 3
node_instance_types    = ["t3.medium"]
EOF

# Plan deployment
terraform plan

# Apply configuration
terraform apply
```

### Azure AKS Setup

Create `infra/terraform/azure.tf`:

```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "statuspage" {
  name     = "rg-statuspage"
  location = "West Europe"
}

resource "azurerm_kubernetes_cluster" "statuspage" {
  name                = "aks-statuspage"
  location            = azurerm_resource_group.statuspage.location
  resource_group_name = azurerm_resource_group.statuspage.name
  dns_prefix          = "statuspage"

  default_node_pool {
    name       = "default"
    node_count = 3
    vm_size    = "Standard_D2s_v3"
  }

  identity {
    type = "SystemAssigned"
  }
}
```

Deploy:

```bash
terraform init
terraform plan
terraform apply
```

---

## Configuration Management

### Environment-Specific Configurations

#### Development `.env`

```bash
DEBUG=true
DISABLE_AUTH=true
DATABASE_URL=sqlite:///data/statuspage.db
POLL_INTERVAL_MINUTES=10
MONITORED_SERVICES=Exchange Online,Microsoft Teams,OneDrive
```

#### Staging `.env`

```bash
DEBUG=false
DISABLE_AUTH=false
DATABASE_URL=postgresql://user:pass@db.staging:5432/statuspage
POLL_INTERVAL_MINUTES=10
MONITORED_SERVICES=Exchange Online,Microsoft Teams,OneDrive,SharePoint,Yammer

AZURE_TENANT_ID=staging-tenant-id
AZURE_CLIENT_ID=staging-client-id
AZURE_CLIENT_SECRET=staging-secret

ADMIN_ROLE=Admin
ADMIN_EMAILS=admin@example.com
```

#### Production `.env`

```bash
DEBUG=false
DISABLE_AUTH=false
DATABASE_URL=postgresql://user:pass@db-prod-rds.amazonaws.com/statuspage
POLL_INTERVAL_MINUTES=10
MONITORED_SERVICES=Exchange Online,Microsoft Teams,OneDrive,SharePoint,Yammer,Power Platform

AZURE_TENANT_ID=prod-tenant-id
AZURE_CLIENT_ID=prod-client-id
AZURE_CLIENT_SECRET=prod-secret

ADMIN_ROLE=StatusPageAdmin
ADMIN_EMAILS=admin@example.com,ops@example.com

EMBED_API_KEY=prod-embed-key
EMBED_ALLOWED_ORIGINS=*.example.com

SMTP_SERVER=ses.eu-central-1.amazonaws.com
SMTP_PORT=587
SMTP_USERNAME=prod-smtp-user
SMTP_PASSWORD=prod-smtp-pass
SMTP_FROM_EMAIL=noreply@status.example.com
```

### Configuration Profiles

For complex multi-environment setups, use configuration management:

```bash
# Use config directory structure
config/
├── common.env          # Shared settings
├── development.env     # Dev overrides
├── staging.env         # Staging overrides
└── production.env      # Prod overrides

# Load specific profile
export ENV=production
source config/common.env
source config/${ENV}.env
```

---

## Secrets Management

### Option 1: Environment Files (Development Only)

```bash
# NOT for production - insecure
cp .env.example .env
# Edit with secrets manually
```

### Option 2: Kubernetes Secrets

```bash
# Create from files
kubectl create secret generic statuspage-secrets \
  --from-file=azure-tenant-id=./secrets/tenant-id.txt \
  --from-file=azure-client-secret=./secrets/client-secret.txt \
  -n statuspage

# Reference in deployment:
env:
  - name: AZURE_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: statuspage-secrets
        key: azure-client-secret
```

### Option 3: External Secrets Operator (Recommended)

Install ESO:

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets-system --create-namespace
```

Create SecretStore (for Azure Key Vault):

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
      vaultUrl: "https://statuspage-kv.vault.azure.net"
```

Reference secrets:

```yaml
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

### Option 4: OpenBao/Vault

See `infra/openbao/` for Terraform configuration.

```bash
# Deploy OpenBao
cd infra/openbao
terraform init
terraform apply

# Authenticate application
export VAULT_ADDR=https://bao.example.com
vault login -method=kubernetes
```

---

## Monitoring & Observability

### Prometheus Metrics

Application exports metrics on `/api/v1/metrics`.

Configure Prometheus to scrape:

```yaml
scrape_configs:
  - job_name: 'statuspage'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/v1/metrics'
    scrape_interval: 30s
```

Key metrics:
- `statuspage_incidents_total` - Total incident count
- `statuspage_incidents_active` - Active incident count
- `statuspage_services_monitored` - Services being monitored
- `statuspage_poll_duration_seconds` - Graph API poll duration

### Logging

View logs:

```bash
# Docker Compose
docker-compose logs statuspage -f

# Kubernetes
kubectl logs -n statuspage deployment/statuspage -f

# Tail last 100 lines
kubectl logs -n statuspage deployment/statuspage --tail=100
```

Configure log aggregation (e.g., ELK Stack):

```yaml
# fluent-bit config
[OUTPUT]
    Name    es
    Match   *
    Host    elasticsearch.monitoring
    Port    9200
    Index   statuspage
```

### Alerting

Example Prometheus alerts (in `prometheus-rules.yaml`):

```yaml
groups:
  - name: statuspage
    interval: 30s
    rules:
      - alert: StatusPageDown
        expr: up{job="statuspage"} == 0
        for: 2m
        annotations:
          summary: "Statuspage down"

      - alert: HighIncidentCount
        expr: statuspage_incidents_active > 5
        for: 5m
        annotations:
          summary: "{{ $value }} active incidents"
```

---

## Backup & Recovery

### Database Backup

```bash
# SQLite backup
sqlite3 data/statuspage.db ".backup data/statuspage.backup.db"

# PostgreSQL backup
pg_dump -U statuspage -h db-host statuspage | gzip > statuspage.sql.gz

# Automated backup (cron)
0 2 * * * /usr/local/bin/backup-statuspage.sh
```

### Database Restore

```bash
# SQLite restore
sqlite3 data/statuspage.db ".restore data/statuspage.backup.db"

# PostgreSQL restore
gunzip < statuspage.sql.gz | psql -U statuspage -h db-host statuspage
```

### Docker Volume Backup

```bash
# Backup volume
docker run --rm -v statuspage_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/statuspage_data.tar.gz -C /data .

# Restore volume
docker run --rm -v statuspage_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/statuspage_data.tar.gz -C /data
```

### Disaster Recovery Plan

1. **RTO (Recovery Time Objective):** < 1 hour
2. **RPO (Recovery Point Objective):** < 1 hour
3. **Regular backup schedule:** Daily at 02:00 UTC
4. **Backup retention:** 30 days
5. **Test restore:** Weekly

---

## Troubleshooting

### Common Issues

**Application won't start**
```bash
# Check environment variables
env | grep AZURE_

# Check logs
docker-compose logs statuspage
```

**Database connection failed**
```bash
# Test database connectivity
psql -h db-host -U statuspage -d statuspage -c "SELECT 1"

# Check volume permissions
docker exec statuspage ls -la /app/data
```

**High memory usage**
```bash
# Check memory limits
kubectl describe pod -n statuspage <pod-name>

# Increase resource limits in values.yaml
resources:
  limits:
    memory: 512Mi
```

---

## Security Considerations

1. **Never commit secrets** - Use external secret management
2. **Use HTTPS/TLS** - Enable Ingress TLS certificates
3. **Implement RBAC** - Use Kubernetes RBAC policies
4. **Enable audit logging** - Log all administrative actions
5. **Regular updates** - Keep dependencies current
6. **Security scanning** - Use Trivy/Snyk for image scanning
7. **Network policies** - Restrict traffic between pods

See `SECURITY.md` for detailed security guidelines.

---

## Support & Documentation

- Helm Chart: `infra/helm/README.md`
- Terraform: `infra/terraform/README.md` (coming soon)
- OpenBao: `infra/openbao/README.md`
- Code documentation: `CLAUDE.md`
