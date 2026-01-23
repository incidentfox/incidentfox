---
name: sync-catalog
description: Review and approve infrastructure discoveries to add to .incidentfox.yaml. Shows services, dependencies, and patterns learned during investigations.
---

# Sync Discoveries to Service Catalog

You are helping the user review and approve discoveries made during incident investigations, then update their `.incidentfox.yaml` service catalog.

## Process

### Step 1: Get Pending Discoveries

```
get_pending_discoveries()
```

This returns:
- **Services**: New services discovered during investigations
- **Dependencies**: Service relationships inferred from logs/traces
- **Known Issues**: Error patterns that could be added to the catalog

If nothing is pending, inform the user and exit:
> "No pending discoveries. Discoveries are recorded during investigations when I find new services or patterns."

### Step 2: Present Discoveries for Review

Format each category clearly:

```
## Pending Discoveries

### Services (3 pending)

1. **checkout-api**
   - Namespace: production
   - Discovered: 2024-01-20 via list_pods
   - [ ] Add to catalog?

2. **inventory-worker**
   - Namespace: production
   - Discovered: 2024-01-21 via describe_deployment
   - [ ] Add to catalog?

### Dependencies (2 pending)

1. **payment-api → stripe-api**
   - Evidence: "Connection timeout to stripe-api in error logs"
   - Confidence: 0.8
   - [ ] Add to catalog?

2. **checkout-api → payment-api**
   - Evidence: "Traced request flow during investigation"
   - Confidence: 0.9
   - [ ] Add to catalog?

### Known Issues (1 pending)

1. **Pattern:** `OOMKilled.*payment`
   - Cause: Memory leak in image processing
   - Solution: Increase memory limit, investigate leak
   - Seen: 3 times
   - [ ] Add to catalog?

---

Which discoveries would you like to add to .incidentfox.yaml?
(Enter numbers like "1,2,3" or "all" or "none")
```

### Step 3: User Selection

Wait for user input on which discoveries to sync.

Options:
- "all" - Add everything
- "none" - Skip all
- "1,2,3" - Add specific items by number
- "services only" - Add only services
- Custom selection

### Step 4: Update .incidentfox.yaml

1. **Read existing file** (if it exists)
2. **Merge discoveries** into appropriate sections:
   - Services go under `services:`
   - Dependencies get added to the relevant service's `dependencies:` array
   - Known issues go under `known_issues:`
3. **Show diff** of what will change
4. **Ask for confirmation** before writing
5. **Write the file**
6. **Mark synced** using `mark_discoveries_synced()`

### Step 5: Confirm Completion

```
Updated .incidentfox.yaml:
- Added 2 new services
- Added 3 dependencies
- Added 1 known issue

These discoveries are now marked as synced and won't appear again.
```

## Example YAML Merge

**Before:**
```yaml
services:
  payment-api:
    namespace: production
    dependencies: [postgres]
```

**After adding discoveries:**
```yaml
services:
  payment-api:
    namespace: production
    dependencies: [postgres, stripe-api]  # Added stripe-api

  checkout-api:  # New service
    namespace: production
    deployments: [checkout-api]
    dependencies: [payment-api]

known_issues:
  - pattern: "OOMKilled.*payment"
    cause: "Memory leak in image processing"
    solution: "Increase memory limit, investigate leak"
    services: [payment-api]
```

## Important Notes

- **Always show diff before writing** - User must see and approve changes
- **Preserve existing content** - Don't remove anything from the YAML
- **Handle missing file** - If `.incidentfox.yaml` doesn't exist, suggest running `/init-catalog` first
- **Mark synced after write** - Call `mark_discoveries_synced()` with the IDs of items that were added
- **Respect user choices** - Only sync what the user explicitly approves
