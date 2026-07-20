"""core.stages — WorkflowStageHandler split across single-responsibility modules.

Public surface: import :class:`WorkflowStageHandler` from here (or from the
backward-compat shim ``core.workflow_stages``).

Inheritance chain (each extends the previous):
  StageHandlerBase  ← constants + __init__
  _GitOps           ← git branch/checkout helpers
  _CIStage          ← CI polling + PR-creation detection
  _PRFixStage       ← CI-failure handling
  _ReviewStage      ← review-comment polling + resolution
  _MergeStage       ← merge readiness + post-merge cleanup
  _ReleaseStage     ← release verification + quick-fix PR
  WorkflowStageHandler  ← public API (no extra logic)
"""

from .release_stage import _ReleaseStage


class WorkflowStageHandler(_ReleaseStage):
    """Handles individual workflow stages in the PR lifecycle.

    Workflow stages:
    1. working → Implement tasks
    2. pr_created → Create/update PR
    3. waiting_ci → Poll CI status
    4. ci_failed → Fix CI failures
    5. waiting_reviews → Wait for reviews
    6. addressing_reviews → Address review feedback
    7. ready_to_merge → Merge PR
    8. merged → Move to releasing (if auto_merge) or next task
    9. releasing → Verify deployment health (optional, auto_merge only)
    10. release_fix → Quick-fix PR if release verification failed
    """


__all__ = ["WorkflowStageHandler"]
