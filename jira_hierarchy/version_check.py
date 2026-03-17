"""Version checking utilities"""

import os
import sys
import subprocess
import requests
import threading
import time


# Global state for version tracking
_version_state = {
    'local_commit': None,
    'github_commit': None,
    'is_outdated': False,
    'last_check': None,
    'enabled': True
}
_version_lock = threading.Lock()


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


def perform_version_check():
    """Perform a version check and update global state"""
    local_commit = get_local_commit()
    github_commit = get_github_commit()

    with _version_lock:
        _version_state['local_commit'] = local_commit
        _version_state['github_commit'] = github_commit
        _version_state['last_check'] = time.time()

        if github_commit and local_commit != github_commit:
            _version_state['is_outdated'] = True
        else:
            _version_state['is_outdated'] = False

    return local_commit, github_commit


def check_version():
    """Check if local commit matches GitHub main and print warning if not"""
    local_commit, github_commit = perform_version_check()

    print(f"JIRA Hierarchy Server (commit: {local_commit})", file=sys.stderr)

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


def get_version_status():
    """Get the current version status"""
    with _version_lock:
        return {
            'local_commit': _version_state['local_commit'],
            'github_commit': _version_state['github_commit'],
            'is_outdated': _version_state['is_outdated'],
            'last_check': _version_state['last_check'],
            'enabled': _version_state['enabled']
        }


def set_version_check_enabled(enabled):
    """Enable or disable version checking"""
    with _version_lock:
        _version_state['enabled'] = enabled


def periodic_version_check():
    """Background thread to periodically check version (every hour)"""
    while True:
        time.sleep(3600)  # Wait 1 hour

        # Only check if enabled
        with _version_lock:
            enabled = _version_state['enabled']

        if not enabled:
            continue

        local_commit, github_commit = perform_version_check()

        if github_commit and local_commit != github_commit:
            print(f"\n⚠️  Server is out of date: local={local_commit}, latest={github_commit}\n", file=sys.stderr)


def start_periodic_check():
    """Start the background version checking thread"""
    with _version_lock:
        enabled = _version_state['enabled']

    if not enabled:
        return

    thread = threading.Thread(target=periodic_version_check, daemon=True)
    thread.start()
