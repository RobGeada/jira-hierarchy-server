#!/usr/bin/env python3
"""
Fetch AI Safety JIRA Hierarchy Data
This script fetches STRATs → Epics → Tasks from JIRA and generates data for the HTML viewer
"""

import json
import subprocess
import sys
from datetime import datetime

def run_jira_search(jql, fields="summary,status,priority,assignee,issuelinks,parent,description"):
    """Run JIRA search using claude CLI (assumes you're running this in Claude Code context)"""
    # This is a placeholder - in actual use, you'd call the JIRA API directly
    # For now, this documents the structure needed
    print(f"Searching: {jql}", file=sys.stderr)
    return []

def extract_strat_from_description(description):
    """Extract STRAT reference from epic description (e.g., 'Parent feature: RHAISTRAT-1173')"""
    if not description:
        return None

    import re
    match = re.search(r'RHAISTRAT-\d+', description)
    return match.group(0) if match else None

def build_hierarchy():
    """Build the complete hierarchy structure"""
    print("Fetching AI Safety STRATs...", file=sys.stderr)

    hierarchy = {
        "strats": [],
        "metadata": {
            "generated": datetime.now().isoformat(),
            "total_strats": 0,
            "total_epics": 0,
            "total_tasks": 0
        }
    }

    # Step 1: Fetch all AI Safety STRATs
    strats_jql = 'project = RHAISTRAT AND issuetype = Feature AND component = "AI Safety" ORDER BY priority DESC, created DESC'
    strats = run_jira_search(strats_jql)

    print(f"Found {len(strats)} STRATs", file=sys.stderr)

    for strat in strats:
        strat_data = {
            "key": strat["key"],
            "summary": strat["summary"],
            "status": strat["status"]["name"],
            "priority": strat.get("priority", {}).get("name", "Undefined"),
            "assignee": strat.get("assignee", {}).get("display_name", "Unassigned"),
            "epics": []
        }

        # Step 2: Find epics that reference this STRAT
        epics_jql = f'component = "AI Safety" AND issuetype = Epic AND description ~ "{strat["key"]}"'
        epics = run_jira_search(epics_jql)

        print(f"  {strat['key']}: Found {len(epics)} epics", file=sys.stderr)

        for epic in epics:
            epic_data = {
                "key": epic["key"],
                "summary": epic["summary"],
                "status": epic["status"]["name"],
                "priority": epic.get("priority", {}).get("name", "Undefined"),
                "assignee": epic.get("assignee", {}).get("display_name", "Unassigned"),
                "tasks": []
            }

            # Step 3: Find tasks linked to this epic
            # Using Epic Link custom field
            tasks_jql = f'component = "AI Safety" AND "Epic Link" = {epic["key"]} AND issuetype NOT IN (Epic, Feature, "Feature Request")'
            tasks = run_jira_search(tasks_jql)

            print(f"    {epic['key']}: Found {len(tasks)} tasks", file=sys.stderr)

            for task in tasks:
                task_data = {
                    "key": task["key"],
                    "summary": task["summary"],
                    "status": task["status"]["name"],
                    "priority": task.get("priority", {}).get("name", "Undefined"),
                    "assignee": task.get("assignee", {}).get("display_name", "Unassigned"),
                    "issuetype": task.get("issuetype", {}).get("name", "Task")
                }
                epic_data["tasks"].append(task_data)

            hierarchy["metadata"]["total_tasks"] += len(epic_data["tasks"])
            strat_data["epics"].append(epic_data)

        hierarchy["metadata"]["total_epics"] += len(strat_data["epics"])
        hierarchy["strats"].append(strat_data)

    hierarchy["metadata"]["total_strats"] = len(hierarchy["strats"])

    return hierarchy

def main():
    """Main function"""
    print("=" * 60, file=sys.stderr)
    print("AI Safety JIRA Hierarchy Fetcher", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("", file=sys.stderr)

    try:
        hierarchy = build_hierarchy()

        # Output JSON to stdout
        print(json.dumps(hierarchy, indent=2))

        # Print summary to stderr
        print("", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("Summary:", file=sys.stderr)
        print(f"  STRATs: {hierarchy['metadata']['total_strats']}", file=sys.stderr)
        print(f"  Epics:  {hierarchy['metadata']['total_epics']}", file=sys.stderr)
        print(f"  Tasks:  {hierarchy['metadata']['total_tasks']}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("", file=sys.stderr)
        print("Save output to file:", file=sys.stderr)
        print("  python3 fetch-jira-hierarchy.py > hierarchy-data.json", file=sys.stderr)
        print("", file=sys.stderr)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
