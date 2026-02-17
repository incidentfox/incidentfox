---
name: azure-infrastructure
description: Azure cloud infrastructure inspection. Use when investigating Azure VMs, AKS clusters, Log Analytics (KQL), Monitor metrics/alerts, Cost Management, or NSG rules.
allowed-tools: Bash(python *)
---

# Azure Infrastructure

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `AZURE_CLIENT_SECRET` or `AZURE_TENANT_ID` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `AZURE_SUBSCRIPTION_ID` - Azure subscription ID
- `AZURE_RESOURCE_GROUP` - Default resource group

---

## MANDATORY: Query-First Investigation

**Start with Log Analytics or Monitor metrics, then drill into resources.**

```
LOG ANALYTICS / METRICS → IDENTIFY RESOURCE → DESCRIBE RESOURCE → CHECK ALERTS
```

## Available Scripts

All scripts are in `.claude/skills/infrastructure-azure/scripts/`

### query_log_analytics.py - KQL Log Queries (START HERE for log investigation)
```bash
python .claude/skills/infrastructure-azure/scripts/query_log_analytics.py --workspace-id WORKSPACE_ID --query "AzureDiagnostics | where Level == 'Error' | limit 50"
python .claude/skills/infrastructure-azure/scripts/query_log_analytics.py --workspace-id WORKSPACE_ID --query "Heartbeat | summarize count() by Computer" --timespan PT1H
```

### query_resource_graph.py - Cross-Subscription Resource Queries
```bash
python .claude/skills/infrastructure-azure/scripts/query_resource_graph.py --query "Resources | where type == 'microsoft.compute/virtualmachines' | project name, location"
```

### get_monitor_metrics.py - Azure Monitor Metrics
```bash
python .claude/skills/infrastructure-azure/scripts/get_monitor_metrics.py --resource-id RESOURCE_ID --metrics "Percentage CPU,Network In" --interval PT5M
```

### list_monitor_alerts.py - Alert Rules
```bash
python .claude/skills/infrastructure-azure/scripts/list_monitor_alerts.py [--resource-group RG]
```

### list_vms.py / describe_vm.py - Virtual Machines
```bash
python .claude/skills/infrastructure-azure/scripts/list_vms.py [--resource-group RG]
python .claude/skills/infrastructure-azure/scripts/describe_vm.py --resource-group RG --vm-name VM
```

### list_aks_clusters.py / describe_aks_cluster.py - AKS Clusters
```bash
python .claude/skills/infrastructure-azure/scripts/list_aks_clusters.py [--resource-group RG]
python .claude/skills/infrastructure-azure/scripts/describe_aks_cluster.py --resource-group RG --cluster-name CLUSTER
```

### query_costs.py - Cost Management
```bash
python .claude/skills/infrastructure-azure/scripts/query_costs.py --start 2026-01-01 --end 2026-02-01 [--granularity Monthly] [--group-by ResourceGroup,ServiceName]
```

### get_nsg_rules.py - Network Security Group Rules
```bash
python .claude/skills/infrastructure-azure/scripts/get_nsg_rules.py --resource-group RG --nsg-name NSG
```

---

## KQL Query Reference

```kql
// Errors in last hour
AzureDiagnostics | where Level == "Error" | where TimeGenerated > ago(1h) | limit 50

// CPU usage
Perf | where CounterName == "% Processor Time" | summarize avg(CounterValue) by bin(TimeGenerated, 5m), Computer

// Heartbeat (availability)
Heartbeat | summarize count() by Computer, bin(TimeGenerated, 1h)

// Resource Graph - find VMs
Resources | where type == "microsoft.compute/virtualmachines" | project name, location, properties.hardwareProfile.vmSize
```

---

## Investigation Workflow

### VM Performance Issue
```
1. get_monitor_metrics.py --resource-id <vm-id> --metrics "Percentage CPU,Network In"
2. query_log_analytics.py --query "Perf | where Computer == '<vm>' | where CounterName == '% Processor Time'"
3. describe_vm.py --resource-group <rg> --vm-name <vm>
```

### Cost Spike
```
1. query_costs.py --start <start> --end <end> --group-by ResourceGroup,ServiceName
2. query_resource_graph.py --query "Resources | summarize count() by type, location"
```
