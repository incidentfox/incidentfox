# Golden Templates

This directory contains **read-only snapshots** of the fully assembled prompts for each template.

## Purpose

When a template is used, the actual prompt sent to the model is assembled from:
1. **Base prompt** from application code (`agent/src/ai_agent/prompts/`)
2. **Template overrides** from template JSON (`config_service/templates/`)
3. **Dynamic sections** (capabilities, delegation guidance, error handling, etc.)

These golden files show you **exactly what the model receives** - no assembly required.

## Directory Structure

```
golden_templates/
├── 01_slack_incident_triage/
│   ├── planner.md
│   ├── investigation.md
│   ├── github.md
│   ├── k8s.md
│   ├── aws.md
│   ├── metrics.md
│   ├── log_analysis.md
│   ├── coding.md
│   └── writeup.md
├── 02_git_ci_auto_fix/
│   └── ...
└── ... (10 templates total)
```

## Regenerating

To regenerate golden files after changing prompts:

```bash
cd /path/to/riyadh
python config_service/scripts/generate_golden_prompts.py
```

Or regenerate a specific template:

```bash
python config_service/scripts/generate_golden_prompts.py --template 01_slack_incident_triage
```

## CI Integration

Golden files are checked in CI. If you change prompts in:
- `agent/src/ai_agent/prompts/*.py`
- `config_service/templates/*.json`

You must regenerate and commit the updated golden files, or CI will fail.

## Usage

### Reviewing Prompts

To see exactly what the planner agent receives in the Slack Incident Triage template:

```bash
cat config_service/golden_templates/01_slack_incident_triage/planner.md
```

### Comparing Templates

To compare how the planner differs between templates:

```bash
diff golden_templates/01_slack_incident_triage/planner.md \
     golden_templates/07_alert_fatigue/planner.md
```

### PR Reviews

When reviewing prompt changes, check the diff in golden files to see the actual impact.

## Note on Runtime Context

These golden files show the **system prompt** only. At runtime, additional context is injected into the **user message**:

- Current timestamp
- Organization/team IDs
- Environment (prod/staging)
- Incident ID (if applicable)
- Team-specific service info, dependencies, etc.

This runtime context is NOT included in golden files as it varies per request.
