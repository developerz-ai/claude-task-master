"""State Manager - All persistence to .claude-task-master/ directory."""

from pathlib import Path
from typing import Optional
from datetime import datetime
import json
from pydantic import BaseModel


class TaskOptions(BaseModel):
    """Options for task execution."""

    auto_merge: bool = True
    max_sessions: Optional[int] = None
    pause_on_pr: bool = False


class TaskState(BaseModel):
    """Machine-readable state."""

    status: str  # planning|working|blocked|success|failed
    current_task_index: int = 0
    session_count: int = 0
    current_pr: Optional[int] = None
    created_at: str
    updated_at: str
    run_id: str
    model: str
    options: TaskOptions


class StateManager:
    """Manages all state persistence."""

    STATE_DIR = Path(".claude-task-master")

    def __init__(self, state_dir: Optional[Path] = None):
        """Initialize state manager."""
        self.state_dir = state_dir or self.STATE_DIR
        self.logs_dir = self.state_dir / "logs"

    def initialize(
        self, goal: str, model: str, options: TaskOptions
    ) -> TaskState:
        """Initialize new task state."""
        self.state_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().isoformat()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        state = TaskState(
            status="planning",
            created_at=timestamp,
            updated_at=timestamp,
            run_id=run_id,
            model=model,
            options=options,
        )

        self.save_state(state)
        self.save_goal(goal)

        return state

    def save_state(self, state: TaskState) -> None:
        """Save state to state.json."""
        state.updated_at = datetime.now().isoformat()
        state_file = self.state_dir / "state.json"

        with open(state_file, "w") as f:
            json.dump(state.model_dump(), f, indent=2)

    def load_state(self) -> TaskState:
        """Load state from state.json."""
        state_file = self.state_dir / "state.json"

        if not state_file.exists():
            raise FileNotFoundError("No task state found. Run 'start' first.")

        with open(state_file) as f:
            data = json.load(f)

        return TaskState(**data)

    def save_goal(self, goal: str) -> None:
        """Save goal to goal.txt."""
        goal_file = self.state_dir / "goal.txt"
        goal_file.write_text(goal)

    def load_goal(self) -> str:
        """Load goal from goal.txt."""
        goal_file = self.state_dir / "goal.txt"
        return goal_file.read_text()

    def save_criteria(self, criteria: str) -> None:
        """Save success criteria to criteria.txt."""
        criteria_file = self.state_dir / "criteria.txt"
        criteria_file.write_text(criteria)

    def load_criteria(self) -> Optional[str]:
        """Load success criteria from criteria.txt."""
        criteria_file = self.state_dir / "criteria.txt"
        if criteria_file.exists():
            return criteria_file.read_text()
        return None

    def save_plan(self, plan: str) -> None:
        """Save task plan to plan.md."""
        plan_file = self.state_dir / "plan.md"
        plan_file.write_text(plan)

    def load_plan(self) -> Optional[str]:
        """Load task plan from plan.md."""
        plan_file = self.state_dir / "plan.md"
        if plan_file.exists():
            return plan_file.read_text()
        return None

    def save_progress(self, progress: str) -> None:
        """Save progress summary to progress.md."""
        progress_file = self.state_dir / "progress.md"
        progress_file.write_text(progress)

    def load_progress(self) -> Optional[str]:
        """Load progress summary from progress.md."""
        progress_file = self.state_dir / "progress.md"
        if progress_file.exists():
            return progress_file.read_text()
        return None

    def save_context(self, context: str) -> None:
        """Save accumulated context to context.md."""
        context_file = self.state_dir / "context.md"
        context_file.write_text(context)

    def load_context(self) -> str:
        """Load accumulated context from context.md."""
        context_file = self.state_dir / "context.md"
        if context_file.exists():
            return context_file.read_text()
        return ""

    def get_log_file(self, run_id: str) -> Path:
        """Get path to log file for run."""
        return self.logs_dir / f"run-{run_id}.txt"

    def exists(self) -> bool:
        """Check if state directory exists."""
        return self.state_dir.exists() and (self.state_dir / "state.json").exists()

    def cleanup_on_success(self, run_id: str) -> None:
        """Clean up all state files except logs on success."""
        import shutil

        # Delete all files in state directory except logs/
        for item in self.state_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir() and item != self.logs_dir:
                shutil.rmtree(item)

        # Keep only the last 10 log files
        self._cleanup_old_logs(max_logs=10)

    def _cleanup_old_logs(self, max_logs: int = 10) -> None:
        """Keep only the most recent log files."""
        if not self.logs_dir.exists():
            return

        # Get all log files sorted by modification time (newest first)
        log_files = sorted(
            self.logs_dir.glob("run-*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        # Delete older logs
        for log_file in log_files[max_logs:]:
            log_file.unlink()
