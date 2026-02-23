#!/usr/bin/env python3
"""
JIRA Hierarchy Viewer Server
Entry point for the JIRA hierarchy visualization web application
"""

import os
import sys

# Check for required dependencies
try:
    import requests
except ImportError:
    print("⚠️  'requests' library not installed!")
    print()
    print("Install it with:")
    print("  pip install requests")
    print()
    sys.exit(1)

from jira_hierarchy.server import run_server


def check_requirements():
    """Check for required environment variables and files"""
    print("=" * 70)
    print("JIRA Hierarchy Viewer Server")
    print("=" * 70)
    print()

    # Check for JIRA PAT
    if not os.getenv('JIRA_PAT'):
        print("⚠️  JIRA Personal Access Token not configured!")
        print()
        print("Please set your JIRA PAT:")
        print()
        print("  export JIRA_PAT='your-personal-access-token'")
        print()
        print("To create a Personal Access Token:")
        print("  1. Go to: https://issues.redhat.com/secure/ViewProfile.jspa")
        print("  2. Click 'Personal Access Tokens' in the left sidebar")
        print("  3. Click 'Create token'")
        print("  4. Give it a name (e.g., 'JIRA Hierarchy Viewer')")
        print("  5. Click 'Create'")
        print("  6. Copy the token and set it as JIRA_PAT")
        print()
        print("Note: The PAT can also be provided via the web UI Settings")
        print()

    # Check if HTML file exists
    static_path = os.path.join(os.path.dirname(__file__), 'static', 'jira-hierarchy-viewer.html')
    old_path = os.path.join(os.path.dirname(__file__), 'jira-hierarchy-viewer.html')

    if not os.path.exists(static_path) and not os.path.exists(old_path):
        print(f"⚠️  HTML viewer not found at: {static_path}")
        print("Please make sure jira-hierarchy-viewer.html is in the static/ directory.")
        sys.exit(1)


def main():
    """Main entry point"""
    check_requirements()
    run_server()


if __name__ == '__main__':
    main()
