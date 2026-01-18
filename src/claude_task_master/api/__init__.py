"""REST API layer for Claude Task Master.

This module provides a FastAPI-based REST API that exposes claudetm functionality
as HTTP endpoints for remote task management and control operations.

Key Features:
- Status and monitoring endpoints (GET /status, /plan, /logs, /progress)
- Control operations (POST /control/pause, /control/stop, /control/resume)
- Configuration management (PATCH /config)
- Task lifecycle management (POST /task/init, DELETE /task)

Usage:
    # Import and create the app
    from claude_task_master.api import create_app

    app = create_app()

    # Or run directly
    from claude_task_master.api import run_server

    run_server(host="0.0.0.0", port=8000)
"""

# API components will be imported here as they are implemented in subsequent tasks:
# - models.py: Pydantic request/response models
# - server.py: FastAPI app factory and server runner
# - routes.py: API endpoint definitions

__all__: list[str] = []
