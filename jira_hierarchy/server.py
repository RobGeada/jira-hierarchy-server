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
        elif parsed_path.path == '/api/transitions':
            self.get_transitions()
        elif parsed_path.path == '/api/reload-item':
            self.reload_item()
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
        else:
            self.send_error(404, 'Not Found')

    def handle_create_epic(self):
        """Create a new epic and link it to a STRAT"""
        try:
            data = self.read_json_body()

            pat = data.get('pat')
            strat_key = data.get('strat_key')
            summary = data.get('summary')
            component = data.get('component')
            assignee = data.get('assignee')
            description = data.get('description', '')

            if not strat_key or not summary:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            epic_data = create_epic(summary, description, strat_key, component, assignee, pat)
            self.send_json({'success': True, 'epic': epic_data})

        except Exception as e:
            print(f"Error creating epic: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_create_task(self):
        """Create a new task and link it to an epic"""
        try:
            data = self.read_json_body()

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

            task_data = create_task(summary, description, epic_key, issue_type, component, assignee, pat)
            self.send_json({'success': True, 'task': task_data})

        except Exception as e:
            print(f"Error creating task: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_add_comment(self):
        """Add a comment to a JIRA issue"""
        try:
            data = self.read_json_body()

            pat = data.get('pat')
            issue_key = data.get('issue_key')
            comment = data.get('comment')

            if not issue_key or not comment:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            add_jira_comment(issue_key, comment, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error adding comment: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_labels(self):
        """Add or remove a label from a JIRA issue"""
        try:
            data = self.read_json_body()

            pat = data.get('pat')
            issue_key = data.get('issue_key')
            action = data.get('action')  # 'add' or 'remove'
            label = data.get('label')

            if not issue_key or not action or not label:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            updated_labels = update_jira_labels(issue_key, action, label, pat)
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
            pat = params.get('pat', [None])[0]

            if not issue_key:
                self.send_json({'error': 'Missing issue_key parameter'}, status=400)
                return

            transitions = get_jira_transitions(issue_key, pat)
            self.send_json({'success': True, 'transitions': transitions})

        except Exception as e:
            print(f"Error getting transitions: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_transition(self):
        """Transition a JIRA issue to a new status"""
        try:
            data = self.read_json_body()

            pat = data.get('pat')
            issue_key = data.get('issue_key')
            transition_id = data.get('transition_id')

            if not issue_key or not transition_id:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            transition_jira_issue(issue_key, transition_id, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error transitioning issue: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_priority(self):
        """Update the priority of a JIRA issue"""
        try:
            data = self.read_json_body()

            pat = data.get('pat')
            issue_key = data.get('issue_key')
            priority = data.get('priority')

            if not issue_key or not priority:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            from .jira_client import update_jira_issue
            update_jira_issue(issue_key, {'priority': {'name': priority}}, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error updating priority: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def handle_update_assignee(self):
        """Update the assignee of a JIRA issue"""
        try:
            data = self.read_json_body()

            pat = data.get('pat')
            issue_key = data.get('issue_key')
            assignee = data.get('assignee', '')

            if not issue_key:
                self.send_json({'error': 'Missing required fields'}, status=400)
                return

            from .jira_client import update_jira_issue
            # If assignee is empty, set to null to unassign
            if assignee:
                update_jira_issue(issue_key, {'assignee': {'name': assignee}}, pat)
            else:
                update_jira_issue(issue_key, {'assignee': None}, pat)
            self.send_json({'success': True})

        except Exception as e:
            print(f"Error updating assignee: {e}", file=sys.stderr)
            traceback.print_exc()
            self.send_json({'error': str(e)}, status=500)

    def reload_item(self):
        """Reload a single item and its children"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            issue_key = params.get('issue_key', [None])[0]
            item_type = params.get('item_type', [None])[0]
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
                rfes = fetch_rfes(component, pat)
                rfe = next((r for r in rfes if r['key'] == issue_key), None)
                if not rfe:
                    self.send_json({'error': 'RFE not found'}, status=404)
                    return

                # Fetch its children
                rfe['strats'] = []
                strats = fetch_strats_for_rfe(issue_key, pat)
                for strat_data in strats:
                    strat_data['rfe_key'] = issue_key
                    strat_data['epics'] = []

                    epics = fetch_epics_for_strat(strat_data['key'], pat)
                    for epic_data in epics:
                        epic_data['rfe_key'] = issue_key
                        epic_data['strat_key'] = strat_data['key']
                        epic_data['tasks'] = fetch_tasks_for_epic(epic_data['key'], pat)
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
                strat_issues = run_jira_query(jql, field_list, pat)
                if not strat_issues:
                    self.send_json({'error': 'STRAT not found'}, status=404)
                    return

                strat_data = build_issue_data(strat_issues[0], 'strat')
                strat_data['epics'] = []

                epics = fetch_epics_for_strat(issue_key, pat)
                for epic_data in epics:
                    epic_data['strat_key'] = issue_key
                    epic_data['tasks'] = fetch_tasks_for_epic(epic_data['key'], pat)
                    for task in epic_data['tasks']:
                        task['strat_key'] = issue_key
                        task['epic_key'] = epic_data['key']
                    strat_data['epics'].append(epic_data)

                self.send_json({'success': True, 'data': strat_data})

            elif item_type == 'epic':
                # Fetch this specific Epic
                jql = f'key = {issue_key}'
                field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,created,updated,components'
                epic_issues = run_jira_query(jql, field_list, pat)
                if not epic_issues:
                    self.send_json({'error': 'Epic not found'}, status=404)
                    return

                epic_data = build_issue_data(epic_issues[0], 'epic')
                epic_data['tasks'] = fetch_tasks_for_epic(issue_key, pat)
                for task in epic_data['tasks']:
                    task['epic_key'] = issue_key

                self.send_json({'success': True, 'data': epic_data})

            elif item_type == 'task':
                # Fetch this specific Task
                jql = f'key = {issue_key}'
                field_list = 'summary,status,priority,assignee,reporter,description,labels,comment,issuetype,created,updated,components'
                task_issues = run_jira_query(jql, field_list, pat)
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

        pat = params.get('pat', [None])[0]
        component = params.get('component', ['AI Safety'])[0]
        top_level = params.get('top_level', ['rfe'])[0]

        if not pat:
            pat = os.getenv('JIRA_PAT')

        if not pat:
            self.send_json({'error': 'Personal Access Token not provided'}, status=400)
            return

        self.send_response(200)
        self.send_header('Content-type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        try:
            stream_hierarchy(self.wfile, pat, component, top_level)
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


def run_server():
    """Start the HTTP server"""
    server_address = (SERVER_HOST, SERVER_PORT)
    httpd = ThreadingHTTPServer(server_address, JIRAHierarchyHandler)

    print(f"✅ Server starting on http://localhost:{SERVER_PORT}")
    print()
    print("📋 Available endpoints:")
    print(f"   http://localhost:{SERVER_PORT}/                     - Hierarchy viewer")
    print(f"   http://localhost:{SERVER_PORT}/api/hierarchy/stream - SSE stream")
    print(f"   http://localhost:{SERVER_PORT}/health               - Health check")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 70)
    print()

    # Open browser in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        httpd.shutdown()
        print("Server stopped.")
