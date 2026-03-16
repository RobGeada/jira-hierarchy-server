"""JIRA REST API client"""

import base64
import requests
from .config import JIRA_BASE_URL, get_jira_pat, get_jira_email


def _get_auth_header(jira_email=None, jira_pat=None):
    """
    Create Basic auth header for JIRA Cloud API

    Args:
        jira_email: User email address
        jira_pat: API token

    Returns:
        Authorization header value
    """
    email = get_jira_email(jira_email)
    pat = get_jira_pat(jira_pat)

    # Create Basic auth: base64(email:token)
    auth_string = f"{email}:{pat}"
    encoded = base64.b64encode(auth_string.encode()).decode()
    return f'Basic {encoded}'


def run_jira_query(jql, fields="summary,status,priority,assignee,description", jira_email=None, jira_pat=None, wfile=None, progress_message_prefix="Loading"):
    """
    Run a JQL query using the JIRA REST API with Basic Authentication
    Handles pagination to fetch all results

    Args:
        jql: JQL query string
        fields: Comma-separated list of fields to retrieve
        jira_email: User email address (optional, falls back to env)
        jira_pat: API token (optional, falls back to env)
        wfile: Optional write file for sending SSE progress events
        progress_message_prefix: Prefix for progress messages (e.g., "Loading Tasks")

    Returns:
        List of JIRA issues
    """
    import sys
    import json

    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Accept': 'application/json'
    }

    all_issues = []
    max_results = 100  # Fetch 100 at a time (JIRA Cloud typical limit)
    page_num = 1
    max_pages = 100  # Safety limit: stop after 100 pages (10,000 issues)
    first_key = None
    next_page_token = None

    while page_num <= max_pages:
        params = {
            'jql': jql,
            'fields': fields,
            'maxResults': max_results
        }

        # Use nextPageToken for pagination (JIRA Cloud pagination token)
        if next_page_token:
            params['nextPageToken'] = next_page_token

        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            raise ValueError(
                f"JIRA API error: {response.status_code}\n"
                f"URL: {url}\n"
                f"Response: {response.text[:500]}"
            )

        result = response.json()
        issues = result.get('issues', [])

        # Stop if we got no issues
        if len(issues) == 0:
            break

        # Check for duplicates (might indicate pagination issue)
        if page_num == 1 and issues:
            first_key = issues[0]['key']
        elif page_num == 2 and issues and first_key:
            second_page_first_key = issues[0]['key']
            if first_key == second_page_first_key:
                print(f"WARNING: Pagination not working! Page 2 starts with same issue as page 1: {first_key}", file=sys.stderr)
                break

        all_issues.extend(issues)

        # Send progress event if wfile is provided (only log errors)
        if wfile:
            try:
                event = f"event: progress\ndata: {json.dumps({'message': f'{progress_message_prefix}... ({len(all_issues)} fetched)'})}\n\n"
                wfile.write(event.encode())
                wfile.flush()
            except Exception as e:
                print(f"Warning: Failed to send progress event: {e}", file=sys.stderr)

        # Get next page token for pagination
        next_page_token = result.get('nextPageToken')
        page_num += 1

        # If no next page token, we've reached the end
        if not next_page_token:
            break

    if page_num > max_pages:
        print(f"WARNING: Hit pagination safety limit ({max_pages} pages). There may be more results.", file=sys.stderr)

    print(f"Pagination complete: {len(all_issues)} total issues fetched", file=sys.stderr)
    return all_issues


