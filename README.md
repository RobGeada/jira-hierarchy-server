# JIRA Hierarchy Viewer

A web application for visualizing and interacting with JIRA issue hierarchies with support for RFEs, STRATs, Epics, and Tasks.

## Project Structure

```
jira-dashboard-configs/
├── jira_hierarchy/              # Main package
│   ├── __init__.py             # Package initialization
│   ├── config.py               # Configuration management
│   ├── jira_client.py          # JIRA REST API client
│   ├── data_fetcher.py         # Data fetching and hierarchy building
│   ├── sse.py                  # Server-Sent Events utilities
│   └── server.py               # HTTP server and request handlers
├── static/                      # Static files
│   └── jira-hierarchy-viewer.html  # Web UI
├── jira-hierarchy-server.py    # Entry point script
└── README.md                   # This file
```

## Features

- **Real-time streaming**: Uses Server-Sent Events (SSE) for progressive loading
- **Hierarchical view**: Displays RFE → STRAT → Epic → Task relationships
- **Interactive UI**: Expandable tree view with sorting and filtering
- **Issue details**: View descriptions, comments, labels, components, and dates
- **Create issues**: Create Epics and Tasks directly from the UI
- **Add comments**: Comment on issues without leaving the viewer

## Setup

### Prerequisites

- Python 3.7+
- JIRA Personal Access Token (PAT)

### Installation

1. Install dependencies:
   ```bash
   pip install requests
   ```

2. Set your JIRA Personal Access Token:
   ```bash
   export JIRA_PAT='your-personal-access-token'
   ```

   To create a PAT:
   - Go to: https://issues.redhat.com/secure/ViewProfile.jspa
   - Click 'Personal Access Tokens' in the left sidebar
   - Click 'Create token'
   - Give it a name and click 'Create'
   - Copy the token and set it as JIRA_PAT

3. Optional: Configure custom port
   ```bash
   export PORT=8080
   ```

### Running the Server

```bash
python3 jira-hierarchy-server.py
```

The browser will automatically open to http://localhost:8000

**Command line options:**
- `--no-browser`: Skip automatically opening the browser (useful if you already have the page open)

```bash
# Skip opening browser
python3 jira-hierarchy-server.py --no-browser
```

## Configuration

Environment variables:
- `JIRA_PAT`: Personal Access Token (required)
- `JIRA_URL`: JIRA base URL (default: https://issues.redhat.com)
- `PORT`: Server port (default: 8000)
- `HOST`: Server host (default: '' = all interfaces)

## Development

### Module Overview

- **config.py**: Manages environment variables and configuration
- **jira_client.py**: Low-level JIRA API wrapper (queries, issue creation, comments)
- **data_fetcher.py**: High-level data fetching logic (building hierarchies)
- **sse.py**: Server-Sent Events implementation for real-time streaming
- **server.py**: HTTP server with request routing and handlers

### Adding New Features

1. **New JIRA API calls**: Add to `jira_client.py`
2. **New data fetching logic**: Add to `data_fetcher.py`
3. **New HTTP endpoints**: Add to `server.py`
4. **New UI features**: Modify `static/jira-hierarchy-viewer.html`

## API Endpoints

- `GET /` - Serve the HTML viewer
- `GET /api/hierarchy/stream` - Stream hierarchy data (SSE)
- `GET /health` - Health check
- `POST /api/create-epic` - Create a new Epic
- `POST /api/create-task` - Create a new Task
- `POST /api/add-comment` - Add a comment to an issue
