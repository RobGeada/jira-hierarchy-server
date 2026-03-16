"""HTTP server and request handlers"""

import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .config import JIRA_BASE_URL, SERVER_HOST, SERVER_PORT
from .sse import stream_hierarchy
from .data_fetcher import create_epic, create_task
from .jira_client import (
    add_jira_comment,
    update_jira_labels,
    get_jira_transitions,
    transition_jira_issue
)


class JIRAHierarchyHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves the hierarchy viewer and fetches JIRA data"""

    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/':
            self.serve_viewer()
        elif parsed_path.path == '/api/hierarchy/stream':
            self.serve_hierarchy_stream()
        elif parsed_path.path == '/api/fetch-assignees':
            self.fetch_assignees()
        elif parsed_path.path == '/api/transitions':
            self.get_transitions()
        elif parsed_path.path == '/api/reload-item':
            self.reload_item()
        elif parsed_path.path == '/api/strats-by-assignee':
            self.get_strats_by_assignee()
        elif parsed_path.path == '/api/validate-components':
            self.validate_components()
        elif parsed_path.path == '/health':
            self.send_json({'status': 'ok'})
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/api/create-epic':
            self.handle_create_epic()
        elif parsed_path.path == '/api/create-task':
            self.handle_create_task()
        elif parsed_path.path == '/api/add-comment':
            self.handle_add_comment()
        elif parsed_path.path == '/api/update-labels':
            self.handle_update_labels()
        elif parsed_path.path == '/api/transition':
            self.handle_transition()
        elif parsed_path.path == '/api/update-priority':
            self.handle_update_priority()
        elif parsed_path.path == '/api/update-assignee':
            self.handle_update_assignee()
        elif parsed_path.path == '/api/update-description':
            self.handle_update_description()
        elif parsed_path.path == '/api/batch-add-comments':
            self.handle_batch_add_comments()
        else:
            self.send_error(404, 'Not Found')

    def handle_create_epic(self):
        """Create a new epic and link it to a STRAT"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            strat_key = data.get('strat_key')
            summary = data.get('summary')
            component = data.get('component')
            assignee = data.get('assignee')
            description = data.get('description', '')

            if not strat_key or not summary:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            epic_data = create_epic(summary, description, strat_key, component, assignee, email, pat)
            self.send_json({'success': True, 'epic': epic_data})

        except Exception as e:
            print(f"Error creating epic: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_create_task(self):
        """Create a new task and link it to an epic"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            epic_key = data.get('epic_key')
            summary = data.get('summary')
            component = data.get('component')
            assignee = data.get('assignee')
            description = data.get('description', '')
            issue_type = data.get('issue_type', 'Story')

            if not epic_key or not summary:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            task_data = create_task(summary, description, epic_key, issue_type, component, assignee, email, pat)
            self.send_json({'success': True, 'task': task_data})

        except Exception as e:
            print(f"Error creating task: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_add_comment(self):
        """Add a comment to a JIRA issue"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            issue_key = data.get('issue_key')
            comment = data.get('comment')

            if not issue_key or not comment:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            add_jira_comment(issue_key, comment, email, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error adding comment: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_batch_add_comments(self):
        """Add comments to multiple JIRA issues"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            comments_data = data.get('comments', [])  # List of {issue_key, comment}

            if not comments_data:
                self.send_json({'error': 'No comments provided'}, status=400)
                return

            results = []
            for item in comments_data:
                issue_key = item.get('issue_key')
                comment = item.get('comment')

                if not issue_key or not comment:
                    results.append({'issue_key': issue_key, 'success': False, 'error': 'Missing fields'})
                    continue

                try:
                    add_jira_comment(issue_key, comment, email, pat)
                    results.append({'issue_key': issue_key, 'success': True})
                except Exception as e:
                    results.append({'issue_key': issue_key, 'success': False, 'error': str(e)})

            self.send_json({'success': True, 'results': results})

        except Exception as e:
            print(f"Error batch adding comments: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_labels(self):
        """Add or remove a label from a JIRA issue"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            issue_key = data.get('issue_key')
            action = data.get('action')  # 'add' or 'remove'
            label = data.get('label')

            if not issue_key or not action or not label:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            updated_labels = update_jira_labels(issue_key, action, label, email, pat)
            self.send_json({'success': True, 'labels': updated_labels})

        except Exception as e:
            print(f"Error updating labels: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def get_transitions(self):
        """Get available status transitions for a JIRA issue"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            issue_key = params.get('issue_key', [None])[0]
            email = params.get('email', [None])[0]
            pat = params.get('pat', [None])[0]

            if not issue_key:
                self.send_json({'error': 'Missing issue_key parameter'}, status=400)
                return

            transitions = get_jira_transitions(issue_key, email, pat)
            self.send_json({'success': True, 'transitions': transitions})

        except Exception as e:
            print(f"Error getting transitions: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_transition(self):
        """Transition a JIRA issue to a new status"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            issue_key = data.get('issue_key')
            transition_id = data.get('transition_id')

            if not issue_key or not transition_id:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            transition_jira_issue(issue_key, transition_id, email, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error transitioning issue: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_priority(self):
        """Update the priority of a JIRA issue"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            issue_key = data.get('issue_key')
            priority = data.get('priority')

            if not issue_key or not priority:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            from .jira_client import update_jira_issue
            update_jira_issue(issue_key, {'priority': {'name': priority}}, email, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error updating priority: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_assignee(self):
        """Update the assignee of a JIRA issue"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            issue_key = data.get('issue_key')
            assignee = data.get('assignee', '')

            if not issue_key:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            from .jira_client import update_jira_issue
            # If assignee is empty, set to null to unassign
            if assignee:
                update_jira_issue(issue_key, {'assignee': {'name': assignee}}, email, pat)
            else:
                update_jira_issue(issue_key, {'assignee': None}, email, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error updating assignee: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_description(self):
        """Update the description of a JIRA issue"""
        try:
            data = self.read_json_body()

            email = data.get('email')
            pat = data.get('pat')
            issue_key = data.get('issue_key')
            description = data.get('description', '')

            if not issue_key:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            from .jira_client import update_jira_issue
            update_jira_issue(issue_key, {'description': description}, email, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error updating description: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def reload_item(self):
        """Reload a single item and its children"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            issue_key = params.get('issue_key', [None])[0]
            item_type = params.get('item_type', [None])[0]
            email = params.get('email', [None])[0]
            pat = params.get('pat', [None])[0]
            component = params.get('component', ['AI Safety'])[0]

            if not issue_key or not item_type:
                self.send_json({'error': 'Missing required parameters'}, status=400)
                return

            # Import reload functions
            from .data_fetcher import (
                fetch_rfes,
                fetch_strats_for_rfe,
                fetch_epics_for_strat,
                fetch_tasks_for_epic,
                build_issue_data
            )
            from .jira_client import run_jira_query

            # Fetch the item and its children based on type
            if item_type == 'rfe':
                # Fetch this specific RFE
                rfes = fetch_rfes(component, email, pat)
                rfe = next((r for r in rfes if r['key'] == issue_key), None)
                if not rfe:
                    self.send_json({'error': 'RFE not found'}, status=404)
                    return

                # Fetch its children
                rfe['strats'] = []
                strats = fetch_strats_for_rfe(issue_key, email, pat)
                for strat_data in strats:
                    strat_data['rfe_key'] = issue_key
                    strat_data['epics'] = []

                    epics = fetch_epics_for_strat(strat_data['key'], email, pat)
                    for epic_data in epics:
                        epic_data['rfe_key'] = issue_key
                        epic_data['strat_key'] = strat_data['key']
                        epic_data['tasks'] = fetch_tasks_for_epic(epic_data['key'], email, pat)
                        for task in epic_data['tasks']:
                            task['rfe_key'] = issue_key
                            task['strat_key'] = strat_data['key']
                            task['epic_key'] = epic_data['key']
                        strat_data['epics'].append(epic_data)

                    rfe['strats'].append(strat_data)

                self.send_json({'success': True, 'data': rfe})

            elif item_type == 'strat':
                # Fetch this specific STRAT
                jql = f'key = {issue_key}'
                field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components'
                strat_issues = run_jira_query(jql, field_list, email, pat)
                if not strat_issues:
                    self.send_json({'error': 'STRAT not found'}, status=404)
                    return

                strat_data = build_issue_data(strat_issues[0], 'strat')
                strat_data['epics'] = []

                epics = fetch_epics_for_strat(issue_key, email, pat)
                for epic_data in epics:
                    epic_data['strat_key'] = issue_key
                    epic_data['tasks'] = fetch_tasks_for_epic(epic_data['key'], email, pat)
                    for task in epic_data['tasks']:
                        task['strat_key'] = issue_key
                        task['epic_key'] = epic_data['key']
                    strat_data['epics'].append(epic_data)

                self.send_json({'success': True, 'data': strat_data})

            elif item_type == 'epic':
                # Fetch this specific Epic
                jql = f'key = {issue_key}'
                field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components'
                epic_issues = run_jira_query(jql, field_list, email, pat)
                if not epic_issues:
                    self.send_json({'error': 'Epic not found'}, status=404)
                    return

                epic_data = build_issue_data(epic_issues[0], 'epic')
                epic_data['tasks'] = fetch_tasks_for_epic(issue_key, email, pat)
                for task in epic_data['tasks']:
                    task['epic_key'] = issue_key

                self.send_json({'success': True, 'data': epic_data})

            elif item_type == 'task':
                # Fetch this specific Task
                jql = f'key = {issue_key}'
                field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components'
                task_issues = run_jira_query(jql, field_list, email, pat)
                if not task_issues:
                    self.send_json({'error': 'Task not found'}, status=404)
                    return

                task_data = build_issue_data(task_issues[0], 'task')
                task_data['issuetype'] = task_issues[0]['fields'].get('issuetype', {}).get('name', 'Task')

                self.send_json({'success': True, 'data': task_data})

            else:
                self.send_json({'error': 'Invalid item type'}, status=400)

        except Exception as e:
            print(f"Error reloading item: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def get_strats_by_assignee(self):
        """Fetch all STRATs assigned to a specific user"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            assignee = params.get('assignee', [None])[0]
            email = params.get('email', [None])[0]
            pat = params.get('pat', [None])[0]
            component = params.get('component', [None])[0]

            if not assignee:
                self.send_json({'error': 'Missing assignee parameter'}, status=400)
                return

            from .jira_client import run_jira_query
            from .data_fetcher import build_issue_data

            # Build JQL query for STRATs assigned to this user
            jql_parts = [
                f'project = RHAISTRAT',
                f'AND assignee = "{assignee}"',
                f'AND status NOT IN (Closed, Resolved)'
            ]

            if component:
                jql_parts.append(f'AND component = "{component}"')

            jql_parts.append('ORDER BY priority DESC, created DESC')

            strats_jql = ' '.join(jql_parts)

            field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components'
            strat_issues = run_jira_query(strats_jql, field_list, email, pat)

            strats = [build_issue_data(strat, 'strat') for strat in strat_issues]

            self.send_json({'success': True, 'strats': strats})

        except Exception as e:
            print(f"Error fetching STRATs by assignee: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def validate_components(self):
        """Validate that components exist in JIRA"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            components_str = params.get('components', [None])[0]
            email = params.get('email', [None])[0]
            pat = params.get('pat', [None])[0]

            if not components_str:
                self.send_json({'error': 'Missing components parameter'}, status=400)
                return

            # Always use the supplied credentials for validation, not saved ones
            if not email or not pat:
                self.send_json({'error': 'Email and API Token must be provided for validation'}, status=400)
                return

            # Split components and validate each one
            components = [c.strip() for c in components_str.split(',')]

            import requests
            import base64
            from .config import JIRA_BASE_URL

            # Create auth header
            auth_string = f"{email}:{pat}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            headers = {
                'Authorization': f'Basic {encoded}',
                'Accept': 'application/json'
            }

            # Get components directly from project API (much faster than querying all issues)
            all_components = set()

            # Get components from RHAIRFE project
            try:
                url = f"{JIRA_BASE_URL}/rest/api/3/project/RHAIRFE/components"
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    rfe_comps = response.json()
                    for comp in rfe_comps:
                        all_components.add(comp.get('name'))
                else:
                    print(f"Warning: Could not fetch RFE components: {response.status_code}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not fetch RFE components: {e}", file=sys.stderr)

            # Get components from RHAISTRAT project
            try:
                url = f"{JIRA_BASE_URL}/rest/api/3/project/RHAISTRAT/components"
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    strat_comps = response.json()
                    for comp in strat_comps:
                        all_components.add(comp.get('name'))
                else:
                    print(f"Warning: Could not fetch STRAT components: {response.status_code}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not fetch STRAT components: {e}", file=sys.stderr)

            # Get components from RHOAIENG project (for tasks)
            try:
                url = f"{JIRA_BASE_URL}/rest/api/3/project/RHOAIENG/components"
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    eng_comps = response.json()
                    for comp in eng_comps:
                        all_components.add(comp.get('name'))
                else:
                    print(f"Warning: Could not fetch RHOAIENG components: {response.status_code}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not fetch RHOAIENG components: {e}", file=sys.stderr)

            # Check each requested component
            invalid_components = []
            for component in components:
                if component not in all_components:
                    invalid_components.append(component)

            if invalid_components:
                self.send_json({
                    'valid': False,
                    'invalid_components': invalid_components,
                    'available_components': sorted(list(all_components))
                })
            else:
                self.send_json({
                    'valid': True,
                    'components': components
                })

        except Exception as e:
            print(f"Error validating components: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def fetch_assignees(self):
        """Fetch all unique assignees from tasks without assignee filter"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            email = params.get('email', [None])[0]
            pat = params.get('pat', [None])[0]
            component = params.get('component', ['AI Safety'])[0]
            max_age_days = int(params.get('max_age_days', ['365'])[0])

            if not email:
                email = os.getenv('JIRA_EMAIL')
            if not pat:
                pat = os.getenv('JIRA_PAT')

            if not email or not pat:
                self.send_json({'error': 'Email and API Token not provided'}, status=400)
                return

            from datetime import timedelta
            from .jira_client import run_jira_query

            # Calculate cutoff date
            cutoff_date = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')

            # Build component filter
            components = [c.strip() for c in component.split(',')]
            if len(components) > 1:
                component_list = ', '.join([f'"{c}"' for c in components])
                component_clause = f'component IN ({component_list})'
            else:
                component_clause = f'component = "{components[0]}"'

            # Fetch ALL tasks for the component (no assignee filter)
            tasks_jql = (
                f'project = RHOAIENG '
                f'AND {component_clause} '
                f'AND issuetype NOT IN (Epic, Feature, "Feature Request") '
                f'AND created >= {cutoff_date} '
                f'AND status NOT IN (Closed, Resolved)'
            )

            task_issues = run_jira_query(tasks_jql, 'assignee', email, pat)

            # Extract unique assignees
            assignees = {}
            for task in task_issues:
                assignee = task.get('fields', {}).get('assignee')
                if assignee:
                    account_id = assignee.get('accountId')
                    display_name = assignee.get('displayName', 'Unknown')
                    if account_id:
                        assignees[account_id] = display_name

            # Convert to list format
            assignee_list = [
                {'username': account_id, 'displayName': display_name}
                for account_id, display_name in assignees.items()
            ]

            self.send_json({'assignees': assignee_list})

        except Exception as e:
            print(f"Error fetching assignees: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def serve_viewer(self):
        """Serve the HTML viewer page"""
        # Look for HTML in static/ directory
        html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'jira-hierarchy-viewer.html')

        # Fallback to old location
        if not os.path.exists(html_path):
            html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'jira-hierarchy-viewer.html')

        if not os.path.exists(html_path):
            self.send_error(404, 'Viewer HTML not found')
            return

        with open(html_path, 'r') as f:
            html_content = f.read()

        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html_content.encode())

    def serve_hierarchy_stream(self):
        """Stream hierarchy data as it's being fetched using Server-Sent Events"""
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)

        email = params.get('email', [None])[0]
        pat = params.get('pat', [None])[0]
        component = params.get('component', ['AI Safety'])[0]
        top_level = params.get('top_level', ['rfe'])[0]
        max_age_days = int(params.get('max_age_days', ['365'])[0])
        show_closed_rfes = params.get('show_closed_rfes', ['false'])[0].lower() == 'true'
        show_closed_strats = params.get('show_closed_strats', ['false'])[0].lower() == 'true'
        show_closed_epics = params.get('show_closed_epics', ['false'])[0].lower() == 'true'
        show_closed_tasks = params.get('show_closed_tasks', ['false'])[0].lower() == 'true'

        # Extract assignees filter (comma-separated list of account IDs)
        assignees_param = params.get('assignees', [None])[0]
        assignees = assignees_param.split(',') if assignees_param else None

        if not email:
            email = os.getenv('JIRA_EMAIL')
        if not pat:
            pat = os.getenv('JIRA_PAT')

        if not email:
            self.send_json({'error': 'JIRA Email not provided'}, status=400)
            return
        if not pat:
            self.send_json({'error': 'API Token not provided'}, status=400)
            return

        self.send_response(200)
        self.send_header('Content-type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        try:
            stream_hierarchy(self.wfile, email, pat, component, top_level,
                           show_closed_rfes, show_closed_strats,
                           show_closed_epics, show_closed_tasks, max_age_days, assignees)
        except Exception as e:
            print(f"Error streaming hierarchy: {e}", file=sys.stderr)
            traceback.print_exc()
            error_event = f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            self.wfile.write(error_event.encode())
            self.wfile.flush()

    def read_json_body(self):
        """Read and parse JSON request body"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        return json.loads(post_data.decode('utf-8'))

    def send_json(self, data, status=200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def log_message(self, format, *args):
        """Custom log format"""
        sys.stderr.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {format % args}\n")


def open_browser():
    """Open the default browser after a short delay"""
    time.sleep(1)  # Wait for server to be ready
    webbrowser.open(f"http://localhost:{SERVER_PORT}/")


def run_server(open_browser_window=True):
    """Start the HTTP server

    Args:
        open_browser_window: Whether to automatically open browser on startup (default: True)
    """
    server_address = (SERVER_HOST, SERVER_PORT)
    httpd = ThreadingHTTPServer(server_address, JIRAHierarchyHandler)

    print(f"✅ Server starting on http://localhost:{SERVER_PORT}")
    print()
    print("📋 Available endpoints:")
    print(f"   http://localhost:{SERVER_PORT}/                     - Hierarchy viewer")
    print(f"   http://localhost:{SERVER_PORT}/api/hierarchy/stream - SSE stream")
    print(f"   http://localhost:{SERVER_PORT}/health               - Health check")
    print()

    # Open browser in a separate thread (if enabled)
    if open_browser_window:
        print("🌐 Opening browser window...")
        threading.Thread(target=open_browser, daemon=True).start()
    else:
        print("🌐 Browser auto-open disabled (use --no-browser)")
        print(f"   Navigate to http://localhost:{SERVER_PORT}/ to view")

    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 70)
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        httpd.shutdown()
        print("Server stopped.")
