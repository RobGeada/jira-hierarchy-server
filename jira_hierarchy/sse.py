"""Server-Sent Events (SSE) utilities"""

import json
import sys
from datetime import datetime, timedelta
from .data_fetcher import (
    fetch_outcomes,
    fetch_rfes,
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


def stream_hierarchy(wfile, jira_email, jira_pat, component="AI Safety",
                     show_closed_outcomes=False, show_closed_rfes=False,
                     show_closed_initiatives=False, show_closed_strats=False,
                     show_closed_epics=False, show_closed_tasks=False,
                     max_age_days=365, assignees=None):
    """
    Fetch hierarchy and stream data as Server-Sent Events.

    Hierarchy: Outcome -> RFE -> Strat -> Epic -> Task
               Outcome -> Initiative -> Epic -> Task

    Args:
        wfile: Write file object
        jira_email: User email address
        jira_pat: API token
        component: Component name(s) to filter by (comma-separated for multiple)
        show_closed_outcomes: Include closed Outcomes
        show_closed_rfes: Include closed RFEs
        show_closed_initiatives: Include closed Initiatives
        show_closed_strats: Include closed STRATs
        show_closed_epics: Include closed Epics
        show_closed_tasks: Include closed Tasks
        max_age_days: Maximum age of tickets in days
        assignees: List of account IDs to filter tasks by (None = all assignees)
    """
    print(f"Streaming {component} hierarchy from JIRA...", file=sys.stderr)
    if assignees:
        print(f"Filtering tasks by assignees: {assignees}", file=sys.stderr)

    from .jira_client import run_jira_query, get_jira_issue
    from .data_fetcher import build_issue_data

    cutoff_date = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
    print(f"Filtering tickets updated on or after: {cutoff_date}", file=sys.stderr)

    # Build component filter clause
    components = [c.strip() for c in component.split(',')]
    if len(components) > 1:
        component_list = ', '.join([f'"{c}"' for c in components])
        component_clause = f'component IN ({component_list})'
    else:
        component_clause = f'component = "{components[0]}"'

    # Counters
    total_outcomes = 0
    total_rfes = 0
    total_initiatives = 0
    total_strats = 0
    total_epics = 0
    total_tasks = 0

    # =========================================================================
    # Step 1: Fetch Outcomes and parse depends-on links
    # =========================================================================
    print("Fetching Outcomes...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading Outcomes...'})
    outcomes = fetch_outcomes(component, jira_email, jira_pat, show_closed=show_closed_outcomes, max_age_days=max_age_days)
    print(f"Found {len(outcomes)} Outcomes", file=sys.stderr)

    outcomes.sort(key=lambda x: x.get('updated', ''), reverse=True)

    outcome_keys = [o['key'] for o in outcomes]

    # Parse depends-on links from Outcomes: outcome_key -> set of issue keys it depends on
    # Also build reverse mapping: issue_key -> set of outcome_keys that depend on it
    outcome_depends_on = {}
    depended_on_by_outcomes = {}
    for outcome_data in outcomes:
        depends_on_keys = set()
        for link in outcome_data.get('issuelinks', []):
            link_type = link.get('type', {}).get('name', '').lower()
            if 'depend' not in link_type:
                continue
            # "depends on" = outwardIssue; "is depended on by" = inwardIssue
            outward = link.get('outwardIssue', {})
            inward = link.get('inwardIssue', {})
            outward_desc = link.get('type', {}).get('outward', '').lower()
            if outward.get('key') and 'depends on' in outward_desc:
                depends_on_keys.add(outward['key'])
            elif inward.get('key') and 'depends on' not in outward_desc:
                depends_on_keys.add(inward['key'])
        if depends_on_keys:
            outcome_depends_on[outcome_data['key']] = depends_on_keys
            for dep_key in depends_on_keys:
                if dep_key not in depended_on_by_outcomes:
                    depended_on_by_outcomes[dep_key] = set()
                depended_on_by_outcomes[dep_key].add(outcome_data['key'])
            print(f"  Outcome {outcome_data['key']} depends on: {depends_on_keys}", file=sys.stderr)

    for outcome_data in outcomes:
        outcome_data.pop('issuelinks', None)
        outcome_data['rfes'] = []
        outcome_data['initiatives'] = []
        send_sse_event(wfile, 'outcome', outcome_data)
        total_outcomes += 1

    # =========================================================================
    # Step 2: Fetch RFEs and link to Outcomes (many-to-many)
    # =========================================================================
    print("Fetching RFEs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading RFEs...'})
    rfes = fetch_rfes(component, jira_email, jira_pat, show_closed=show_closed_rfes, max_age_days=max_age_days)
    print(f"Found {len(rfes)} RFEs", file=sys.stderr)

    rfes.sort(key=lambda x: x.get('updated', ''), reverse=True)

    rfe_keys = [rfe['key'] for rfe in rfes]
    rfes_by_outcome = {}

    for rfe_data in rfes:
        rfe_data.pop('issuelinks', None)
        rfe_data['strats'] = []

        # Collect all outcome_keys for this RFE (parent + depends-on)
        rfe_outcome_keys = []
        parent_outcome_key = rfe_data.get('outcome_key')
        if parent_outcome_key and parent_outcome_key in outcome_keys:
            rfe_outcome_keys.append(parent_outcome_key)

        # Check if any Outcomes depend on this RFE
        for dep_outcome_key in depended_on_by_outcomes.get(rfe_data['key'], set()):
            if dep_outcome_key in outcome_keys and dep_outcome_key not in rfe_outcome_keys:
                rfe_outcome_keys.append(dep_outcome_key)

        if not rfe_outcome_keys:
            rfe_outcome_keys = ['__orphan__']
            print(f"  RFE {rfe_data['key']} has no Outcome link, treating as orphan", file=sys.stderr)

        # Send one SSE event per Outcome this RFE belongs to
        for outcome_key in rfe_outcome_keys:
            rfe_copy = rfe_data.copy()
            rfe_copy['strats'] = []
            rfe_copy['outcome_key'] = outcome_key
            if outcome_key not in rfes_by_outcome:
                rfes_by_outcome[outcome_key] = []
            rfes_by_outcome[outcome_key].append(rfe_copy)
            send_sse_event(wfile, 'rfe', rfe_copy)
            total_rfes += 1

    # =========================================================================
    # Step 3: Fetch Initiatives and link to Outcomes
    # =========================================================================
    print("Fetching Initiatives...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading Initiatives...'})

    initiatives_jql = (
        f'project = RHAISTRAT '
        f'AND issuetype = Initiative '
        f'AND {component_clause} '
        f'AND updated >= {cutoff_date}'
    )
    if not show_closed_initiatives:
        initiatives_jql += ' AND status NOT IN (Closed, Resolved)'
    initiatives_jql += ' ORDER BY priority DESC, created DESC'

    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,parent,issuelinks'
    initiative_issues = run_jira_query(initiatives_jql, field_list, jira_email, jira_pat)
    print(f"Found {len(initiative_issues)} Initiatives", file=sys.stderr)

    initiative_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    initiative_keys_list = []
    initiatives_by_outcome = {}

    for initiative in initiative_issues:
        initiative_data = build_issue_data(initiative, 'initiative')
        initiative_key = initiative_data['key']
        initiative_keys_list.append(initiative_key)

        # Find parent Outcome via Parent Link
        parent_field = initiative.get('fields', {}).get('parent')
        outcome_key = None
        if parent_field and isinstance(parent_field, dict):
            outcome_key = parent_field.get('key')

        if outcome_key and outcome_key in outcome_keys:
            initiative_data['outcome_key'] = outcome_key
        else:
            initiative_data['outcome_key'] = '__orphan__'
            print(f"  Initiative {initiative_key} has no Outcome link, treating as orphan", file=sys.stderr)

        effective_outcome = initiative_data['outcome_key']
        if effective_outcome not in initiatives_by_outcome:
            initiatives_by_outcome[effective_outcome] = []
        initiatives_by_outcome[effective_outcome].append(initiative_data)

        initiative_data['epics'] = []
        send_sse_event(wfile, 'initiative', initiative_data)
        total_initiatives += 1

    # =========================================================================
    # Step 4: Fetch STRATs and link to RFEs
    # =========================================================================
    print("Fetching STRATs...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading STRATs...'})

    strats_jql = (
        f'project = RHAISTRAT '
        f'AND issuetype NOT IN (Outcome, Initiative) '
        f'AND {component_clause} '
        f'AND updated >= {cutoff_date}'
    )
    if not show_closed_strats:
        strats_jql += ' AND status NOT IN (Closed, Resolved)'
    strats_jql += ' ORDER BY priority DESC, created DESC'

    strat_field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,issuelinks,parent'
    strat_issues = run_jira_query(strats_jql, strat_field_list, jira_email, jira_pat)
    print(f"Found {len(strat_issues)} STRATs", file=sys.stderr)

    strat_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    strats_by_rfe = {}
    strat_keys_list = []

    for strat in strat_issues:
        strat_data = build_issue_data(strat, 'strat')
        strat_key = strat_data['key']
        strat_keys_list.append(strat_key)

        # Find which RFE this STRAT is linked to via "Cloners" issuelinks (clone/cloned-by)
        links = strat.get('fields', {}).get('issuelinks', [])
        found_rfe = None
        for link in links:
            link_type = link.get('type', {}).get('name', '')
            if link_type != 'Cloners':
                continue

            inward_issue = link.get('inwardIssue', {})
            outward_issue = link.get('outwardIssue', {})

            if inward_issue.get('key') in rfe_keys:
                found_rfe = inward_issue.get('key')
                break
            if outward_issue.get('key') in rfe_keys:
                found_rfe = outward_issue.get('key')
                break

        # Collect all Outcome keys this STRAT should appear under
        strat_outcome_keys = set()

        if found_rfe:
            if found_rfe not in strats_by_rfe:
                strats_by_rfe[found_rfe] = []
            strats_by_rfe[found_rfe].append(strat_data)
            strat_data['rfe_key'] = found_rfe

            # Find all Outcomes this RFE belongs to
            for o_key, rfe_list in rfes_by_outcome.items():
                if any(r['key'] == found_rfe for r in rfe_list):
                    strat_outcome_keys.add(o_key)

        # Check if this STRAT has a direct parent that is an Outcome
        strat_parent_field = strat.get('fields', {}).get('parent')
        if strat_parent_field and isinstance(strat_parent_field, dict):
            parent_key = strat_parent_field.get('key')
            if parent_key and parent_key in outcome_keys and parent_key not in strat_outcome_keys:
                strat_outcome_keys.add(parent_key)
                print(f"  STRAT {strat_key} has direct parent Outcome {parent_key}", file=sys.stderr)

        # Check if any Outcomes depend on this STRAT directly
        for dep_outcome_key in depended_on_by_outcomes.get(strat_key, set()):
            if dep_outcome_key in outcome_keys and dep_outcome_key not in strat_outcome_keys:
                strat_outcome_keys.add(dep_outcome_key)

        # For any Outcome that needs this STRAT (via depends-on or direct parent),
        # ensure the RFE also appears under that Outcome
        for extra_outcome_key in strat_outcome_keys:
            if found_rfe:
                if extra_outcome_key not in rfes_by_outcome:
                    rfes_by_outcome[extra_outcome_key] = []
                rfe_already_under_outcome = any(r['key'] == found_rfe for r in rfes_by_outcome.get(extra_outcome_key, []))
                if not rfe_already_under_outcome:
                    original_rfe = next((r for r in rfes if r['key'] == found_rfe), None)
                    if original_rfe:
                        rfe_copy = original_rfe.copy()
                        rfe_copy['strats'] = []
                        rfe_copy['outcome_key'] = extra_outcome_key
                        rfe_copy.pop('issuelinks', None)
                        rfes_by_outcome[extra_outcome_key].append(rfe_copy)
                        send_sse_event(wfile, 'rfe', rfe_copy)
                        total_rfes += 1
                        print(f"  Injected RFE {found_rfe} under Outcome {extra_outcome_key} (via STRAT {strat_key})", file=sys.stderr)

        if found_rfe and strat_outcome_keys:
            # Send one STRAT event per Outcome it should appear under
            for o_key in strat_outcome_keys:
                strat_copy = strat_data.copy()
                strat_copy['epics'] = []
                strat_copy['rfe_key'] = found_rfe
                strat_copy['outcome_key'] = o_key
                send_sse_event(wfile, 'strat', strat_copy)
                total_strats += 1
        elif not found_rfe and strat_outcome_keys:
            # Strat with no RFE but depended-on by Outcomes - show as orphan under those Outcomes
            for o_key in strat_outcome_keys:
                strat_copy = strat_data.copy()
                strat_copy['epics'] = []
                strat_copy['outcome_key'] = o_key
                send_sse_event(wfile, 'strat', strat_copy)
                total_strats += 1
        elif not found_rfe:
            print(f"  WARNING: STRAT {strat_key} has no RFE link, checking all links:", file=sys.stderr)
            for link in links:
                print(f"    Link type: {link.get('type', {}).get('name')}, inward: {link.get('inwardIssue', {}).get('key')}, outward: {link.get('outwardIssue', {}).get('key')}", file=sys.stderr)

    # =========================================================================
    # Step 5: Fetch Epics for all STRATs and Initiatives
    # =========================================================================
    all_parent_keys = strat_keys_list + initiative_keys_list
    epics_by_parent = {}
    epic_keys_list = []
    epic_issues = []

    if all_parent_keys:
        print("Fetching Epics...", file=sys.stderr)
        send_sse_event(wfile, 'progress', {'message': 'Loading Epics...'})

        epics_jql = (
            f'project = RHOAIENG '
            f'AND issuetype = Epic '
            f'AND "Parent Link" in ({",".join(all_parent_keys)}) '
            f'AND updated >= {cutoff_date}'
        )
        if not show_closed_epics:
            epics_jql += ' AND status NOT IN (Closed, Resolved)'

        epic_field_list = strat_field_list + ',parent'
        epic_issues = run_jira_query(epics_jql, epic_field_list, jira_email, jira_pat)
        print(f"Found {len(epic_issues)} Epics via Parent Link", file=sys.stderr)

        # Also check for Epics linked via "is documented by" relationship
        documented_by_epics = {}
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
                        if epic_key and (show_closed_epics or status not in ['Closed', 'Resolved']):
                            if epic_key not in documented_by_epics:
                                documented_by_epics[epic_key] = []
                            documented_by_epics[epic_key].append(strat_key)

        # Also check initiatives for "is documented by"
        for initiative in initiative_issues:
            init_key = initiative['key']
            issue_links = initiative.get('fields', {}).get('issuelinks', [])
            for link in issue_links:
                link_type = link.get('type', {}).get('name', '')
                if 'document' in link_type.lower():
                    inward_issue = link.get('inwardIssue', {})
                    if inward_issue.get('fields', {}).get('issuetype', {}).get('name') == 'Epic':
                        epic_key = inward_issue.get('key')
                        status = inward_issue.get('fields', {}).get('status', {}).get('name')
                        if epic_key and (show_closed_epics or status not in ['Closed', 'Resolved']):
                            if epic_key not in documented_by_epics:
                                documented_by_epics[epic_key] = []
                            documented_by_epics[epic_key].append(init_key)

        # Fetch full details for documented-by Epics not already in our list
        existing_epic_keys = {e['key'] for e in epic_issues}
        for epic_key in documented_by_epics:
            if epic_key not in existing_epic_keys:
                try:
                    epic_data = get_jira_issue(epic_key, fields=epic_field_list, jira_email=jira_email, jira_pat=jira_pat)
                    if epic_data:
                        epic_issues.append(epic_data)
                        print(f"  Added Epic {epic_key} via 'is documented by' link", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Failed to fetch Epic {epic_key}: {e}", file=sys.stderr)

        print(f"Found {len(epic_issues)} Epics total", file=sys.stderr)

        epic_issues.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

        for epic in epic_issues:
            epic_data = build_issue_data(epic, 'epic')
            epic_key = epic_data['key']
            epic_keys_list.append(epic_key)

            # Find parent via Parent Link field
            linked_parent_keys = []
            parent_field = epic.get('fields', {}).get('parent')
            parent_link = None
            if parent_field:
                if isinstance(parent_field, dict):
                    parent_link = parent_field.get('key')
                else:
                    parent_link = str(parent_field)

                if parent_link and parent_link in all_parent_keys:
                    linked_parent_keys.append(parent_link)

            # Also check documented-by links
            if epic_key in documented_by_epics:
                for parent_key in documented_by_epics[epic_key]:
                    if parent_key not in linked_parent_keys:
                        linked_parent_keys.append(parent_key)

            if linked_parent_keys:
                for parent_key in linked_parent_keys:
                    if parent_key not in epics_by_parent:
                        epics_by_parent[parent_key] = []
                    epics_by_parent[parent_key].append(epic_data)

                    # Determine if parent is a STRAT or Initiative
                    if parent_key in strat_keys_list:
                        # Find RFE for this STRAT
                        rfe_key = None
                        for r_key, strats in strats_by_rfe.items():
                            if any(s['key'] == parent_key for s in strats):
                                rfe_key = r_key
                                break
                        # Find all Outcomes this strat/rfe appears under
                        epic_outcome_keys = set()
                        if rfe_key:
                            for o_key, rfe_list in rfes_by_outcome.items():
                                if any(r['key'] == rfe_key for r in rfe_list):
                                    epic_outcome_keys.add(o_key)
                        if not epic_outcome_keys:
                            epic_outcome_keys.add(None)
                        for o_key in epic_outcome_keys:
                            epic_data_copy = epic_data.copy()
                            epic_data_copy['tasks'] = []
                            epic_data_copy['strat_key'] = parent_key
                            if rfe_key:
                                epic_data_copy['rfe_key'] = rfe_key
                            if o_key:
                                epic_data_copy['outcome_key'] = o_key
                            send_sse_event(wfile, 'epic', epic_data_copy)
                            total_epics += 1
                    elif parent_key in initiative_keys_list:
                        epic_data_copy = epic_data.copy()
                        epic_data_copy['tasks'] = []
                        epic_data_copy['initiative_key'] = parent_key
                        for o_key, init_list in initiatives_by_outcome.items():
                            if any(i['key'] == parent_key for i in init_list):
                                epic_data_copy['outcome_key'] = o_key
                                break
                        send_sse_event(wfile, 'epic', epic_data_copy)
                        total_epics += 1
            else:
                print(f"  WARNING: Epic {epic_key} has no Parent Link to our STRATs/Initiatives", file=sys.stderr)

    # =========================================================================
    # Step 6: Fetch Tasks
    # =========================================================================
    tasks_by_epic = {}
    total_task_issues = 0
    print("Fetching Tasks...", file=sys.stderr)
    send_sse_event(wfile, 'progress', {'message': 'Loading Tasks...'})

    tasks_jql = (
        f'project = RHOAIENG '
        f'AND {component_clause} '
        f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
        f'AND updated >= {cutoff_date}'
    )
    if not show_closed_tasks:
        tasks_jql += ' AND status NOT IN (Closed, Resolved)'

    if assignees:
        assignee_list = ', '.join([f'"{a}"' for a in assignees])
        tasks_jql += f' AND assignee IN ({assignee_list})'

    task_field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,customfield_10014,customfield_10875'

    from .jira_client import iter_jira_query
    for task_batch, fetched_so_far in iter_jira_query(tasks_jql, task_field_list, jira_email, jira_pat):
        send_sse_event(wfile, 'progress', {'message': f'Loading Tasks... ({fetched_so_far} fetched)'})
        total_task_issues = fetched_so_far

        for task in task_batch:
            task_data = build_issue_data(task, 'task')
            task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')

            epic_link = task['fields'].get('customfield_10014')

            if epic_link and epic_link in epic_keys_list:
                if epic_link not in tasks_by_epic:
                    tasks_by_epic[epic_link] = []
                tasks_by_epic[epic_link].append(task_data)

                task_data['epic_key'] = epic_link

                # Find all hierarchy contexts for this task (many-to-many)
                task_contexts = []
                for parent_key, epics in epics_by_parent.items():
                    if any(e['key'] == epic_link for e in epics):
                        if parent_key in strat_keys_list:
                            rfe_key = None
                            for r_key, strats in strats_by_rfe.items():
                                if any(s['key'] == parent_key for s in strats):
                                    rfe_key = r_key
                                    break
                            outcome_keys_for_task = set()
                            if rfe_key:
                                for o_key, rfe_list in rfes_by_outcome.items():
                                    if any(r['key'] == rfe_key for r in rfe_list):
                                        outcome_keys_for_task.add(o_key)
                            for o_key in (outcome_keys_for_task or {None}):
                                task_contexts.append({
                                    'strat_key': parent_key,
                                    'rfe_key': rfe_key,
                                    'outcome_key': o_key,
                                })
                        elif parent_key in initiative_keys_list:
                            o_key = None
                            for ok, init_list in initiatives_by_outcome.items():
                                if any(i['key'] == parent_key for i in init_list):
                                    o_key = ok
                                    break
                            task_contexts.append({
                                'initiative_key': parent_key,
                                'outcome_key': o_key,
                            })

                if task_contexts:
                    for ctx in task_contexts:
                        task_copy = task_data.copy()
                        task_copy.update(ctx)
                        send_sse_event(wfile, 'task', task_copy)
                        total_tasks += 1
                else:
                    send_sse_event(wfile, 'task', task_data)
                    total_tasks += 1
            else:
                send_sse_event(wfile, 'task', task_data)
                total_tasks += 1

    print(f"Found {total_task_issues} Tasks total for component", file=sys.stderr)

    # Send completion event
    send_sse_event(wfile, 'complete', {
        'total_outcomes': total_outcomes,
        'total_rfes': total_rfes,
        'total_initiatives': total_initiatives,
        'total_strats': total_strats,
        'total_epics': total_epics,
        'total_tasks': total_tasks
    })

    tasks_in_hierarchy = sum(len(tasks) for tasks in tasks_by_epic.values())
    tasks_outside_hierarchy = total_task_issues - tasks_in_hierarchy

    print("\nStreaming complete!", file=sys.stderr)
    print(f"  Outcomes:     {total_outcomes}", file=sys.stderr)
    print(f"  RFEs:         {total_rfes} (fetched {len(rfes)})", file=sys.stderr)
    print(f"  Initiatives:  {total_initiatives} (fetched {len(initiative_issues)})", file=sys.stderr)
    print(f"  STRATs:       {total_strats} (fetched {len(strat_issues)})", file=sys.stderr)
    print(f"  Epics:        {total_epics} (fetched {len(epic_issues) if epic_keys_list else 0})", file=sys.stderr)
    print(f"  Tasks:        {total_tasks} (fetched {total_task_issues}, in hierarchy: {tasks_in_hierarchy}, outside: {tasks_outside_hierarchy})", file=sys.stderr)
