# XML Output Format Reference

This document provides standard XML output formats for all agents. These can be added to system prompts in config to define the expected output structure. Since Pydantic `output_type` has been removed, agents now use prompt-based XML schemas which are hot-reloadable via config.

## Benefits of XML Output Format

- **Hot-reloadable**: Change config, get new format immediately - no redeploy
- **Customizable**: Add/remove fields per team via config override
- **Reliable**: LLMs follow XML formats consistently (better than JSON for complex structures)
- **Self-documenting**: Schema is visible in the prompt

---

## Planner Agent

```xml
Always output your findings in this format:
<response>
  <summary>Brief summary of findings (2-3 sentences)</summary>
  <root_cause>Identified root cause if found</root_cause>
  <confidence>0-100</confidence>
  <recommendations>
    <item>Recommended action 1</item>
    <item>Recommended action 2</item>
  </recommendations>
  <needs_followup>true|false</needs_followup>
</response>
```

---

## Investigation Agent

```xml
Always output your findings in this format:
<response>
  <summary>Investigation summary</summary>
  <root_cause>
    <description>Root cause description</description>
    <confidence>high|medium|low</confidence>
    <evidence>Supporting evidence</evidence>
  </root_cause>
  <timeline>
    <event>Timestamp - Event description</event>
    <event>Timestamp - Event description</event>
  </timeline>
  <affected_systems>
    <system>Service or system name</system>
  </affected_systems>
  <recommendations>
    <item>Recommended action</item>
  </recommendations>
  <requires_escalation>true|false</requires_escalation>
</response>
```

---

## K8s Agent

```xml
Always output your findings in this format:
<response>
  <summary>Summary of Kubernetes findings</summary>
  <pod_status>Current pod status (Running, CrashLoopBackOff, etc.)</pod_status>
  <issues_found>
    <issue>Issue description</issue>
  </issues_found>
  <recommendations>
    <item>Recommended action</item>
  </recommendations>
  <requires_manual_intervention>true|false</requires_manual_intervention>
  <resource_metrics>
    <cpu_usage>Current CPU usage</cpu_usage>
    <memory_usage>Current memory usage</memory_usage>
    <requests>Resource requests</requests>
    <limits>Resource limits</limits>
  </resource_metrics>
</response>
```

---

## AWS Agent

```xml
Always output your findings in this format:
<response>
  <summary>Summary of AWS findings</summary>
  <resource_status>Current resource status</resource_status>
  <issues_found>
    <issue>Issue description</issue>
  </issues_found>
  <recommendations>
    <item>Recommended action</item>
  </recommendations>
  <estimated_cost_impact>Cost impact if applicable</estimated_cost_impact>
</response>
```

---

## Metrics Agent

```xml
Always output your findings in this format:
<response>
  <summary>Summary of metric analysis</summary>
  <anomalies_found>
    <anomaly>
      <metric_name>Name of the metric</metric_name>
      <timestamp>When anomaly occurred</timestamp>
      <severity>critical|high|medium|low</severity>
      <description>Description of the anomaly</description>
    </anomaly>
  </anomalies_found>
  <baseline_established>true|false</baseline_established>
  <recommendations>
    <item>Recommended action</item>
  </recommendations>
  <requires_immediate_action>true|false</requires_immediate_action>
</response>
```

---

## Log Analysis Agent

```xml
Always output your findings in this format:
<response>
  <summary>Executive summary of log analysis findings</summary>
  <statistics>
    <total_logs_analyzed>Number</total_logs_analyzed>
    <error_count>Number</error_count>
    <error_rate_percent>Percentage</error_rate_percent>
    <time_range_analyzed>Time range</time_range_analyzed>
  </statistics>
  <error_patterns>
    <pattern>
      <signature>Error pattern signature</signature>
      <count>Number of occurrences</count>
      <percentage>Percentage of total errors</percentage>
      <first_seen>Timestamp</first_seen>
      <last_seen>Timestamp</last_seen>
      <sample_message>Example error message</sample_message>
    </pattern>
  </error_patterns>
  <timeline>
    <event>
      <timestamp>When it happened</timestamp>
      <event_type>error_spike|deployment|restart|pattern_start</event_type>
      <description>What happened</description>
    </event>
  </timeline>
  <root_causes>
    <hypothesis>
      <description>Root cause hypothesis</description>
      <confidence>0-100</confidence>
      <evidence>Supporting evidence</evidence>
    </hypothesis>
  </root_causes>
  <recommendations>
    <item>Recommended action</item>
  </recommendations>
</response>
```

---

## GitHub Agent

```xml
Always output your findings in this format:
<response>
  <summary>Summary of GitHub analysis findings</summary>
  <recent_changes>
    <change>
      <commit_sha>Short SHA</commit_sha>
      <author>Author name</author>
      <timestamp>When committed</timestamp>
      <files_changed>file1.py, file2.ts</files_changed>
      <message>Commit message</message>
    </change>
  </recent_changes>
  <related_prs>
    <pr>PR #123: Title</pr>
  </related_prs>
  <related_issues>
    <issue>Issue #456: Title</issue>
  </related_issues>
  <code_findings>
    <finding>Relevant code pattern or issue found</finding>
  </code_findings>
  <recommendations>
    <item>Recommended action</item>
  </recommendations>
</response>
```

---

## Coding Agent

