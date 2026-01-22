"""Prompt Templates - Centralized, maintainable prompt generation.

This module provides structured prompt templates for different agent phases:
- Planning: Initial codebase analysis and task creation
- Plan Update: Modifying existing plans based on change requests
- Working: Task execution with verification
- PR Review: Addressing code review feedback
- Verification: Confirming success criteria

All prompts are designed to be concise, structured, and token-efficient.

This module re-exports all prompt functions for backward compatibility.
The actual implementations are in:
- prompts_base.py: PromptSection, PromptBuilder
- prompts_planning.py: build_planning_prompt
- prompts_plan_update.py: build_plan_update_prompt
- prompts_working.py: build_work_prompt
- prompts_verification.py: build_verification_prompt, build_task_completion_check_prompt,
                           build_context_extraction_prompt, build_error_recovery_prompt
"""

from __future__ import annotations

# Re-export base classes
from .prompts_base import PromptBuilder, PromptSection

# Re-export planning prompts
from .prompts_plan_update import build_plan_update_prompt
from .prompts_planning import build_planning_prompt

# Re-export verification prompts
from .prompts_verification import (
    build_context_extraction_prompt,
    build_error_recovery_prompt,
    build_task_completion_check_prompt,
    build_verification_prompt,
)

# Re-export working prompts
from .prompts_working import build_work_prompt

__all__ = [
    # Base classes
    "PromptSection",
    "PromptBuilder",
    # Planning
    "build_planning_prompt",
    "build_plan_update_prompt",
    # Working
    "build_work_prompt",
    # Verification and utilities
    "build_verification_prompt",
    "build_task_completion_check_prompt",
    "build_context_extraction_prompt",
    "build_error_recovery_prompt",
]
