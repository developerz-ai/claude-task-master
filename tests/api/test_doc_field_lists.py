"""Guard: the documented field lists match the models and tools they describe.

`docs/api-reference.md` and `docs/mcp-tools.md` publish the option lists a
client reads before it calls one of the four request surfaces: the REST
`PATCH /config` and `POST /task/init` bodies, and the MCP `initialize_task`
and `update_config` tools. Those lists are the only place a client learns
which options exist, so a field the server accepts but the docs omit is
invisible, and a field the docs list that no model declares is a trap: the
REST surfaces ignore such a key rather than rejecting the body, so the
client sets it, gets a 200, and watches nothing happen.

The pydantic models are the authority: `ConfigUpdateRequest.model_fields` and
`TaskInitRequest.model_fields` are exactly what the REST API accepts. The MCP
tools expose those same fields plus `state_dir` - a real tool parameter
(`mcp/tool_handlers_task.py`, `mcp/tool_handlers_control.py`) that belongs to
neither request model - so the MCP tables are compared against
`model_fields | {"state_dir"}`.

The REST server does not reject an unknown key: pydantic ignores it and drops
its value. The only names it refuses are the removed ones in
`REMOVED_REQUEST_FIELDS` (`api/models_common.py`). So a request list that
grows an undeclared field documents a body whose value is silently discarded
- `budget` and `max_budget_usd` are such fields: they live on
`TaskOptionsResponse`, not on either request model. The `GET /status` sample
shows `TaskOptionsResponse` and therefore does carry `max_budget_usd`.

These tests read the committed Markdown only. On drift they name the missing
and the extra fields, so the fix is to edit the doc rather than to loosen the
assertion.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from claude_task_master.api.models import (
    ConfigUpdateRequest,
    TaskInitRequest,
    TaskOptionsResponse,
)
from claude_task_master.api.models_common import REMOVED_REQUEST_FIELDS
from claude_task_master.mcp.tools import initialize_task, update_config

# =============================================================================
# Documented surfaces
# =============================================================================

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_REFERENCE = _REPO_ROOT / "docs" / "api-reference.md"
_MCP_TOOLS = _REPO_ROOT / "docs" / "mcp-tools.md"

# The MCP-only parameter both tools expose on top of their request model.
_MCP_ONLY_PARAM = "state_dir"

# "- `name` (type) - description" - the shape api-reference.md uses for its
# field lists. Only the first backticked token is the name: descriptions
# legitimately carry more of them (`quiet`, `hive-worker`, ...).
_BULLET_RE = re.compile(r"^\s*-\s+`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`(?P<rest>.*)$")

# "| `name` | type | required | ... | description |" - the shape mcp-tools.md
# uses for its parameter tables.
_ROW_RE = re.compile(r"^\|\s*`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`(?P<rest>.*)$")

# Phrases that tell the reader the option is accepted and stored but does
# nothing - nothing in the tree implements checkpointing.
_INERT_PHRASES = (
    "no effect",
    "no checkpointing",
    "not implemented",
    "unimplemented",
    "not supported",
    "unsupported",
    "inert",
    "no-op",
    "does nothing",
    "ignored",
)

# Phrases that tell the reader the option is still accepted and stored.
_ACCEPTED_PHRASES = ("accepted", "stored")


# =============================================================================
# Markdown parsing
# =============================================================================


def _section(path: Path, heading: str) -> list[str]:
    """The lines under ``heading``, up to the next heading or section rule.

    Args:
        path: The Markdown file to read.
        heading: The exact heading line, e.g. ``#### `PATCH /config` ``.

    Returns:
        The lines of that section, fenced code blocks included.

    Raises:
        AssertionError: If the file has no such heading.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index
            break
    if start is None:
        raise AssertionError(f"{path.name}: heading {heading!r} not found")

    body: list[str] = []
    in_fence = False
    for line in lines[start + 1 :]:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            body.append(line)
            continue
        if not in_fence and (line.startswith("#") or line.strip() == "---"):
            break
        body.append(line)
    return body


def _block_after_label(path: Path, heading: str, label: str) -> list[str]:
    """The lines that follow a bold label inside a section.

    Args:
        path: The Markdown file to read.
        heading: The section heading the label belongs to.
        label: The bold label, e.g. ``**Supported Options:**``.

    Returns:
        The lines after the label, up to the end of the section.

    Raises:
        AssertionError: If the section has no such label.
    """
    body = _section(path, heading)
    for index, line in enumerate(body):
        if line.strip() == label:
            return body[index + 1 :]
    raise AssertionError(f"{path.name}: {heading} has no {label} block")


