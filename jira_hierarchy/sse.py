"""Server-Sent Events (SSE) utilities"""

import json
import sys
from datetime import datetime, timedelta
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


def stream_hierarchy(wfile, jira_email, jira_pat, component="AI Safety", top_level="rfe",
                     show_closed_rfes=False, show_closed_strats=False,
                     show_closed_epics=False, show_closed_tasks=False, max_age_days=365, assignees=None):
    """
    Fetch hierarchy and stream data as Server-Sent Events

    Args:
        wfile: Write file object
        jira_email: User email address
        jira_pat: API token
        component: Component name(s) to filter by (comma-separated for multiple)
        top_level: Top level to show ('rfe' or 'strat')
        show_closed_rfes: Include closed RFEs in results
        show_closed_strats: Include closed STRATs in results
        show_closed_epics: Include closed Epics in results
        show_closed_tasks: Include closed Tasks in results
        max_age_days: Maximum age of tickets in days
        assignees: List of account IDs to filter tasks by (None = all assignees)
    """
    print(f"Streaming {component} hierarchy from JIRA (top level: {top_level})...", file=sys.stderr)
    if assignees:
        print(f"Filtering tasks by assignees: {assignees}", file=sys.stderr)

    if top_level == 'strat':
        stream_hierarchy_strat_first(wfile, jira_email, jira_pat, component,
                                    show_closed_strats, show_closed_epics, show_closed_tasks, max_age_days, assignees)
    else:
        stream_hierarchy_rfe_first(wfile, jira_email, jira_pat, component,
                                  show_closed_rfes, show_closed_strats,
                                  show_closed_epics, show_closed_tasks, max_age_days, assignees)


