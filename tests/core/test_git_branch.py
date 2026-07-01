"""Unit tests for git branch-name validation."""

import pytest

from claude_task_master.core.git_branch import is_valid_branch_name


@pytest.mark.parametrize(
    "name",
    [
        "feature/login",
        "release/v2",
        "fix-123",
        "user/task/subtask",
        "a",
        "WIP_snake_case",
    ],
)
def test_valid_names(name: str) -> None:
    assert is_valid_branch_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty
        "@",  # bare @
        "-leading-dash",
        "/leading-slash",
        "trailing-slash/",
        "trailing-dot.",
        "feature.lock",
        "foo.lock/bar",  # nested component ending in .lock
        "a/b.lock",
        "has..dotdot",
        "has space",
        "has\ttab",
        "ctrl\x01char",
        "tilde~",
        "caret^",
        "colon:",
        "question?",
        "star*",
        "bracket[",
        "back\\slash",
        "at@{brace",
        "double//slash",
        "foo/.hidden",  # component starting with dot
        ".hidden",
    ],
)
def test_invalid_names(name: str) -> None:
    assert is_valid_branch_name(name) is False
