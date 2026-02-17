---
name: gcp-infrastructure
description: Google Cloud Platform infrastructure inspection. Use when investigating GCP Compute instances, GKE clusters, Cloud Functions, Cloud SQL, or project metadata.
allowed-tools: Bash(python *)
---

# GCP Infrastructure

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `GCP_SERVICE_ACCOUNT_KEY` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `GCP_PROJECT_ID` - GCP project ID

---

## Available Scripts

All scripts are in `.claude/skills/infrastructure-gcp/scripts/`

### list_compute_instances.py - List Compute Engine VMs
```bash
python .claude/skills/infrastructure-gcp/scripts/list_compute_instances.py [--zone us-central1-a]
```

### list_gke_clusters.py - List GKE Clusters
```bash
python .claude/skills/infrastructure-gcp/scripts/list_gke_clusters.py
```

### list_cloud_functions.py - List Cloud Functions
```bash
python .claude/skills/infrastructure-gcp/scripts/list_cloud_functions.py
```

### list_cloud_sql.py - List Cloud SQL Instances
```bash
python .claude/skills/infrastructure-gcp/scripts/list_cloud_sql.py
```

### get_project_metadata.py - Project Info
```bash
python .claude/skills/infrastructure-gcp/scripts/get_project_metadata.py
```

---

## Investigation Workflow

### GKE Cluster Issue
```
1. list_gke_clusters.py
2. Use infrastructure-kubernetes skill for pod-level debugging
```

### Compute Instance Issue
```
1. list_compute_instances.py --zone <zone>
2. Check instance status and IPs
```
