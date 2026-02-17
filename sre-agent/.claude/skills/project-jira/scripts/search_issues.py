#!/usr/bin/env python3
"""Search Jira issues using JQL.

Usage:
    python search_issues.py --jql "type = Bug AND created >= -7d"
    python search_issues.py --jql "labels = incident" --max-results 50
"""

import argparse
import json
import sys

from jira_client import extract_adf_text, get_browse_url, jira_request


def main():
    parser = argparse.ArgumentParser(description="Search Jira issues using JQL")
    parser.add_argument("--jql", required=True, help="JQL query string")
    parser.add_argument(
        "--max-results", type=int, default=50, help="Maximum results (default: 50)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = jira_request(
            "GET",
            "/search",
            params={
                "jql": args.jql,
                "maxResults": args.max_results,
                "fields": "summary,status,issuetype,priority,assignee,reporter,created,updated,labels,description",
            },
        )

        browse_url = get_browse_url()
        issues = []
        for item in data.get("issues", []):
            f = item.get("fields", {})
            desc = extract_adf_text(f.get("description"))
            if len(desc) > 500:
                desc = desc[:500] + "..."

            issue = {
                "key": item["key"],
                "summary": f.get("summary"),
                "status": f.get("status", {}).get("name") if f.get("status") else None,
                "type": (
                    f.get("issuetype", {}).get("name") if f.get("issuetype") else None
                ),
                "priority": (
                    f.get("priority", {}).get("name") if f.get("priority") else None
                ),
                "assignee": (
                    f.get("assignee", {}).get("displayName")
                    if f.get("assignee")
                    else None
                ),
                "created": f.get("created"),
                "updated": f.get("updated"),
                "labels": f.get("labels", []),
            }
            if desc:
                issue["description_snippet"] = desc
            if browse_url:
                issue["url"] = f"{browse_url}/browse/{item['key']}"
            issues.append(issue)

        status_counts = {}
        priority_counts = {}
        for issue in issues:
            s = issue.get("status")
            if s:
                status_counts[s] = status_counts.get(s, 0) + 1
            p = issue.get("priority")
            if p:
                priority_counts[p] = priority_counts.get(p, 0) + 1

        result = {
            "ok": True,
            "jql": args.jql,
            "total": data.get("total", len(issues)),
            "count": len(issues),
            "summary": {"by_status": status_counts, "by_priority": priority_counts},
            "issues": issues,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"JQL: {args.jql}")
            print(
                f"Found: {data.get('total', len(issues))} issues (showing {len(issues)})"
            )
            if status_counts:
                print(
                    f"By status: {', '.join(f'{k}: {v}' for k, v in status_counts.items())}"
                )
            print()
            for issue in issues:
                print(
                    f"  [{issue.get('status', '?')}] {issue['key']} - {issue.get('summary', '')}"
                )
                print(
                    f"    Priority: {issue.get('priority', '?')} | Assignee: {issue.get('assignee', 'Unassigned')}"
                )
                if issue.get("labels"):
                    print(f"    Labels: {', '.join(issue['labels'])}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
