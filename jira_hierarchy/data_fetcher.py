"""Data fetching and hierarchy building logic"""

import sys
from .jira_client import run_jira_query, create_jira_issue, get_jira_issue


def build_issue_data(issue, issue_type='rfe'):
    """
    Build standardized issue data dict from JIRA response

    Args:
        issue: JIRA issue dict from API
        issue_type: Type of issue for logging

    Returns:
        Standardized issue data dict
    """
    fields = issue['fields']
    assignee = fields.get('assignee')
    reporter = fields.get('reporter')

    return {
        "key": issue['key'],
        "summary": fields.get('summary', 'No summary'),
        "status": fields.get('status', {}).get('name', 'Unknown'),
        "priority": fields.get('priority', {}).get('name', 'Undefined'),
        "assignee": assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned',
        "assignee_username": assignee.get('name') if assignee else None,
        "reporter": reporter.get('displayName', 'Unknown') if reporter else 'Unknown',
        "description": fields.get('description', ''),
        "labels": fields.get('labels', []),
        "components": [c.get('name', '') for c in fields.get('components', [])],
        "comments": [
            {
                "body": c.get('body', ''),
                "author": c.get('author', {}).get('displayName', 'Unknown'),
                "created": c.get('created', '')
            }
            for c in fields.get('comment', {}).get('comments', [])
        ],
        "created": fields.get('created', ''),
        "updated": fields.get('updated', ''),
    }


def fetch_rfes(component, jira_pat):
    """
    Fetch RFEs for a given component

    Args:
        component: Component name to filter by
        jira_pat: Personal Access Token

    Returns:
        List of RFE issue dicts
    """
    rfes_jql = (
        f'project = RHAIRFE '
        f'AND issuetype = "Feature Request" '
        f'AND component = "{component}" '
        f'AND status NOT IN (Closed, Resolved) '
        f'ORDER BY priority DESC, created DESC'
    )

    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components'
    rfe_issues = run_jira_query(rfes_jql, field_list, jira_pat)

    return [build_issue_data(rfe, 'rfe') for rfe in rfe_issues]


def fetch_strats_for_rfe(rfe_key, jira_pat):
    """
    Fetch STRATs linked to an RFE (all issue types in RHAISTRAT project)

    Args:
        rfe_key: RFE issue key
        jira_pat: Personal Access Token

    Returns:
        List of STRAT issue dicts
    """
    strats_jql = (
        f'project = RHAISTRAT '
        f'AND (issueFunction in linkedIssuesOf("key = {rfe_key}", "is cloned by") '
        f'OR issueFunction in linkedIssuesOf("key = {rfe_key}", "clones")) '
        f'AND status NOT IN (Closed, Resolved)'
    )

    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components'
    strat_issues = run_jira_query(strats_jql, field_list, jira_pat)

    return [build_issue_data(strat, 'strat') for strat in strat_issues]


def fetch_epics_for_strat(strat_key, jira_pat):
    """
    Fetch Epics linked to a STRAT

    Args:
        strat_key: STRAT issue key
        jira_pat: Personal Access Token

    Returns:
        List of Epic issue dicts
    """
    # Query by Parent Link custom field since Epics link to STRATs via customfield_12313140
    epics_jql = (
        f'project = RHOAIENG '
        f'AND issuetype = Epic '
        f'AND "Parent Link" = {strat_key} '
        f'AND status NOT IN (Closed, Resolved)'
    )

    # Include customfield_12313140 (Parent Link) in the field list
    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components,customfield_12313140'
    epic_issues = run_jira_query(epics_jql, field_list, jira_pat)

    return [build_issue_data(epic, 'epic') for epic in epic_issues]


def fetch_tasks_for_epic(epic_key, jira_pat):
    """
    Fetch Tasks linked to an Epic

    Args:
        epic_key: Epic issue key
        jira_pat: Personal Access Token

    Returns:
        List of Task issue dicts
    """
    tasks_jql = (
        f'"Epic Link" = {epic_key} '
        f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
        f'AND status NOT IN (Closed, Resolved)'
    )

    # Include customfield_12311140 (Epic Link) in the field list
    field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components,customfield_12311140'

    try:
        task_issues = run_jira_query(tasks_jql, field_list, jira_pat)
        tasks = []
        for task in task_issues:
            task_data = build_issue_data(task, 'task')
            task_data['issuetype'] = task['fields'].get('issuetype', {}).get('name', 'Task')
            tasks.append(task_data)
        return tasks
    except Exception as e:
        print(f"Error fetching tasks for {epic_key}: {e}", file=sys.stderr)
        return []


def create_epic(summary, description, strat_key, component=None, assignee=None, jira_pat=None):
    """
    Create a new Epic and link it to a STRAT

    Args:
        summary: Epic summary
        description: Epic description
        strat_key: Parent STRAT key
        component: Component name to assign
        assignee: Assignee email or username
        jira_pat: Personal Access Token

    Returns:
        Epic data dict
    """
    custom_fields = {
        "customfield_12311141": summary,  # Epic Name
        "customfield_12313140": strat_key  # Parent Link to STRAT
    }

    # Add component if provided
    if component:
        custom_fields["components"] = [{"name": component}]

    # Add assignee if provided
    if assignee:
        custom_fields["assignee"] = {"name": assignee}

    epic_key = create_jira_issue(
        project_key="RHOAIENG",
        summary=summary,
        description=description,
        issue_type="Epic",
        custom_fields=custom_fields,
        jira_pat=jira_pat
    )

    print(f"Created epic {epic_key} linked to STRAT {strat_key}", file=sys.stderr)

    # Fetch and return full issue data
    issue_data = get_jira_issue(epic_key, 'summary,status,priority,assignee,reporter,description,labels,components,created,updated', jira_pat)
    epic_data = build_issue_data(issue_data, 'epic')
    epic_data['strat_key'] = strat_key

    return epic_data


def create_task(summary, description, epic_key, issue_type, component=None, assignee=None, jira_pat=None):
    """
    Create a new Task and link it to an Epic

    Args:
        summary: Task summary
        description: Task description
        epic_key: Parent Epic key
        issue_type: Issue type (Story, Spike, etc.)
        component: Component name to assign
        assignee: Assignee email or username
        jira_pat: Personal Access Token

    Returns:
        Task data dict
    """
    custom_fields = {
        "customfield_12311140": epic_key  # Epic Link
    }

    # Add component if provided
    if component:
        custom_fields["components"] = [{"name": component}]

    # Add assignee if provided
    if assignee:
        custom_fields["assignee"] = {"name": assignee}

    task_key = create_jira_issue(
        project_key="RHOAIENG",
        summary=summary,
        description=description,
        issue_type=issue_type,
        custom_fields=custom_fields,
        jira_pat=jira_pat
    )

    print(f"Created task {task_key} under epic {epic_key}", file=sys.stderr)

    # Fetch and return full issue data
    issue_data = get_jira_issue(task_key, 'summary,status,priority,assignee,reporter,description,labels,components,created,updated,issuetype', jira_pat)
    task_data = build_issue_data(issue_data, 'task')
    task_data['epic_key'] = epic_key
    task_data['issuetype'] = issue_data['fields'].get('issuetype', {}).get('name', 'Task')

    return task_data
