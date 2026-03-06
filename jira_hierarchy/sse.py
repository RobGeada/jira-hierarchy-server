"""Server-Sent Events (SSE) utilities"""

import json
import sys
from .data_fetcher import (
    fetch_rfes,
    fetch_strats_for_rfe,
    fetch_epics_for_strat,
    fetch_tasks_for_epic
)


def send_sse_event(wfile, event_type, data):
    """
    Send a Server-Sent Event

    Args:
        wfile: Write file object
        event_type: Event type name
        data: Data to send (will be JSON encoded)
    """
    event = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    wfile.write(event.encode())
    wfile.flush()


def stream_hierarchy(wfile, jira_pat, component="AI Safety", top_level="rfe"):
    """
    Fetch hierarchy and stream data as Server-Sent Events

    Args:
        wfile: Write file object
        jira_pat: Personal Access Token
        component: Component name to filter by
        top_level: Top level to show ('rfe' or 'strat')
    """
    print(f"Streaming {component} hierarchy from JIRA (top level: {top_level})...", file=sys.stderr)

    if top_level == 'strat':
        stream_hierarchy_strat_first(wfile, jira_pat, component)
    else:
        stream_hierarchy_rfe_first(wfile, jira_pat, component)


def stream_hierarchy_rfe_first(wfile, jira_pat, component="AI Safety"):
    """Stream hierarchy with RFEs as top level"""

    from .jira_client import run_jira_query

    # Counters
    total_rfes = 0
    total_strats = 0
    total_epics = 0
    total_tasks = 0

    # Step 1: Batch fetch all RFEs and stream them immediately
    print("Fetching all RFEs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading RFEs...'})
    rfes = fetch_rfes(component, jira_pat)
    print(f"Found {len(rfes)} RFEs", file=sys.stderr)

    if not rfes:
        send_sse_event(wfile, 'complete', {
            'total_rfes': 0, 'total_strats': 0, 'total_epics': 0, 'total_tasks': 0
        })
        return

    # Stream RFEs immediately as they're fetched
    print("Streaming RFEs to UI...", file=sys.stderr)
    for rfe_data in rfes:
        rfe_data['strats'] = []
        send_sse_event(wfile, 'rfe', rfe_data)
        total_rfes += 1

    # Step 2: Batch fetch all STRATs for all RFEs
    print("Fetching all STRATs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading STRATs...'})
    rfe_keys = [rfe['key'] for rfe in rfes]
    strats_jql = (
        f'project = RHAISTRAT '
        f'AND (issueFunction in linkedIssuesOf("key in ({",".join(rfe_keys)})", "is cloned by") '
        f'OR issueFunction in linkedIssuesOf("key in ({",".join(rfe_keys)})", "clones")) '
        f'AND status NOT IN (Closed, Resolved)'
    )
    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,issuelinks'
    strat_issues = run_jira_query(strats_jql, field_list, jira_pat)
    print(f"Found {len(strat_issues)} STRATs total", file=sys.stderr)

    # Build STRAT data and map to RFEs, streaming as we go
    strats_by_rfe = {}
    strat_keys_list = []
    for strat in strat_issues:
        from .data_fetcher import build_issue_data
        strat_data = build_issue_data(strat, 'strat')
        strat_key = strat_data['key']
        strat_keys_list.append(strat_key)

        # Find which RFE this STRAT is linked to
        links = strat.get('fields', {}).get('issuelinks', [])
        found_rfe = None
        for link in links:
            # Check both inward and outward links
            inward_issue = link.get('inwardIssue', {})
            outward_issue = link.get('outwardIssue', {})

            # Check if inward issue is an RFE
            if inward_issue.get('key') in rfe_keys:
                found_rfe = inward_issue.get('key')
                break

            # Check if outward issue is an RFE
            if outward_issue.get('key') in rfe_keys:
                found_rfe = outward_issue.get('key')
                break

        if found_rfe:
            if found_rfe not in strats_by_rfe:
                strats_by_rfe[found_rfe] = []
            strats_by_rfe[found_rfe].append(strat_data)
            print(f"  Linked STRAT {strat_key} to RFE {found_rfe}", file=sys.stderr)

            # Stream STRAT immediately
            strat_data['rfe_key'] = found_rfe
            strat_data['epics'] = []
            send_sse_event(wfile, 'strat', strat_data)
            total_strats += 1
        else:
            print(f"  WARNING: STRAT {strat_key} has no RFE link, checking all links:", file=sys.stderr)
            for link in links:
                print(f"    Link type: {link.get('type', {}).get('name')}, inward: {link.get('inwardIssue', {}).get('key')}, outward: {link.get('outwardIssue', {}).get('key')}", file=sys.stderr)

    # Step 3: Batch fetch all Epics for all STRATs
    epics_by_strat = {}
    epic_keys_list = []
    epic_issues = []
    if strat_keys_list:
        print("Fetching all Epics...", file=sys.stderr)
        send_sse_event(wfile, 'progress', {'message': 'Loading Epics...'})
        # Query by Parent Link custom field since Epics link to STRATs via customfield_12313140
        epics_jql = (
            f'project = RHOAIENG '
            f'AND issuetype = Epic '
            f'AND "Parent Link" in ({",".join(strat_keys_list)}) '
            f'AND status NOT IN (Closed, Resolved)'
        )
        # Include customfield_12313140 (Parent Link) in the field list
        epic_field_list = field_list + ',customfield_12313140'
        epic_issues = run_jira_query(epics_jql, epic_field_list, jira_pat)
        print(f"Found {len(epic_issues)} Epics via Parent Link", file=sys.stderr)

        # Also check for Epics linked via "is documented by" relationship
        documented_by_epics = {}  # Map of epic_key -> [strat_keys]
        print(f"Checking {len(strat_issues)} STRATs for 'is documented by' links...", file=sys.stderr)
        for strat in strat_issues:
            strat_key = strat['key']
            issue_links = strat.get('fields', {}).get('issuelinks', [])
            if issue_links:
                print(f"  {strat_key} has {len(issue_links)} issuelinks", file=sys.stderr)
            for link in issue_links:
                link_type = link.get('type', {}).get('name', '')
                if 'document' in link_type.lower():
                    print(f"    Found Document link in {strat_key}, type={link_type}", file=sys.stderr)
                    inward_issue = link.get('inwardIssue', {})
                    outward_issue = link.get('outwardIssue', {})
                    print(f"      inward={inward_issue.get('key')}, outward={outward_issue.get('key')}", file=sys.stderr)
                    if inward_issue.get('fields', {}).get('issuetype', {}).get('name') == 'Epic':
                        epic_key = inward_issue.get('key')
                        status = inward_issue.get('fields', {}).get('status', {}).get('name')
                        print(f"      Epic {epic_key}, status={status}", file=sys.stderr)
                        if epic_key and status not in ['Closed', 'Resolved']:
                            if epic_key not in documented_by_epics:
                                documented_by_epics[epic_key] = []
                            documented_by_epics[epic_key].append(strat_key)
                            print(f"      -> Added to documented_by_epics", file=sys.stderr)

        # Fetch full details for documented-by Epics that aren't already in our list
        existing_epic_keys = {e['key'] for e in epic_issues}
        for epic_key, linked_strats in documented_by_epics.items():
            if epic_key not in existing_epic_keys:
                try:
                    from .jira_client import get_jira_issue
                    epic_data = get_jira_issue(epic_key, fields=epic_field_list, jira_pat=jira_pat)
                    if epic_data:
                        epic_issues.append(epic_data)
                        print(f"  Added Epic {epic_key} via 'is documented by' link", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Failed to fetch Epic {epic_key}: {e}", file=sys.stderr)

        print(f"Found {len(epic_issues)} Epics total", file=sys.stderr)

        for epic in epic_issues:
            from .data_fetcher import build_issue_data
            epic_data = build_issue_data(epic, 'epic')
            epic_key = epic_data['key']
            epic_keys_list.append(epic_key)

            # Find which STRATs this Epic is linked to
            linked_strat_keys = []

            # First check Parent Link custom field
            parent_link = epic.get('fields', {}).get('customfield_12313140')  # Parent Link to STRAT
            if parent_link and parent_link in strat_keys_list:
                linked_strat_keys.append(parent_link)

            # Also check if this Epic is in documented_by_epics
            if epic_key in documented_by_epics:
                for strat_key in documented_by_epics[epic_key]:
                    if strat_key not in linked_strat_keys:
                        linked_strat_keys.append(strat_key)

            # Link Epic to all related STRATs
            for strat_key in linked_strat_keys:
                if strat_key not in epics_by_strat:
                    epics_by_strat[strat_key] = []
                epics_by_strat[strat_key].append(epic_data)
                print(f"  Linked Epic {epic_key} to STRAT {strat_key}", file=sys.stderr)

                # Find RFE key for this epic (via its parent STRAT)
                rfe_key = None
                for rfe_k, strats in strats_by_rfe.items():
                    if any(s['key'] == strat_key for s in strats):
                        rfe_key = rfe_k
                        break

                # Stream Epic immediately
                if rfe_key:
                    epic_data_copy = epic_data.copy()
                    epic_data_copy['rfe_key'] = rfe_key
                    epic_data_copy['strat_key'] = strat_key
                    epic_data_copy['tasks'] = []
                    send_sse_event(wfile, 'epic', epic_data_copy)
                    total_epics += 1
                else:
                    print(f"  WARNING: Epic {epic_key} has Parent Link {parent_link} not in our STRAT list", file=sys.stderr)
            else:
                print(f"  WARNING: Epic {epic_key} has no Parent Link field", file=sys.stderr)

    # Step 4: Batch fetch all Tasks for all Epics
    tasks_by_epic = {}
    task_issues = []
    if epic_keys_list:
        print("Fetching all Tasks...", file=sys.stderr)
        send_sse_event(wfile, 'progress', {'message': 'Loading Tasks...'})
        tasks_jql = (
            f'"Epic Link" in ({",".join(epic_keys_list)}) '
            f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
            f'AND status NOT IN (Closed, Resolved)'
        )
        # Include customfield_12311140 (Epic Link) in the field list
        task_field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,customfield_12311140'
        task_issues = run_jira_query(tasks_jql, task_field_list, jira_pat)
        print(f"Found {len(task_issues)} Tasks total", file=sys.stderr)

        for task in task_issues:
            from .data_fetcher import build_issue_data
            task_data = build_issue_data(task, 'task')
            task_key = task_data['key']
            task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')

            # Get the Epic Link
            epic_link = task['fields'].get('customfield_12311140')  # Epic Link custom field
            if epic_link:
                if epic_link in epic_keys_list:
                    if epic_link not in tasks_by_epic:
                        tasks_by_epic[epic_link] = []
                    tasks_by_epic[epic_link].append(task_data)
                    print(f"  Linked Task {task_key} to Epic {epic_link}", file=sys.stderr)

                    # Find STRAT and RFE keys for this task (via its parent Epic)
                    strat_key = None
                    rfe_key = None
                    for st_key, epics in epics_by_strat.items():
                        if any(e['key'] == epic_link for e in epics):
                            strat_key = st_key
                            # Find RFE from STRAT
                            for r_key, strats in strats_by_rfe.items():
                                if any(s['key'] == st_key for s in strats):
                                    rfe_key = r_key
                                    break
                            break

                    # Stream Task immediately
                    if rfe_key and strat_key:
                        task_data['rfe_key'] = rfe_key
                        task_data['strat_key'] = strat_key
                        task_data['epic_key'] = epic_link
                        send_sse_event(wfile, 'task', task_data)
                        total_tasks += 1
                else:
                    print(f"  WARNING: Task {task_key} has Epic Link {epic_link} not in our epic list", file=sys.stderr)
            else:
                print(f"  WARNING: Task {task_key} has no Epic Link field", file=sys.stderr)

    # Send completion event
    send_sse_event(wfile, 'complete', {
        'total_rfes': total_rfes,
        'total_strats': total_strats,
        'total_epics': total_epics,
        'total_tasks': total_tasks
    })

    orphaned_strats = len(strat_issues) - total_strats
    orphaned_epics = (len(epic_issues) if epic_keys_list else 0) - total_epics
    orphaned_tasks = (len(task_issues) if epic_keys_list else 0) - total_tasks

    print("\nStreaming complete!", file=sys.stderr)
    print(f"  RFEs:   {total_rfes} (fetched {len(rfes)})", file=sys.stderr)
    print(f"  STRATs: {total_strats} (fetched {len(strat_issues)}, orphaned: {orphaned_strats})", file=sys.stderr)
    print(f"  Epics:  {total_epics} (fetched {len(epic_issues) if epic_keys_list else 0}, orphaned: {orphaned_epics})", file=sys.stderr)
    print(f"  Tasks:  {total_tasks} (fetched {len(task_issues) if epic_keys_list else 0}, orphaned: {orphaned_tasks})", file=sys.stderr)


def stream_hierarchy_strat_first(wfile, jira_pat, component="AI Safety"):
    """Stream hierarchy with STRATs as top level"""

    from .jira_client import run_jira_query

    # Counters
    total_strats = 0
    total_epics = 0
    total_tasks = 0

    # Step 1: Batch fetch all STRATs with the component filter
    print("Fetching all STRATs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading STRATs...'})
    strats_jql = (
        f'project = RHAISTRAT '
        f'AND component = "{component}" '
        f'AND status NOT IN (Closed, Resolved) '
        f'ORDER BY priority DESC, created DESC'
    )
    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,issuelinks'
    strat_issues = run_jira_query(strats_jql, field_list, jira_pat)
    print(f"Found {len(strat_issues)} STRATs", file=sys.stderr)

    if not strat_issues:
        send_sse_event(wfile, 'complete', {
            'total_rfes': 0, 'total_strats': 0, 'total_epics': 0, 'total_tasks': 0
        })
        return

    # Stream STRATs immediately
    print("Streaming STRATs to UI...", file=sys.stderr)
    strat_keys_list = []
    for strat in strat_issues:
        from .data_fetcher import build_issue_data
        strat_data = build_issue_data(strat, 'strat')
        strat_key = strat_data['key']
        strat_keys_list.append(strat_key)

        strat_data['epics'] = []
        send_sse_event(wfile, 'strat', strat_data)
        total_strats += 1

    # Step 2: Batch fetch all Epics for all STRATs
    epics_by_strat = {}
    epic_keys_list = []
    epic_issues = []
    if strat_keys_list:
        print("Fetching all Epics...", file=sys.stderr)
        send_sse_event(wfile, 'progress', {'message': 'Loading Epics...'})
        epics_jql = (
            f'project = RHOAIENG '
            f'AND issuetype = Epic '
            f'AND "Parent Link" in ({",".join(strat_keys_list)}) '
            f'AND status NOT IN (Closed, Resolved)'
        )
        epic_field_list = field_list + ',customfield_12313140'
        epic_issues = run_jira_query(epics_jql, epic_field_list, jira_pat)
        print(f"Found {len(epic_issues)} Epics via Parent Link", file=sys.stderr)

        # Also check for Epics linked via "is documented by" relationship
        documented_by_epics = {}  # Map of epic_key -> [strat_keys]
        print(f"Checking {len(strat_issues)} STRATs for 'is documented by' links...", file=sys.stderr)
        for strat in strat_issues:
            strat_key = strat['key']
            issue_links = strat.get('fields', {}).get('issuelinks', [])
            for link in issue_links:
                link_type = link.get('type', {}).get('name', '')
                if 'document' in link_type.lower():
                    inward_issue = link.get('inwardIssue', {})
                    if inward_issue.get('fields', {}).get('issuetype', {}).get('name') == 'Epic':
                        epic_key = inward_issue.get('key')
                        status = inward_issue.get('fields', {}).get('status', {}).get('name')
                        if epic_key and status not in ['Closed', 'Resolved']:
                            if epic_key not in documented_by_epics:
                                documented_by_epics[epic_key] = []
                            documented_by_epics[epic_key].append(strat_key)

        # Fetch full details for documented-by Epics that aren't already in our list
        existing_epic_keys = {e['key'] for e in epic_issues}
        for epic_key, linked_strats in documented_by_epics.items():
            if epic_key not in existing_epic_keys:
                try:
                    from .jira_client import get_jira_issue
                    epic_data = get_jira_issue(epic_key, fields=epic_field_list, jira_pat=jira_pat)
                    if epic_data:
                        epic_issues.append(epic_data)
                        print(f"  Added Epic {epic_key} via 'is documented by' link", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Failed to fetch Epic {epic_key}: {e}", file=sys.stderr)

        print(f"Found {len(epic_issues)} Epics total", file=sys.stderr)

        for epic in epic_issues:
            from .data_fetcher import build_issue_data
            epic_data = build_issue_data(epic, 'epic')
            epic_key = epic_data['key']
            epic_keys_list.append(epic_key)

            # Find which STRATs this Epic is linked to
            linked_strat_keys = []

            # First check Parent Link
            parent_link = epic.get('fields', {}).get('customfield_12313140')
            if parent_link and parent_link in strat_keys_list:
                linked_strat_keys.append(parent_link)

            # Also check if this Epic is in documented_by_epics
            if epic_key in documented_by_epics:
                for strat_key in documented_by_epics[epic_key]:
                    if strat_key not in linked_strat_keys:
                        linked_strat_keys.append(strat_key)

            # Link Epic to all related STRATs
            if linked_strat_keys:
                for strat_key in linked_strat_keys:
                    if strat_key not in epics_by_strat:
                        epics_by_strat[strat_key] = []
                    epics_by_strat[strat_key].append(epic_data)
                    print(f"  Linked Epic {epic_key} to STRAT {strat_key}", file=sys.stderr)

                    # Stream Epic immediately
                    epic_data_copy = epic_data.copy()
                    epic_data_copy['strat_key'] = strat_key
                    epic_data_copy['tasks'] = []
                    send_sse_event(wfile, 'epic', epic_data_copy)
                    total_epics += 1
            else:
                print(f"  WARNING: Epic {epic_key} has no Parent Link or Document relationship to our STRATs", file=sys.stderr)

    # Step 3: Batch fetch all Tasks for all Epics
    tasks_by_epic = {}
    task_issues = []
    if epic_keys_list:
        print("Fetching all Tasks...", file=sys.stderr)
        send_sse_event(wfile, 'progress', {'message': 'Loading Tasks...'})
        tasks_jql = (
            f'"Epic Link" in ({",".join(epic_keys_list)}) '
            f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
            f'AND status NOT IN (Closed, Resolved)'
        )
        task_field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,customfield_12311140'
        task_issues = run_jira_query(tasks_jql, task_field_list, jira_pat)
        print(f"Found {len(task_issues)} Tasks total", file=sys.stderr)

        for task in task_issues:
            from .data_fetcher import build_issue_data
            task_data = build_issue_data(task, 'task')
            task_key = task_data['key']
            task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')

            # Get the Epic Link
            epic_link = task['fields'].get('customfield_12311140')
            if epic_link:
                if epic_link in epic_keys_list:
                    if epic_link not in tasks_by_epic:
                        tasks_by_epic[epic_link] = []
                    tasks_by_epic[epic_link].append(task_data)
                    print(f"  Linked Task {task_key} to Epic {epic_link}", file=sys.stderr)

                    # Find STRAT key for this task
                    strat_key = None
                    for st_key, epics in epics_by_strat.items():
                        if any(e['key'] == epic_link for e in epics):
                            strat_key = st_key
                            break

                    # Stream Task immediately
                    if strat_key:
                        task_data['strat_key'] = strat_key
                        task_data['epic_key'] = epic_link
                        send_sse_event(wfile, 'task', task_data)
                        total_tasks += 1
                else:
                    print(f"  WARNING: Task {task_key} has Epic Link {epic_link} not in our epic list", file=sys.stderr)
            else:
                print(f"  WARNING: Task {task_key} has no Epic Link field", file=sys.stderr)

    # Send completion event (no RFEs in STRAT mode)
    send_sse_event(wfile, 'complete', {
        'total_rfes': 0,
        'total_strats': total_strats,
        'total_epics': total_epics,
        'total_tasks': total_tasks
    })

    orphaned_epics = (len(epic_issues) if epic_keys_list else 0) - total_epics
    orphaned_tasks = (len(task_issues) if epic_keys_list else 0) - total_tasks

    print("\nStreaming complete!", file=sys.stderr)
    print(f"  STRATs: {total_strats} (fetched {len(strat_issues)})", file=sys.stderr)
    print(f"  Epics:  {total_epics} (fetched {len(epic_issues) if epic_keys_list else 0}, orphaned: {orphaned_epics})", file=sys.stderr)
    print(f"  Tasks:  {total_tasks} (fetched {len(task_issues) if epic_keys_list else 0}, orphaned: {orphaned_tasks})", file=sys.stderr)
