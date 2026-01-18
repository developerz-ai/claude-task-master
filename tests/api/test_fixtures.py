"""Test API fixtures to ensure they work correctly."""

import pytest

# Skip all tests if FastAPI is not installed
try:
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")


def test_api_client_fixture(api_client):
    """Test that the API client fixture works."""
    assert api_client is not None
    assert isinstance(api_client, TestClient)


def test_api_app_fixture(api_app):
    """Test that the API app fixture works."""
    from fastapi import FastAPI

    assert api_app is not None
    assert isinstance(api_app, FastAPI)
    assert api_app.title == "Claude Task Master API"


def test_api_state_dir_fixture(api_state_dir):
    """Test that the state directory fixture works."""
    assert api_state_dir.exists()
    assert api_state_dir.is_dir()
    assert api_state_dir.name == ".claude-task-master"


def test_api_complete_state_fixture(api_complete_state):
    """Test that the complete state fixture creates all files."""
    state_dir = api_complete_state

    # Check all required files exist
    assert (state_dir / "goal.txt").exists()
    assert (state_dir / "state.json").exists()
    assert (state_dir / "plan.md").exists()
    assert (state_dir / "context.md").exists()
    assert (state_dir / "progress.md").exists()
    assert (state_dir / "criteria.txt").exists()
    assert (state_dir / "logs" / "run-20250118-120000.txt").exists()


def test_sample_request_fixtures(
    sample_pause_request, sample_stop_request, sample_config_update_request
):
    """Test that sample request fixtures return valid data."""
    assert isinstance(sample_pause_request, dict)
    assert "reason" in sample_pause_request

    assert isinstance(sample_stop_request, dict)
    assert "reason" in sample_stop_request

    assert isinstance(sample_config_update_request, dict)
    assert "auto_merge" in sample_config_update_request
    assert "max_sessions" in sample_config_update_request


def test_sample_response_fixture(sample_task_status_response):
    """Test that sample response fixture returns valid data."""
    assert isinstance(sample_task_status_response, dict)
    assert "status" in sample_task_status_response
    assert "goal" in sample_task_status_response
    assert "current_task_index" in sample_task_status_response
