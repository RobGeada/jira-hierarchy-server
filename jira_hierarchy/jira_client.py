"""JIRA REST API client"""

import requests
from .config import JIRA_BASE_URL, get_jira_pat


def run_jira_query(jql, fields="summary,status,priority,assignee,description", jira_pat=None):
    """
    Run a JQL query using the JIRA REST API with Personal Access Token

    Args:
        jql: JQL query string
        fields: Comma-separated list of fields to retrieve
        jira_pat: Personal Access Token (optional, falls back to env)

    Returns:
        List of JIRA issues
    """
    pat = get_jira_pat(jira_pat)

    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    params = {
        'jql': jql,
        'fields': fields,
        'maxResults': 100
    }

    headers = {
        'Authorization': f'Bearer {pat}',
        'Accept': 'application/json'
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        raise ValueError(
            f"JIRA API error: {response.status_code}\n"
            f"URL: {url}\n"
            f"Response: {response.text[:500]}"
        )

    return response.json()['issues']


def create_jira_issue(project_key, summary, description, issue_type, custom_fields=None, jira_pat=None):
    """
    Create a new JIRA issue

    Args:
        project_key: JIRA project key
        summary: Issue summary
        description: Issue description
        issue_type: Issue type (Epic, Story, etc.)
        custom_fields: Dict of custom field values
        jira_pat: Personal Access Token

    Returns:
        Created issue key
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Content-Type': 'application/json'
    }

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type}
        }
    }

    # Add custom fields if provided
    if custom_fields:
        payload["fields"].update(custom_fields)

    create_url = f"{JIRA_BASE_URL}/rest/api/2/issue"
    response = requests.post(create_url, headers=headers, json=payload)

    if response.status_code != 201:
        raise Exception(f"Failed to create issue: {response.status_code} - {response.text}")

    return response.json()['key']


def get_jira_issue(issue_key, fields="summary,status,priority,assignee", jira_pat=None):
    """
    Get JIRA issue details

    Args:
        issue_key: JIRA issue key
        fields: Comma-separated list of fields
        jira_pat: Personal Access Token

    Returns:
        Issue data dict
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Accept': 'application/json'
    }

    get_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}?fields={fields}"
    response = requests.get(get_url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch issue: {response.status_code}")

    return response.json()


def add_jira_comment(issue_key, comment, jira_pat=None):
    """
    Add a comment to a JIRA issue

    Args:
        issue_key: JIRA issue key
        comment: Comment text
        jira_pat: Personal Access Token
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Content-Type': 'application/json'
    }

    comment_payload = {"body": comment}
    comment_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/comment"
    response = requests.post(comment_url, headers=headers, json=comment_payload)

    if response.status_code != 201:
        raise Exception(f"Failed to add comment: {response.status_code} - {response.text}")

    return True


def update_jira_labels(issue_key, action, label, jira_pat=None):
    """
    Add or remove a label from a JIRA issue

    Args:
        issue_key: JIRA issue key
        action: 'add' or 'remove'
        label: Label text
        jira_pat: Personal Access Token

    Returns:
        Updated list of labels
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Content-Type': 'application/json'
    }

    # First, get current labels
    issue_data = get_jira_issue(issue_key, 'labels', jira_pat)
    current_labels = issue_data['fields'].get('labels', [])

    # Update labels list
    if action == 'add':
        if label not in current_labels:
            current_labels.append(label)
    elif action == 'remove':
        if label in current_labels:
            current_labels.remove(label)

    # Update issue with new labels
    update_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}"
    payload = {"fields": {"labels": current_labels}}
    response = requests.put(update_url, headers=headers, json=payload)

    if response.status_code != 204:
        raise Exception(f"Failed to update labels: {response.status_code} - {response.text}")

    return current_labels


def update_jira_issue(issue_key, fields, jira_pat=None):
    """
    Update fields on a JIRA issue

    Args:
        issue_key: JIRA issue key
        fields: Dictionary of fields to update
        jira_pat: Personal Access Token

    Returns:
        True if successful
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Content-Type': 'application/json'
    }

    update_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}"
    payload = {"fields": fields}
    response = requests.put(update_url, headers=headers, json=payload)

    if response.status_code != 204:
        raise Exception(f"Failed to update issue: {response.status_code} - {response.text}")

    return True


def get_jira_transitions(issue_key, jira_pat=None):
    """
    Get available status transitions for a JIRA issue

    Args:
        issue_key: JIRA issue key
        jira_pat: Personal Access Token

    Returns:
        List of available transitions
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Accept': 'application/json'
    }

    transitions_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/transitions"
    response = requests.get(transitions_url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to get transitions: {response.status_code} - {response.text}")

    data = response.json()
    return [{"id": t["id"], "name": t["name"]} for t in data.get("transitions", [])]


def transition_jira_issue(issue_key, transition_id, jira_pat=None):
    """
    Transition a JIRA issue to a new status

    Args:
        issue_key: JIRA issue key
        transition_id: ID of the transition to perform
        jira_pat: Personal Access Token
    """
    pat = get_jira_pat(jira_pat)

    headers = {
        'Authorization': f'Bearer {pat}',
        'Content-Type': 'application/json'
    }

    transition_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/transitions"
    payload = {"transition": {"id": transition_id}}
    response = requests.post(transition_url, headers=headers, json=payload)

    if response.status_code != 204:
        raise Exception(f"Failed to transition issue: {response.status_code} - {response.text}")

    return True