def stream_hierarchy_rfe_first(wfile, jira_email, jira_pat, component="AI Safety",
                               show_closed_rfes=False, show_closed_strats=False,
                               show_closed_epics=False, show_closed_tasks=False, max_age_days=365, assignees=None):
    """Stream hierarchy with RFEs as top level

    Args:
        component: Component name(s) to filter by (comma-separated for multiple)
        assignees: List of account IDs to filter tasks by (None = all assignees)
    """

    from .jira_client import run_jira_query

    # Calculate cutoff date for age filter
    cutoff_date = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
    print(f"Filtering tickets created on or after: {cutoff_date}", file=sys.stderr)

    # Counters
    total_rfes = 0
    total_strats = 0
    total_epics = 0
    total_tasks = 0

    # Step 1: Batch fetch all RFEs and stream them immediately
    print("Fetching all RFEs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading RFEs...'})
    rfes = fetch_rfes(component, jira_email, jira_pat, show_closed=show_closed_rfes, max_age_days=max_age_days)
    print(f"Found {len(rfes)} RFEs", file=sys.stderr)

    if not rfes:
        send_sse_event(wfile, 'complete', {
            'total_rfes': 0, 'total_strats': 0, 'total_epics': 0, 'total_tasks': 0
        })
        return

    # Sort RFEs by last update time (most recent first)
    rfes.sort(key=lambda x: x.get('updated', ''), reverse=True)

    # Stream RFEs immediately as they're fetched
    for rfe_data in rfes:
        rfe_data['strats'] = []
        send_sse_event(wfile, 'rfe', rfe_data)
        total_rfes += 1

    # Step 2: Batch fetch all STRATs for the component (same as STRAT mode)
    print("Fetching all STRATs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading STRATs...'})

    # Use component filter instead of issueFunction (which may not be available)
    components = [c.strip() for c in component.split(',')]
    if len(components) > 1:
        component_list = ', '.join([f'"{c}"' for c in components])
        component_clause = f'component IN ({component_list})'
    else:
        component_clause = f'component = "{components[0]}"'

    strats_jql = (
        f'project = RHAISTRAT '
        f'AND {component_clause} '
        f'AND created >= {cutoff_date}'
    )
    if not show_closed_strats:
        strats_jql += ' AND status NOT IN (Closed, Resolved)'
    strats_jql += ' ORDER BY priority DESC, created DESC'

    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,issuelinks'
    strat_issues = run_jira_query(strats_jql, field_list, jira_email, jira_pat)
    print(f"Found {len(strat_issues)} STRATs total", file=sys.stderr)

    # Sort STRATs by last update time (most recent first)
    strat_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    rfe_keys = [rfe['key'] for rfe in rfes]

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
            f'AND created >= {cutoff_date}'
        )
        if not show_closed_epics:
            epics_jql += ' AND status NOT IN (Closed, Resolved)'
        # Include parent field (standard field in JIRA Cloud)
        epic_field_list = field_list + ',parent'
        epic_issues = run_jira_query(epics_jql, epic_field_list, jira_email, jira_pat)
        print(f"Found {len(epic_issues)} Epics via Parent Link", file=sys.stderr)

        # Also check for Epics linked via "is documented by" relationship
        documented_by_epics = {}  # Map of epic_key -> [strat_keys]
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
                        # Include epic if show_closed_epics is True OR status is not closed
                        if epic_key and (show_closed_epics or status not in ['Closed', 'Resolved']):
                            if epic_key not in documented_by_epics:
                                documented_by_epics[epic_key] = []
                            documented_by_epics[epic_key].append(strat_key)

        # Fetch full details for documented-by Epics that aren't already in our list
        existing_epic_keys = {e['key'] for e in epic_issues}
        for epic_key, linked_strats in documented_by_epics.items():
            if epic_key not in existing_epic_keys:
                try:
                    from .jira_client import get_jira_issue
                    epic_data = get_jira_issue(epic_key, fields=epic_field_list, jira_email=jira_email, jira_pat=jira_pat)
                    if epic_data:
                        epic_issues.append(epic_data)
                        print(f"  Added Epic {epic_key} via 'is documented by' link", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Failed to fetch Epic {epic_key}: {e}", file=sys.stderr)

        print(f"Found {len(epic_issues)} Epics total", file=sys.stderr)

        # Sort Epics by last update time (most recent first)
        epic_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

        for epic in epic_issues:
            from .data_fetcher import build_issue_data
            epic_data = build_issue_data(epic, 'epic')
            epic_key = epic_data['key']
            epic_keys_list.append(epic_key)

            # Find which STRATs this Epic is linked to
            linked_strat_keys = []

            # Check for parent field (standard field in JIRA Cloud)
            parent_field = epic.get('fields', {}).get('parent')
            parent_link = None
            if parent_field:
                if isinstance(parent_field, dict):
                    parent_link = parent_field.get('key')
                else:
                    parent_link = str(parent_field)

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
                print(f"  WARNING: Epic {epic_key} has no Parent Link or Document relationship to our STRATs", file=sys.stderr)

    # Step 4: Fetch ALL Tasks for the component (not just those linked to epics)
    tasks_by_epic = {}
    task_issues = []
    print("Fetching all Tasks...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading Tasks...'})

    # Build component filter same as for RFEs
    components = [c.strip() for c in component.split(',')]
    if len(components) > 1:
        component_list = ', '.join([f'"{c}"' for c in components])
        component_clause = f'component IN ({component_list})'
    else:
        component_clause = f'component = "{components[0]}"'

    # Fetch ALL tasks for the component from RHOAIENG project
    tasks_jql = (
        f'project = RHOAIENG '
        f'AND {component_clause} '
        f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
        f'AND created >= {cutoff_date}'
    )
    if not show_closed_tasks:
        tasks_jql += ' AND status NOT IN (Closed, Resolved)'

    # Add assignee filter if specified
    if assignees:
        assignee_list = ', '.join([f'"{a}"' for a in assignees])
        tasks_jql += f' AND assignee IN ({assignee_list})'

    # Include customfield_10014 (Epic Link) and customfield_10875 (Git Pull Request) in the field list
    task_field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,customfield_10014,customfield_10875'
    task_issues = run_jira_query(tasks_jql, task_field_list, jira_email, jira_pat, wfile=wfile, progress_message_prefix="Loading Tasks")
    print(f"Found {len(task_issues)} Tasks total for component", file=sys.stderr)

    # Sort Tasks by last update time (most recent first)
    task_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    for task in task_issues:
        from .data_fetcher import build_issue_data
        task_data = build_issue_data(task, 'task')
        task_key = task_data['key']
        task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')

        # Get the Epic Link (customfield_10014 in JIRA Cloud)
        epic_link = task['fields'].get('customfield_10014')  # Epic Link custom field

        # Try to find hierarchy context
        strat_key = None
        rfe_key = None

        if epic_link and epic_link in epic_keys_list:
            # Task is linked to an epic in our hierarchy
            if epic_link not in tasks_by_epic:
                tasks_by_epic[epic_link] = []
            tasks_by_epic[epic_link].append(task_data)

            # Find STRAT and RFE keys for this task (via its parent Epic)
            for st_key, epics in epics_by_strat.items():
                if any(e['key'] == epic_link for e in epics):
                    strat_key = st_key
                    # Find RFE from STRAT
                    for r_key, strats in strats_by_rfe.items():
                        if any(s['key'] == st_key for s in strats):
                            rfe_key = r_key
                            break
                    break

            # Add hierarchy keys if found
            if rfe_key:
                task_data['rfe_key'] = rfe_key
            if strat_key:
                task_data['strat_key'] = strat_key
            task_data['epic_key'] = epic_link
        # else: Task is not in hierarchy (no epic link or epic not in our list)

        # Stream ALL tasks (whether in hierarchy or not)
        send_sse_event(wfile, 'task', task_data)
        total_tasks += 1

    # Send completion event
    send_sse_event(wfile, 'complete', {
        'total_rfes': total_rfes,
        'total_strats': total_strats,
        'total_epics': total_epics,
        'total_tasks': total_tasks
    })

    orphaned_strats = len(strat_issues) - total_strats
    orphaned_epics = (len(epic_issues) if epic_keys_list else 0) - total_epics
    tasks_in_hierarchy = sum(len(tasks) for tasks in tasks_by_epic.values())
    tasks_outside_hierarchy = len(task_issues) - tasks_in_hierarchy

    print("\nStreaming complete!", file=sys.stderr)
    print(f"  RFEs:   {total_rfes} (fetched {len(rfes)})", file=sys.stderr)
    print(f"  STRATs: {total_strats} (fetched {len(strat_issues)}, orphaned: {orphaned_strats})", file=sys.stderr)
    print(f"  Epics:  {total_epics} (fetched {len(epic_issues) if epic_keys_list else 0}, orphaned: {orphaned_epics})", file=sys.stderr)
    print(f"  Tasks:  {total_tasks} (fetched {len(task_issues)}, in hierarchy: {tasks_in_hierarchy}, outside hierarchy: {tasks_outside_hierarchy})", file=sys.stderr)


def stream_hierarchy_strat_first(wfile, jira_email, jira_pat, component="AI Safety",
                                 show_closed_strats=False, show_closed_epics=False,
                                 show_closed_tasks=False, max_age_days=365, assignees=None):
    """Stream hierarchy with STRATs as top level

    Args:
        component: Component name(s) to filter by (comma-separated for multiple)
        assignees: List of account IDs to filter tasks by (None = all assignees)
    """

    from .jira_client import run_jira_query

    # Calculate cutoff date for age filter
    cutoff_date = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
    print(f"Filtering tickets created on or after: {cutoff_date}", file=sys.stderr)

    # Counters
    total_strats = 0
    total_epics = 0
    total_tasks = 0

    # Step 1: Batch fetch all STRATs with the component filter
    print("Fetching all STRATs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading STRATs...'})

    # Handle comma-separated components
    components = [c.strip() for c in component.split(',')]
    if len(components) > 1:
        # Multiple components: use IN clause
        component_list = ', '.join([f'"{c}"' for c in components])
        component_clause = f'component IN ({component_list})'
    else:
        # Single component: use equality
        component_clause = f'component = "{components[0]}"'

    strats_jql = (
        f'project = RHAISTRAT '
        f'AND {component_clause} '
        f'AND created >= {cutoff_date}'
    )
    if not show_closed_strats:
        strats_jql += ' AND status NOT IN (Closed, Resolved)'
    strats_jql += ' ORDER BY priority DESC, created DESC'

    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,issuelinks'
    strat_issues = run_jira_query(strats_jql, field_list, jira_email, jira_pat)
    print(f"Found {len(strat_issues)} STRATs", file=sys.stderr)

    if not strat_issues:
        send_sse_event(wfile, 'complete', {
            'total_rfes': 0, 'total_strats': 0, 'total_epics': 0, 'total_tasks': 0
        })
        return

    # Sort STRATs by last update time (most recent first)
    strat_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    # Stream STRATs immediately
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
            f'AND created >= {cutoff_date}'
        )
        if not show_closed_epics:
            epics_jql += ' AND status NOT IN (Closed, Resolved)'
        epic_field_list = field_list + ',parent'
        epic_issues = run_jira_query(epics_jql, epic_field_list, jira_email, jira_pat)
        print(f"Found {len(epic_issues)} Epics via Parent Link", file=sys.stderr)

        # Also check for Epics linked via "is documented by" relationship
        documented_by_epics = {}  # Map of epic_key -> [strat_keys]
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
                        # Include epic if show_closed_epics is True OR status is not closed
                        if epic_key and (show_closed_epics or status not in ['Closed', 'Resolved']):
                            if epic_key not in documented_by_epics:
                                documented_by_epics[epic_key] = []
                            documented_by_epics[epic_key].append(strat_key)

        # Fetch full details for documented-by Epics that aren't already in our list
        existing_epic_keys = {e['key'] for e in epic_issues}
        for epic_key, linked_strats in documented_by_epics.items():
            if epic_key not in existing_epic_keys:
                try:
                    from .jira_client import get_jira_issue
                    epic_data = get_jira_issue(epic_key, fields=epic_field_list, jira_email=jira_email, jira_pat=jira_pat)
                    if epic_data:
                        epic_issues.append(epic_data)
                        print(f"  Added Epic {epic_key} via 'is documented by' link", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Failed to fetch Epic {epic_key}: {e}", file=sys.stderr)

        print(f"Found {len(epic_issues)} Epics total", file=sys.stderr)

        # Sort Epics by last update time (most recent first)
        epic_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

        for epic in epic_issues:
            from .data_fetcher import build_issue_data
            epic_data = build_issue_data(epic, 'epic')
            epic_key = epic_data['key']
            epic_keys_list.append(epic_key)

            # Find which STRATs this Epic is linked to
            linked_strat_keys = []

            # Check for parent field (standard field in JIRA Cloud)
            parent_field = epic.get('fields', {}).get('parent')

            # Extract parent key
            parent_link = None
            if parent_field:
                if isinstance(parent_field, dict):
                    parent_link = parent_field.get('key')
                else:
                    parent_link = str(parent_field)

                # Check if parent is in our STRAT list
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

                    # Stream Epic immediately
                    epic_data_copy = epic_data.copy()
                    epic_data_copy['strat_key'] = strat_key
                    epic_data_copy['tasks'] = []
                    send_sse_event(wfile, 'epic', epic_data_copy)
                    total_epics += 1
            else:
                print(f"  WARNING: Epic {epic_key} has no Parent Link or Document relationship to our STRATs", file=sys.stderr)

    # Step 3: Fetch ALL Tasks for the component (not just those linked to epics)
    tasks_by_epic = {}
    task_issues = []
    print("Fetching all Tasks...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading Tasks...'})

    # Build component filter same as for STRATs
    components = [c.strip() for c in component.split(',')]
    if len(components) > 1:
        component_list = ', '.join([f'"{c}"' for c in components])
        component_clause = f'component IN ({component_list})'
    else:
        component_clause = f'component = "{components[0]}"'

    # Fetch ALL tasks for the component from RHOAIENG project
    tasks_jql = (
        f'project = RHOAIENG '
        f'AND {component_clause} '
        f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
        f'AND created >= {cutoff_date}'
    )
    if not show_closed_tasks:
        tasks_jql += ' AND status NOT IN (Closed, Resolved)'

    # Add assignee filter if specified
    if assignees:
        assignee_list = ', '.join([f'"{a}"' for a in assignees])
        tasks_jql += f' AND assignee IN ({assignee_list})'

    task_field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,customfield_10014,customfield_10875'
    task_issues = run_jira_query(tasks_jql, task_field_list, jira_email, jira_pat, wfile=wfile, progress_message_prefix="Loading Tasks")
    print(f"Found {len(task_issues)} Tasks total for component", file=sys.stderr)

    # Sort Tasks by last update time (most recent first)
    task_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    for task in task_issues:
        from .data_fetcher import build_issue_data
        task_data = build_issue_data(task, 'task')
        task_key = task_data['key']
        task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')

        # Get the Epic Link (customfield_10014 in JIRA Cloud)
        epic_link = task['fields'].get('customfield_10014')

        # Try to find hierarchy context
        strat_key = None

        if epic_link and epic_link in epic_keys_list:
            # Task is linked to an epic in our hierarchy
            if epic_link not in tasks_by_epic:
                tasks_by_epic[epic_link] = []
            tasks_by_epic[epic_link].append(task_data)
            print(f"  Linked Task {task_key} to Epic {epic_link}", file=sys.stderr)

            # Find STRAT key for this task
            for st_key, epics in epics_by_strat.items():
                if any(e['key'] == epic_link for e in epics):
                    strat_key = st_key
                    break

            # Add hierarchy keys if found
            if strat_key:
                task_data['strat_key'] = strat_key
            task_data['epic_key'] = epic_link
        # else: Task is not in hierarchy (no epic link or epic not in our list)

        # Stream ALL tasks (whether in hierarchy or not)
        send_sse_event(wfile, 'task', task_data)
        total_tasks += 1

    # Send completion event (no RFEs in STRAT mode)
    send_sse_event(wfile, 'complete', {
        'total_rfes': 0,
        'total_strats': total_strats,
        'total_epics': total_epics,
        'total_tasks': total_tasks
    })

    orphaned_epics = (len(epic_issues) if epic_keys_list else 0) - total_epics
    tasks_in_hierarchy = sum(len(tasks) for tasks in tasks_by_epic.values())
    tasks_outside_hierarchy = len(task_issues) - tasks_in_hierarchy

    print("\nStreaming complete!", file=sys.stderr)
    print(f"  STRATs: {total_strats} (fetched {len(strat_issues)})", file=sys.stderr)
    print(f"  Epics:  {total_epics} (fetched {len(epic_issues) if epic_keys_list else 0}, orphaned: {orphaned_epics})", file=sys.stderr)
    print(f"  Tasks:  {total_tasks} (fetched {len(task_issues)}, in hierarchy: {tasks_in_hierarchy}, outside hierarchy: {tasks_outside_hierarchy})", file=sys.stderr)
