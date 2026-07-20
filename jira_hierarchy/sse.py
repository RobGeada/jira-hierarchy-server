"""Server-Sent Events (SSE) utilities"""

import json
import sys
from datetime import datetime, timedelta


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


def _is_closed(issue):
    status = issue.get('fields', {}).get('status', {}).get('name', '')
    return status in ('Closed', 'Resolved')


def stream_hierarchy(wfile, jira_email, jira_pat, component="AI Safety",
                     show_closed_outcomes=False, show_closed_rfes=False,
                     show_closed_initiatives=False, show_closed_strats=False,
                     show_closed_epics=False, show_closed_tasks=False,
                     max_age_days=365, assignees=None):
    """
    Fetch hierarchy and stream data as Server-Sent Events.
    Uses 3 parallel bulk queries (RHAISTRAT, RHAIRFE, RHOAIENG) then
    builds the hierarchy graph in-memory and streams events.
    """
    print(f"Streaming {component} hierarchy from JIRA...", file=sys.stderr)
    if assignees:
        print(f"Filtering tasks by assignees: {assignees}", file=sys.stderr)

    from .jira_client import run_parallel_queries, get_jira_issue
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

    # =========================================================================
    # Phase A: Parallel bulk fetch from 3 projects
    # =========================================================================
    send_sse_event(wfile, 'progress', {'message': 'Fetching data from JIRA...'})

    rhaistrat_fields = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,issuelinks,parent,issuetype,customfield_10028,fixVersions'
    rhairfe_fields = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,parent,issuelinks,customfield_10028,fixVersions,customfield_10855'
    rhoaieng_fields = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,parent,issuelinks,customfield_10014,customfield_10875,customfield_10028,fixVersions'

    rhaistrat_jql = (
        f'project = RHAISTRAT '
        f'AND {component_clause} '
        f'AND updated >= {cutoff_date}'
    )

    rhairfe_jql = (
        f'project = RHAIRFE '
        f'AND issuetype = "Feature Request" '
        f'AND {component_clause} '
        f'AND updated >= {cutoff_date}'
    )

    rhoaieng_base_jql = (
        f'project = RHOAIENG '
        f'AND {component_clause} '
        f'AND updated >= {cutoff_date}'
    )

    queries = [
        (rhaistrat_jql, rhaistrat_fields, 'RHAISTRAT'),
        (rhairfe_jql, rhairfe_fields, 'RHAIRFE'),
    ]

    # Split RHOAIENG into parallel per-assignee queries when filtered,
    # plus a separate Epics query (epics aren't assignee-filtered)
    epics_jql = rhoaieng_base_jql + ' AND issuetype = Epic'
    queries.append((epics_jql, rhoaieng_fields, 'RHOAIENG'))

    if assignees:
        # One query per assignee for non-Epic types — runs in parallel
        for assignee_id in assignees:
            task_jql = (
                rhoaieng_base_jql +
                f' AND issuetype NOT IN (Epic, Feature, "Feature Request")'
                f' AND assignee = "{assignee_id}"'
            )
            queries.append((task_jql, rhoaieng_fields, 'RHOAIENG'))
    else:
        task_jql = (
            rhoaieng_base_jql +
            ' AND issuetype NOT IN (Epic, Feature, "Feature Request")'
        )
        queries.append((task_jql, rhoaieng_fields, 'RHOAIENG'))

    raw_results = run_parallel_queries(queries, jira_email, jira_pat, wfile)

    rhaistrat_issues = raw_results.get('RHAISTRAT', [])
    rhairfe_issues = raw_results.get('RHAIRFE', [])
    rhoaieng_issues = raw_results.get('RHOAIENG', [])

    print(f"Fetched {len(rhaistrat_issues)} RHAISTRAT, {len(rhairfe_issues)} RHAIRFE, {len(rhoaieng_issues)} RHOAIENG issues", file=sys.stderr)

    # =========================================================================
    # Phase B: Split by issuetype and apply status filters
    # =========================================================================
    send_sse_event(wfile, 'progress', {'message': 'Building hierarchy...'})

    # Split RHAISTRAT by issuetype
    outcome_issues_raw = []
    initiative_issues_raw = []
    strat_issues_raw = []
    for issue in rhaistrat_issues:
        itype = issue.get('fields', {}).get('issuetype', {}).get('name', '')
        if itype == 'Outcome':
            if show_closed_outcomes or not _is_closed(issue):
                outcome_issues_raw.append(issue)
        elif itype == 'Initiative':
            if show_closed_initiatives or not _is_closed(issue):
                initiative_issues_raw.append(issue)
        else:
            if show_closed_strats or not _is_closed(issue):
                strat_issues_raw.append(issue)

    # Filter RFEs
    rfe_issues_raw = [i for i in rhairfe_issues if show_closed_rfes or not _is_closed(i)]

    # Split RHOAIENG by issuetype
    epic_issues_raw = []
    task_issues_raw = []
    for issue in rhoaieng_issues:
        itype = issue.get('fields', {}).get('issuetype', {}).get('name', '')
        if itype == 'Epic':
            if show_closed_epics or not _is_closed(issue):
                epic_issues_raw.append(issue)
        elif itype not in ('Feature', 'Feature Request'):
            if show_closed_tasks or not _is_closed(issue):
                if not assignees or (issue.get('fields', {}).get('assignee') or {}).get('accountId') in assignees:
                    task_issues_raw.append(issue)

    print(f"  Outcomes: {len(outcome_issues_raw)}, RFEs: {len(rfe_issues_raw)}, "
          f"Initiatives: {len(initiative_issues_raw)}, STRATs: {len(strat_issues_raw)}, "
          f"Epics: {len(epic_issues_raw)}, Tasks: {len(task_issues_raw)}", file=sys.stderr)

    # Counters
    total_outcomes = 0
    total_rfes = 0
    total_initiatives = 0
    total_strats = 0
    total_epics = 0
    total_tasks = 0

    # =========================================================================
    # Step 1: Process Outcomes and parse depends-on links
    # =========================================================================
    outcomes = []
    for issue in outcome_issues_raw:
        outcome_data = build_issue_data(issue, 'outcome')
        outcome_data['issuelinks'] = issue.get('fields', {}).get('issuelinks', [])
        outcomes.append(outcome_data)

    outcomes.sort(key=lambda x: x.get('updated', ''), reverse=True)
    outcome_keys = [o['key'] for o in outcomes]

    outcome_depends_on = {}
    depended_on_by_outcomes = {}
    for outcome_data in outcomes:
        depends_on_keys = set()
        for link in outcome_data.get('issuelinks', []):
            link_type = link.get('type', {}).get('name', '').lower()
            if 'depend' not in link_type:
                continue
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
    # Step 2: Process RFEs and link to Outcomes
    # =========================================================================
    rfes = []
    for issue in rfe_issues_raw:
        rfe_data = build_issue_data(issue, 'rfe')
        parent_field = issue.get('fields', {}).get('parent')
        if parent_field and isinstance(parent_field, dict):
            rfe_data['outcome_key'] = parent_field.get('key')
        rfe_data['issuelinks'] = issue.get('fields', {}).get('issuelinks', [])
        rfes.append(rfe_data)

    rfes.sort(key=lambda x: x.get('updated', ''), reverse=True)
    rfe_keys = [rfe['key'] for rfe in rfes]
    rfes_by_outcome = {}

    for rfe_data in rfes:
        rfe_data.pop('issuelinks', None)
        rfe_data['strats'] = []

        rfe_outcome_keys = []
        parent_outcome_key = rfe_data.get('outcome_key')
        if parent_outcome_key and parent_outcome_key in outcome_keys:
            rfe_outcome_keys.append(parent_outcome_key)

        for dep_outcome_key in depended_on_by_outcomes.get(rfe_data['key'], set()):
            if dep_outcome_key in outcome_keys and dep_outcome_key not in rfe_outcome_keys:
                rfe_outcome_keys.append(dep_outcome_key)

        if not rfe_outcome_keys:
            rfe_outcome_keys = ['__orphan__']
            print(f"  RFE {rfe_data['key']} has no Outcome link, treating as orphan", file=sys.stderr)

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
    # Step 3: Process Initiatives and link to Outcomes
    # =========================================================================
    initiative_keys_list = []
    initiatives_by_outcome = {}

    initiative_issues_raw.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    for initiative in initiative_issues_raw:
        initiative_data = build_issue_data(initiative, 'initiative')
        initiative_key = initiative_data['key']
        initiative_keys_list.append(initiative_key)

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
    # Step 4: Process STRATs and link to RFEs
    # =========================================================================
    strat_issues_raw.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    strats_by_rfe = {}
    strats_by_outcome = {}
    strat_keys_list = []

    for strat in strat_issues_raw:
        strat_data = build_issue_data(strat, 'strat')
        strat_key = strat_data['key']
        strat_keys_list.append(strat_key)

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

        strat_outcome_keys = set()

        if found_rfe:
            if found_rfe not in strats_by_rfe:
                strats_by_rfe[found_rfe] = []
            strats_by_rfe[found_rfe].append(strat_data)
            strat_data['rfe_key'] = found_rfe

            for o_key, rfe_list in rfes_by_outcome.items():
                if any(r['key'] == found_rfe for r in rfe_list):
                    strat_outcome_keys.add(o_key)

        strat_parent_field = strat.get('fields', {}).get('parent')
        if strat_parent_field and isinstance(strat_parent_field, dict):
            parent_key = strat_parent_field.get('key')
            if parent_key and parent_key in outcome_keys and parent_key not in strat_outcome_keys:
                strat_outcome_keys.add(parent_key)
                print(f"  STRAT {strat_key} has direct parent Outcome {parent_key}", file=sys.stderr)

        for dep_outcome_key in depended_on_by_outcomes.get(strat_key, set()):
            if dep_outcome_key in outcome_keys and dep_outcome_key not in strat_outcome_keys:
                strat_outcome_keys.add(dep_outcome_key)

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

        if not strat_outcome_keys:
            strat_outcome_keys.add('__orphan__')
            if not found_rfe:
                print(f"  STRAT {strat_key} has no RFE link and no Outcome, treating as orphan", file=sys.stderr)
            else:
                print(f"  STRAT {strat_key} has RFE {found_rfe} but no Outcome, treating as orphan", file=sys.stderr)

        for o_key in strat_outcome_keys:
            strat_copy = strat_data.copy()
            strat_copy['epics'] = []
            strat_copy['outcome_key'] = o_key
            if found_rfe:
                strat_copy['rfe_key'] = found_rfe
            else:
                if o_key not in strats_by_outcome:
                    strats_by_outcome[o_key] = []
                strats_by_outcome[o_key].append(strat_data)
            send_sse_event(wfile, 'strat', strat_copy)
            total_strats += 1

    # =========================================================================
    # Step 5: Process Epics and link to STRATs/Initiatives
    # =========================================================================
    all_parent_keys = set(strat_keys_list + initiative_keys_list)
    epics_by_parent = {}
    epic_keys_list = []
    epic_keys_set = set()

    # Build "documented by" mapping from STRAT/initiative issuelinks
    documented_by_epics = {}
    for strat in strat_issues_raw:
        strat_key = strat['key']
        for link in strat.get('fields', {}).get('issuelinks', []):
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

    for initiative in initiative_issues_raw:
        init_key = initiative['key']
        for link in initiative.get('fields', {}).get('issuelinks', []):
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

    # Fetch any documented-by epics that aren't in our bulk results
    epic_keys_in_bulk = {e['key'] for e in epic_issues_raw}
    for epic_key in documented_by_epics:
        if epic_key not in epic_keys_in_bulk:
            try:
                epic_field_list = rhoaieng_fields
                epic_data = get_jira_issue(epic_key, fields=epic_field_list, jira_email=jira_email, jira_pat=jira_pat)
                if epic_data:
                    epic_issues_raw.append(epic_data)
                    print(f"  Added Epic {epic_key} via 'is documented by' link (not in bulk results)", file=sys.stderr)
            except Exception as e:
                print(f"  Warning: Failed to fetch Epic {epic_key}: {e}", file=sys.stderr)

    epic_issues_raw.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    for epic in epic_issues_raw:
        epic_data = build_issue_data(epic, 'epic')
        epic_key = epic_data['key']
        epic_keys_list.append(epic_key)
        epic_keys_set.add(epic_key)

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

        if epic_key in documented_by_epics:
            for parent_key in documented_by_epics[epic_key]:
                if parent_key not in linked_parent_keys:
                    linked_parent_keys.append(parent_key)

        if linked_parent_keys:
            for parent_key in linked_parent_keys:
                if parent_key not in epics_by_parent:
                    epics_by_parent[parent_key] = []
                epics_by_parent[parent_key].append(epic_data)

                if parent_key in strat_keys_list:
                    rfe_key = None
                    for r_key, strats in strats_by_rfe.items():
                        if any(s['key'] == parent_key for s in strats):
                            rfe_key = r_key
                            break
                    epic_outcome_keys = set()
                    if rfe_key:
                        for o_key, rfe_list in rfes_by_outcome.items():
                            if any(r['key'] == rfe_key for r in rfe_list):
                                epic_outcome_keys.add(o_key)
                    else:
                        for o_key, strat_list in strats_by_outcome.items():
                            if any(s['key'] == parent_key for s in strat_list):
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
            epic_data_copy = epic_data.copy()
            epic_data_copy['tasks'] = []
            epic_data_copy['orphan'] = True
            send_sse_event(wfile, 'epic', epic_data_copy)
            total_epics += 1

    # =========================================================================
    # Step 5b: Fetch tasks for epics regardless of component
    # =========================================================================
    existing_task_keys = {t['key'] for t in task_issues_raw}
    if epic_keys_set:
        epic_keys_for_query = list(epic_keys_set)
        batch_size = 50
        supplemental_queries = []
        for i in range(0, len(epic_keys_for_query), batch_size):
            batch = epic_keys_for_query[i:i + batch_size]
            epic_links = ', '.join(f'"{k}"' for k in batch)
            supp_jql = (
                f'project = RHOAIENG '
                f'AND ("Epic Link" in ({epic_links}) OR parent in ({epic_links})) '
                f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
                f'AND status NOT IN (Closed, Resolved) '
                f'AND updated >= {cutoff_date}'
            )
            supplemental_queries.append((supp_jql, rhoaieng_fields, 'SUPP_TASKS'))

        if supplemental_queries:
            supp_results = run_parallel_queries(supplemental_queries, jira_email, jira_pat, wfile)
            supp_tasks = supp_results.get('SUPP_TASKS', [])
            added = 0
            for task in supp_tasks:
                if task['key'] not in existing_task_keys:
                    if show_closed_tasks or not _is_closed(task):
                        task_issues_raw.append(task)
                        existing_task_keys.add(task['key'])
                        added += 1
            print(f"  Supplementary task fetch: {len(supp_tasks)} found, {added} new (not already in component results)", file=sys.stderr)

    # =========================================================================
    # Step 6: Process Tasks and link to Epics
    # =========================================================================
    tasks_by_epic = {}
    total_task_issues = len(task_issues_raw)

    task_issues_raw.sort(key=lambda x: x.get('fields', {}).get('updated', ''), reverse=True)

    for task in task_issues_raw:
        task_data = build_issue_data(task, 'task')
        task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')

        epic_link = task['fields'].get('customfield_10014')
        parent_field = task['fields'].get('parent')
        parent_key = parent_field.get('key') if parent_field and isinstance(parent_field, dict) else None
        if not epic_link and parent_key and parent_key in epic_keys_set:
            epic_link = parent_key

        if epic_link and epic_link in epic_keys_set:
            if epic_link not in tasks_by_epic:
                tasks_by_epic[epic_link] = []
            tasks_by_epic[epic_link].append(task_data)

            task_data['epic_key'] = epic_link

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
                        else:
                            for o_key, strat_list in strats_by_outcome.items():
                                if any(s['key'] == parent_key for s in strat_list):
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
            if epic_link:
                task_data['epic_key'] = epic_link
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
    print(f"  Outcomes:     {total_outcomes} (fetched {len(outcome_issues_raw)})", file=sys.stderr)
    print(f"  RFEs:         {total_rfes} (fetched {len(rfe_issues_raw)})", file=sys.stderr)
    print(f"  Initiatives:  {total_initiatives} (fetched {len(initiative_issues_raw)})", file=sys.stderr)
    print(f"  STRATs:       {total_strats} (fetched {len(strat_issues_raw)})", file=sys.stderr)
    print(f"  Epics:        {total_epics} (fetched {len(epic_issues_raw)})", file=sys.stderr)
    print(f"  Tasks:        {total_tasks} (fetched {total_task_issues}, in hierarchy: {tasks_in_hierarchy}, outside: {tasks_outside_hierarchy})", file=sys.stderr)
