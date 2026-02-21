#!/usr/bin/env python3
"""Get the known database schema for incident enrichment tables."""

import json


def main():
    schema = {
        "database": "INCIDENT_ENRICHMENT_DB",
        "schema": "INCIDENT_ENRICHMENT_DEMO",
        "tables": {
            "fact_incident": {
                "description": "Main incident table with all incidents",
                "columns": [
                    "INCIDENT_ID (string, PK)",
                    "CREATED_AT (timestamp)",
                    "STARTED_AT (timestamp)",
                    "MITIGATED_AT (timestamp)",
                    "RESOLVED_AT (timestamp)",
                    "STATUS (string: resolved, open, investigating)",
                    "SEV (string: SEV-1, SEV-2, SEV-3, SEV-4)",
                    "PRIMARY_SERVICE_ID (string, FK)",
                    "ENV (string: prod, staging)",
                    "REGION (string)",
                    "TITLE (string)",
                    "SUMMARY (string)",
                    "ROOT_CAUSE_TYPE (string: deployment, external_dependency, etc)",
                    "DEPLOYMENT_ID (string, FK)",
                    "CONFIDENCE (float)",
                ],
            },
            "fact_incident_customer_impact": {
                "description": "Customer impact per incident",
                "columns": [
                    "IMPACT_ID (string, PK)",
                    "INCIDENT_ID (string, FK)",
                    "CUSTOMER_ID (string, FK)",
                    "IMPACT_TYPE (string)",
                    "IMPACTED_REQUESTS (int)",
                    "ERROR_RATE (float)",
                    "LATENCY_P95_MS (int)",
                    "ESTIMATED_ARR_AT_RISK_USD (float)",
                    "RECORDED_AT (timestamp)",
                ],
            },
            "dim_customer": {
                "description": "Customer dimension table",
                "columns": [
                    "CUSTOMER_ID (string, PK)",
                    "CUSTOMER_NAME (string)",
                    "TIER (string: enterprise, pro, free)",
                    "ARR_USD (float)",
                    "INDUSTRY (string)",
                    "CUSTOMER_REGION (string)",
                    "SLA (string)",
                    "ONBOARD_DATE (date)",
                ],
            },
            "fact_deployment": {
                "description": "Deployment records",
                "columns": [
                    "DEPLOYMENT_ID (string, PK)",
                    "SERVICE_ID (string, FK)",
                    "ENV (string)",
                    "REGION (string)",
                    "STARTED_AT (string)",
                    "FINISHED_AT (string)",
                    "STATUS (string)",
                    "COMMIT_SHA (string)",
                    "PR_NUMBER (int)",
                    "AUTHOR (string)",
                    "CHANGE_TYPE (string)",
                    "RISK_LEVEL (string)",
                ],
            },
            "dim_service": {
                "description": "Service dimension table",
                "columns": [
                    "SERVICE_ID (string, PK)",
                    "SERVICE_NAME (string)",
                    "TEAM (string)",
                    "TIER (string)",
                ],
            },
        },
        "usage_tips": [
            "Use fact_incident for incident queries",
            "Join fact_incident_customer_impact with dim_customer to get ARR at risk",
            "TITLE and SUMMARY contain incident descriptions",
        ],
    }

    print(json.dumps(schema, indent=2))


if __name__ == "__main__":
    main()