def _bullet_fields(block: list[str]) -> list[tuple[str, str]]:
    """The ``- `name` (type) - description`` bullets of a block, in order.

    Args:
        block: The lines of a bullet list.

    Returns:
        One ``(name, text after the name)`` pair per bullet.
    """
    fields: list[tuple[str, str]] = []
    for line in block:
        if not line.strip():
            continue
        match = _BULLET_RE.match(line)
        if match is None:
            break
        fields.append((match.group("name"), match.group("rest")))
    return fields


def _table_fields(block: list[str]) -> list[tuple[str, str]]:
    """The ``| `name` | type | ... | description |`` rows of a table, in order.

    Args:
        block: The lines of a table.

    Returns:
        One ``(name, text after the name)`` pair per row. The header and the
        separator row carry no backticked name and are skipped.
    """
    fields: list[tuple[str, str]] = []
    in_table = False
    for line in block:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        if set(stripped) <= set("|-: "):
            continue
        match = _ROW_RE.match(stripped)
        if match is None:
            continue
        in_table = True
        fields.append((match.group("name"), match.group("rest")))
    return fields


def _prose(section: list[str]) -> list[str]:
    """The lines of a section that are not inside a fenced code block.

    Args:
        section: The lines of a section.

    Returns:
        The prose lines only.
    """
    prose: list[str] = []
    in_fence = False
    for line in section:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            prose.append(line)
    return prose


def _json_blocks(section: list[str]) -> list[str]:
    """The bodies of the fenced code blocks of a section.

    Args:
        section: The lines of a section.

    Returns:
        The raw text of every fenced block, in order.
    """
    blocks: list[str] = []
    current: list[str] | None = None
    for line in section:
        if line.strip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


# =============================================================================
# Assertions
# =============================================================================


def _assert_same_fields(
    documented: list[tuple[str, str]],
    expected: set[str],
    label: str,
) -> None:
    """Assert that a documented list holds exactly the expected field names.

    Args:
        documented: The parsed ``(name, text)`` pairs of the documented list.
        expected: The field names the surface accepts.
        label: How the surface is named in the failure message.

    Raises:
        AssertionError: If a field is missing, extra or listed twice.
    """
    names = [name for name, _ in documented]
    documented_names = set(names)
    missing = sorted(expected - documented_names)
    extra = sorted(documented_names - expected)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not missing and not extra and not duplicates, (
        f"{label}: the documented fields drifted from the accepted fields.\n"
        f"  missing from the documentation: {missing}\n"
        f"  documented but not accepted: {extra}\n"
        f"  documented more than once: {duplicates}"
    )


def _assert_inert(text: str, label: str) -> None:
    """Assert that an option is documented as accepted but without effect.

    Args:
        text: The documented text of the option.
        label: How the option is named in the failure message.

    Raises:
        AssertionError: If the text does not say the option is inert.
    """
    lowered = text.lower()
    assert any(phrase in lowered for phrase in _ACCEPTED_PHRASES), (
        f"{label}: the option must be documented as accepted and stored, got: {text.strip()!r}"
    )
    assert any(phrase in lowered for phrase in _INERT_PHRASES), (
        f"{label}: the option must be documented as having no effect, got: {text.strip()!r}"
    )


def _field_text(fields: list[tuple[str, str]], name: str) -> str:
    """The documented text of one field.

    Args:
        fields: The parsed ``(name, text)`` pairs of a documented list.
        name: The field to look up.

    Returns:
        The text that follows the field name, or an empty string.
    """
    for field_name, rest in fields:
        if field_name == name:
            return rest
    return ""


def _tool_parameters(fn: Callable[..., Any]) -> set[str]:
    """The parameters an MCP tool exposes to clients.

    Args:
        fn: The tool implementation the forwarding wrapper wraps.

    Returns:
        The parameter names the client may pass. The server-injected
        `work_dir` is the one parameter the wrapper never exposes.
    """
    return set(inspect.signature(fn).parameters) - {"work_dir"}


# =============================================================================
# REST documentation
# =============================================================================


def test_api_patch_config_lists_exactly_the_config_update_request_fields() -> None:
    """`PATCH /config` documents exactly `ConfigUpdateRequest.model_fields`."""
    documented = _bullet_fields(
        _block_after_label(_API_REFERENCE, "#### `PATCH /config`", "**Supported Options:**")
    )
    _assert_same_fields(
        documented,
        set(ConfigUpdateRequest.model_fields),
        "docs/api-reference.md PATCH /config",
    )


def test_api_task_init_lists_exactly_the_task_init_request_fields() -> None:
    """`POST /task/init` documents exactly `TaskInitRequest.model_fields`."""
    documented = _bullet_fields(
        _block_after_label(_API_REFERENCE, "#### `POST /task/init`", "**Parameters:**")
    )
    _assert_same_fields(
        documented,
        set(TaskInitRequest.model_fields),
        "docs/api-reference.md POST /task/init",
    )


