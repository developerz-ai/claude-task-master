"""CLI command modules for Claude Task Master."""

from .config import register_config_commands
from .fix_pr import register_fix_pr_command
from .github import register_github_commands
from .info import register_info_commands
from .workflow import register_workflow_commands

__all__ = [
    "register_workflow_commands",
    "register_info_commands",
    "register_github_commands",
    "register_config_commands",
    "register_fix_pr_command",
]
