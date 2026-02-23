"""Configuration management for JIRA Hierarchy Viewer"""

import os

# JIRA Configuration
JIRA_BASE_URL = os.getenv('JIRA_URL', 'https://issues.redhat.com')
JIRA_PAT = os.getenv('JIRA_PAT')

# Server Configuration
SERVER_PORT = int(os.getenv('PORT', '8000'))
SERVER_HOST = os.getenv('HOST', '')

# Default component filter
DEFAULT_COMPONENT = 'AI Safety'


def get_jira_pat(override_pat=None):
    """Get JIRA PAT from parameter or environment"""
    pat = override_pat or JIRA_PAT
    if not pat:
        raise ValueError(
            "JIRA Personal Access Token not provided. Please configure in Settings or set:\n"
            "  export JIRA_PAT='your-personal-access-token'\n"
        )
    return pat
