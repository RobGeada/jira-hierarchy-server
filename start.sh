#!/bin/bash
# Quick start script for JIRA Hierarchy Viewer

echo "========================================"
echo "AI Safety JIRA Hierarchy Viewer"
echo "========================================"
echo ""

# Check if JIRA_PAT is set
if [ -z "$JIRA_PAT" ]; then
    echo "❌ JIRA_PAT environment variable is not set!"
    echo ""
    echo "To set your Personal Access Token:"
    echo "  export JIRA_PAT='your-token-here'"
    echo ""
    echo "Or add it to your ~/.zshrc:"
    echo "  echo \"export JIRA_PAT='your-token-here'\" >> ~/.zshrc"
    echo "  source ~/.zshrc"
    echo ""
    echo "Get a token at: https://issues.redhat.com/secure/ViewProfile.jspa"
    echo ""
    exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed!"
    exit 1
fi

# Check if requests library is installed
python3 -c "import requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "📦 Installing requests library..."
    pip3 install requests
    echo ""
fi

# Start the server
echo "✅ Starting server..."
echo ""
python3 "$(dirname "$0")/jira-hierarchy-server.py"