def test_api_status_sample_lists_exactly_the_task_options_response_fields() -> None:
    """The `GET /status` sample documents exactly `TaskOptionsResponse`."""
    section = _section(_API_REFERENCE, "#### `GET /status`")
    blocks = _json_blocks(section)
    assert blocks, "docs/api-reference.md GET /status has no JSON sample"
    payload = json.loads(blocks[0])
    options = payload["options"]
    documented = set(options)
    expected = set(TaskOptionsResponse.model_fields)
    missing = sorted(expected - documented)
    extra = sorted(documented - expected)
    assert not missing and not extra, (
        "docs/api-reference.md GET /status options sample drifted from "
        "TaskOptionsResponse.\n"
        f"  missing from the sample: {missing}\n"
        f"  in the sample but not on the model: {extra}"
    )


# =============================================================================
# MCP documentation
# =============================================================================


def test_mcp_initialize_task_lists_the_model_fields_plus_state_dir() -> None:
    """`initialize_task` documents `TaskInitRequest` plus the MCP-only `state_dir`."""
    documented = _table_fields(
        _block_after_label(_MCP_TOOLS, "#### `initialize_task`", "**Parameters:**")
    )
    _assert_same_fields(
        documented,
        set(TaskInitRequest.model_fields) | {_MCP_ONLY_PARAM},
        "docs/mcp-tools.md initialize_task",
    )


def test_mcp_update_config_lists_the_model_fields_plus_state_dir() -> None:
    """`update_config` documents `ConfigUpdateRequest` plus the MCP-only `state_dir`."""
    documented = _table_fields(
        _block_after_label(_MCP_TOOLS, "#### `update_config`", "**Parameters:**")
    )
    _assert_same_fields(
        documented,
        set(ConfigUpdateRequest.model_fields) | {_MCP_ONLY_PARAM},
        "docs/mcp-tools.md update_config",
    )


def test_mcp_tools_expose_no_parameters_beyond_the_model_fields_plus_state_dir() -> None:
    """A tool may expose nothing but its model's fields plus `state_dir`.

    The doc guards compare the tables against the models, so a tool parameter
    that is in neither model - and in no table - would slip through them.
    """
    _assert_same_fields(
        [(name, "") for name in sorted(_tool_parameters(initialize_task))],
        set(TaskInitRequest.model_fields) | {_MCP_ONLY_PARAM},
        "MCP tool initialize_task",
    )
    _assert_same_fields(
        [(name, "") for name in sorted(_tool_parameters(update_config))],
        set(ConfigUpdateRequest.model_fields) | {_MCP_ONLY_PARAM},
        "MCP tool update_config",
    )


# =============================================================================
# Checkpointing
# =============================================================================


def test_checkpointing_is_documented_as_accepted_but_inert() -> None:
    """Both config surfaces document `enable_checkpointing` as inert: nothing implements it."""
    surfaces = {
        "docs/api-reference.md PATCH /config": _bullet_fields(
            _block_after_label(_API_REFERENCE, "#### `PATCH /config`", "**Supported Options:**")
        ),
        "docs/mcp-tools.md update_config": _table_fields(
            _block_after_label(_MCP_TOOLS, "#### `update_config`", "**Parameters:**")
        ),
    }
    for label, fields in surfaces.items():
        text = _field_text(fields, "enable_checkpointing")
        assert text, f"{label}: enable_checkpointing is not documented"
        _assert_inert(text, f"{label} enable_checkpointing")


def test_status_sample_reports_checkpointing_as_inert() -> None:
    """The `GET /status` note says the reported checkpointing flag does nothing."""
    prose = _prose(_section(_API_REFERENCE, "#### `GET /status`"))
    mentions = " ".join(line for line in prose if "enable_checkpointing" in line)
    assert mentions, "docs/api-reference.md GET /status does not mention enable_checkpointing"
    _assert_inert(mentions, "docs/api-reference.md GET /status enable_checkpointing")


# =============================================================================
# Server behaviour
# =============================================================================


def test_undeclared_request_keys_are_dropped_and_removed_names_are_rejected() -> None:
    """An unknown key is ignored, not rejected; only a removed name fails.

    The module docstring says the REST surfaces drop a key that no model
    declares, so the claim is pinned here: `budget` is not a request field
    and the request model still accepts the body and discards the value,
    while a name in `REMOVED_REQUEST_FIELDS` is rejected outright.
    """
    init = TaskInitRequest.model_validate({"goal": "g", "budget": 5})
    assert init.goal == "g"
    assert not hasattr(init, "budget")

    config = ConfigUpdateRequest.model_validate({"max_budget_usd": 5})
    assert not hasattr(config, "max_budget_usd")

    for removed in REMOVED_REQUEST_FIELDS:
        with pytest.raises(ValidationError):
            TaskInitRequest.model_validate({"goal": "g", removed: True})
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({removed: True})