def create_jira_issue(project_key, summary, description, issue_type, custom_fields=None, jira_email=None, jira_pat=None):
    """
    Create a new JIRA issue

    Args:
        project_key: JIRA project key
        summary: Issue summary
        description: Issue description
        issue_type: Issue type (Epic, Story, etc.)
        custom_fields: Dict of custom field values
        jira_email: User email address
        jira_pat: API token

    Returns:
        Created issue key
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
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

    create_url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    response = requests.post(create_url, headers=headers, json=payload)

    if response.status_code != 201:
        raise Exception(f"Failed to create issue: {response.status_code} - {response.text}")

    return response.json()['key']


def get_jira_issue(issue_key, fields="summary,status,priority,assignee", jira_email=None, jira_pat=None):
    """
    Get JIRA issue details

    Args:
        issue_key: JIRA issue key
        fields: Comma-separated list of fields
        jira_email: User email address
        jira_pat: API token

    Returns:
        Issue data dict
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Accept': 'application/json'
    }

    get_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}?fields={fields}"
    response = requests.get(get_url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch issue: {response.status_code}")

    return response.json()


def add_jira_comment(issue_key, comment, jira_email=None, jira_pat=None):
    """
    Add a comment to a JIRA issue

    Args:
        issue_key: JIRA issue key
        comment: Comment text
        jira_email: User email address
        jira_pat: API token
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Content-Type': 'application/json'
    }

    comment_payload = {"body": comment}
    comment_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    response = requests.post(comment_url, headers=headers, json=comment_payload)

    if response.status_code != 201:
        raise Exception(f"Failed to add comment: {response.status_code} - {response.text}")

    return True


def update_jira_labels(issue_key, action, label, jira_email=None, jira_pat=None):
    """
    Add or remove a label from a JIRA issue

    Args:
        issue_key: JIRA issue key
        action: 'add' or 'remove'
        label: Label text
        jira_email: User email address
        jira_pat: API token

    Returns:
        Updated list of labels
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Content-Type': 'application/json'
    }

    # First, get current labels
    issue_data = get_jira_issue(issue_key, 'labels', jira_email, jira_pat)
    current_labels = issue_data['fields'].get('labels', [])

    # Update labels list
    if action == 'add':
        if label not in current_labels:
            current_labels.append(label)
    elif action == 'remove':
        if label in current_labels:
            current_labels.remove(label)

    # Update issue with new labels
    update_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    payload = {"fields": {"labels": current_labels}}
    response = requests.put(update_url, headers=headers, json=payload)

    if response.status_code != 204:
        raise Exception(f"Failed to update labels: {response.status_code} - {response.text}")

    return current_labels


def update_jira_issue(issue_key, fields, jira_email=None, jira_pat=None):
    """
    Update fields on a JIRA issue

    Args:
        issue_key: JIRA issue key
        fields: Dictionary of fields to update
        jira_email: User email address
        jira_pat: API token

    Returns:
        True if successful
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Content-Type': 'application/json'
    }

    update_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    payload = {"fields": fields}
    response = requests.put(update_url, headers=headers, json=payload)

    if response.status_code != 204:
        raise Exception(f"Failed to update issue: {response.status_code} - {response.text}")

    return True


def get_jira_transitions(issue_key, jira_email=None, jira_pat=None):
    """
    Get available status transitions for a JIRA issue

    Args:
        issue_key: JIRA issue key
        jira_email: User email address
        jira_pat: API token

    Returns:
        List of available transitions
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Accept': 'application/json'
    }

    transitions_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    response = requests.get(transitions_url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to get transitions: {response.status_code} - {response.text}")

    data = response.json()
    return [{"id": t["id"], "name": t["name"]} for t in data.get("transitions", [])]


def transition_jira_issue(issue_key, transition_id, jira_email=None, jira_pat=None):
    """
    Transition a JIRA issue to a new status

    Args:
        issue_key: JIRA issue key
        transition_id: ID of the transition to perform
        jira_email: User email address
        jira_pat: API token
    """
    headers = {
        'Authorization': _get_auth_header(jira_email, jira_pat),
        'Content-Type': 'application/json'
    }

    transition_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    payload = {"transition": {"id": transition_id}}
    response = requests.post(transition_url, headers=headers, json=payload)

    if response.status_code != 204:
        raise Exception(f"Failed to transition issue: {response.status_code} - {response.text}")

    return True
