#!/usr/bin/env python3
"""
JIRA Hierarchy Viewer Server
Entry point for the JIRA hierarchy visualization web application
"""

import argparse
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
from jira_hierarchy.version_check import check_version, start_periodic_check, set_version_check_enabled


def check_requirements(enable_version_check=True):
    """Check for required environment variables and files"""
    print("=" * 70)
    print("JIRA Hierarchy Viewer Server")
    print("=" * 70)
    print()

    # Check version and warn if updates available
    if enable_version_check:
        set_version_check_enabled(True)
        check_version()
        # Start periodic version checking (once per hour)
        start_periodic_check()
    else:
        set_version_check_enabled(False)
        print("Version checking disabled (--no-version-check)")
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
    parser = argparse.ArgumentParser(
        description='JIRA Hierarchy Viewer Server',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not automatically open browser window on startup'
    )
    parser.add_argument(
        '--no-version-check',
        action='store_true',
        help='Disable version checking (useful for development on feature branches)'
    )

    args = parser.parse_args()

    check_requirements(enable_version_check=not args.no_version_check)
    run_server(open_browser_window=not args.no_browser)


if __name__ == '__main__':
    main()
