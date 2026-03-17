"""Version checking utilities"""

import os
import sys
import subprocess
import requests


def get_local_commit():
    """Get the local git commit hash"""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=os.path.join(os.path.dirname(__file__), '..'),
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            return result.stdout.strip()[:7]  # Short hash
        return "unknown"
    except Exception:
        return "unknown"


def get_github_commit():
    """Get the latest commit hash from GitHub main branch"""
    try:
        url = "https://api.github.com/repos/RobGeada/jira-hierarchy-server/commits/main"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data['sha'][:7]  # Short hash
        return None
    except Exception:
        # Silently fail if we can't reach GitHub
        return None


def check_version():
    """Check if local commit matches GitHub main and print warning if not"""
    local_commit = get_local_commit()

    print(f"JIRA Hierarchy Server (commit: {local_commit})", file=sys.stderr)

    # Try to get GitHub commit
    github_commit = get_github_commit()

    if github_commit is None:
        # Couldn't reach GitHub, skip check
        return

    if local_commit != github_commit:
        print("", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("⚠️  WARNING: There are updates to the JIRA Hierarchy Server!", file=sys.stderr)
        print(f"   Local commit:  {local_commit}", file=sys.stderr)
        print(f"   Latest commit: {github_commit}", file=sys.stderr)
        print("", file=sys.stderr)
        print("   Please pull the latest changes from GitHub:", file=sys.stderr)
        print("   $ git pull origin main", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("", file=sys.stderr)