```xml
Always output your findings in this format:
<response>
  <summary>Analysis summary</summary>
  <issues_found>
    <issue>Issue description</issue>
  </issues_found>
  <code_changes>
    <change>
      <file_path>Path to file</file_path>
      <change_type>fix|refactor|optimize|add</change_type>
      <description>What change is needed</description>
      <code_snippet>Relevant code</code_snippet>
    </change>
  </code_changes>
  <testing_recommendations>
    <item>Testing suggestion</item>
  </testing_recommendations>
  <explanation>Detailed explanation of the analysis and changes</explanation>
</response>
```

---

## Writeup Agent

```xml
Always output your findings in this format:
<response>
  <title>Incident title</title>
  <severity>SEV1|SEV2|SEV3|SEV4</severity>
  <duration>How long the incident lasted</duration>
  <summary>Executive summary (2-3 sentences)</summary>
  <impact>Impact description - users, business, technical</impact>
  <timeline>
    <event>Timestamp UTC - What happened</event>
  </timeline>
  <root_cause>Root cause analysis</root_cause>
  <contributing_factors>
    <factor>Contributing factor</factor>
  </contributing_factors>
  <detection>How was the incident detected?</detection>
  <resolution>How was the incident resolved?</resolution>
  <action_items>
    <item>
      <description>What needs to be done</description>
      <owner>Who owns it</owner>
      <priority>P1|P2|P3</priority>
      <due_date>When it's due</due_date>
    </item>
  </action_items>
  <lessons_learned>
    <item>What we learned</item>
  </lessons_learned>
  <what_went_well>
    <item>What worked well during response</item>
  </what_went_well>
</response>
```

---

## Customization Examples

### Adding Custom Fields

To add custom fields like `follow_up_questions` and `key_links`, simply add them to your prompt:

```xml
Always output your findings in this format:
<response>
  <summary>...</summary>
  <recommendations>
    <item>...</item>
  </recommendations>
  <!-- Custom fields added by team -->
  <follow_up_questions>
    <question>Question to investigate next</question>
  </follow_up_questions>
  <key_links>
    <link>URL to relevant resource</link>
  </key_links>
</response>
```

### Team Config Override Example

```yaml
agents:
  investigation:
    prompt:
      system: |
        You are an expert SRE investigator...

        Always output your findings in this format:
        <response>
          <summary>...</summary>
          <root_cause>...</root_cause>
          <recommendations>
            <item>...</item>
          </recommendations>
          <!-- Team-specific additions -->
          <follow_up_questions>
            <question>...</question>
          </follow_up_questions>
          <key_links>
            <link>...</link>
          </key_links>
          <pagerduty_incident_id>If applicable</pagerduty_incident_id>
        </response>
```

---

## Migration Notes

1. **Pydantic models remain in codebase** - They serve as documentation and can be used for other purposes
2. **output_type= removed from Agent()** - Agents now return free-form text with XML
3. **Prompt-based schema** - XML format is defined in system prompt
4. **Hot-reloadable** - Change config, effect is immediate

---

## Template Update Status

| Template | File | Status |
|----------|------|--------|
| 01 - Slack Incident Triage | `01_slack_incident_triage.json` | ✅ Updated (v2.1.0) |
| 02 - Git CI Auto-Fix | `02_git_ci_auto_fix.json` | ⏳ Pending |
| 03 - AWS Cost Reduction | `03_aws_cost_reduction.json` | ⏳ Pending |
| 04 - Coding Assistant | `04_coding_assistant.json` | ⏳ Pending |
| 05 - Data Migration | `05_data_migration.json` | ⏳ Pending |
| 06 - News Comedian | `06_news_comedian.json` | ⏳ Pending |
| 07 - Alert Fatigue | `07_alert_fatigue.json` | ⏳ Pending |
| 08 - DR Validator | `08_dr_validator.json` | ⏳ Pending |
| 09 - Incident Postmortem | `09_incident_postmortem.json` | ⏳ Pending |
| 10 - Universal Telemetry | `10_universal_telemetry.json` | ⏳ Pending |

---

## How to Update Remaining Templates

For each template, find the `"prompt": { "system": "..." }` section for each agent and append the appropriate XML output format from this document.

Example edit pattern:
```json
{
  "prompt": {
    "system": "You are an expert...\n\n## OUTPUT FORMAT\n\nAlways structure your response in this XML format:\n<response>\n  <summary>...</summary>\n  ...\n</response>"
  }
}
```

---

## Updating Team Config in RDS

Team configs are stored in PostgreSQL `node_configs` table. To update:

### Option 1: Via Config Service API

```bash
# Get current config
curl -H "Authorization: Bearer $TEAM_TOKEN" \
  https://config-service/api/v1/me/effective

# Update team overrides
curl -X PATCH \
  -H "Authorization: Bearer $TEAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agents": {
      "investigation": {
        "prompt": {
          "system": "Your custom prompt with XML format..."
        }
      }
    }
  }' \
  https://config-service/api/v1/me/overrides
```

### Option 2: Via Web UI

1. Go to `/team/config`
2. Navigate to Agents section
3. Edit the agent's system prompt
4. Add XML format section
5. Save changes

### Option 3: Direct Database Update (Admin only)

```sql
UPDATE node_configs
SET config_json = jsonb_set(
  config_json,
  '{agents,investigation,prompt,system}',
  '"Your custom prompt with XML format..."'
)
WHERE org_id = 'your-org' AND node_id = 'team-sre';
```

---

Last Updated: 2026-01-27
