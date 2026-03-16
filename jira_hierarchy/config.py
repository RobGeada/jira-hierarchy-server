"""Configuration management for JIRA Hierarchy Viewer"""

import os

# JIRA Configuration
JIRA_BASE_URL = os.getenv('JIRA_URL', 'https://redhat.atlassian.net')
JIRA_PAT = os.getenv('JIRA_PAT')
JIRA_EMAIL = os.getenv('JIRA_EMAIL')

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
            "JIRA API Token not provided. Please configure in Settings or set:\n"
            "  export JIRA_PAT='your-api-token'\n"
        )
    return pat


def get_jira_email(override_email=None):
    """Get JIRA email from parameter or environment"""
    email = override_email or JIRA_EMAIL
    if not email:
        raise ValueError(
            "JIRA Email not provided. Please configure in Settings or set:\n"
            "  export JIRA_EMAIL='your-email@redhat.com'\n"
        )
    return email
