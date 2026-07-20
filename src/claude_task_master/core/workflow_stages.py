"""Workflow Stage Handlers — backward-compatibility shim.

The implementation has been split into :mod:`claude_task_master.core.stages`:

  stages/base.py         — StageHandlerBase (constants + __init__)
  stages/git_ops.py      — _GitOps (branch/checkout/delete helpers)
  stages/ci_stage.py     — _CIStage (CI polling, PR detection)
  stages/pr_fix_stage.py — _PRFixStage (CI failure handling)
  stages/review_stage.py — _ReviewStage (review comments)
  stages/merge_stage.py  — _MergeStage (merge + post-merge cleanup)
  stages/release_stage.py — _ReleaseStage (release verification)
  stages/__init__.py     — WorkflowStageHandler (public composite class)

All existing imports of the form
  ``from .workflow_stages import WorkflowStageHandler``
continue to work unchanged.

The names below are re-exported so that existing test patches of the form
  ``@patch("claude_task_master.core.workflow_stages.<name>")``
continue to resolve without AttributeError.  Patching them here does NOT
suppress calls made by the sub-modules (which have their own module-level
bindings); update patch targets to the specific sub-module path for full
interception (e.g. ``stages.ci_stage.interruptible_sleep``).
"""

# Re-exports for backward compatibility of test patches — do not use these
# in production code; import directly from the sub-modules instead.
from . import console  # noqa: F401
from .agent import ModelType  # noqa: F401
from .shutdown import interruptible_sleep  # noqa: F401
from .stages import WorkflowStageHandler

__all__ = ["WorkflowStageHandler"]
