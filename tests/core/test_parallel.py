"""Tests for parallel task executor."""

import asyncio

import pytest

from claude_task_master.core.parallel import (
    AsyncParallelExecutor,
    ParallelExecutor,
    ParallelExecutorConfig,
    ParallelTask,
    TaskResult,
    TaskStatus,
)


class TestTaskResult:
    """Tests for TaskResult."""

    def test_duration(self):
        """Test duration calculation."""
        result: TaskResult = TaskResult(
            task_id="test",
            status=TaskStatus.COMPLETED,
            start_time=100.0,
            end_time=105.0,
        )
        assert result.duration == 5.0

    def test_duration_none(self):
        """Test duration when times not set."""
        result: TaskResult = TaskResult(task_id="test", status=TaskStatus.PENDING)
        assert result.duration is None

    def test_is_success(self):
        """Test success check."""
        result: TaskResult = TaskResult(
            task_id="test",
            status=TaskStatus.COMPLETED,
            result="data",
        )
        assert result.is_success

    def test_is_not_success_on_failure(self):
        """Test success check on failure."""
        result: TaskResult = TaskResult(
            task_id="test",
            status=TaskStatus.FAILED,
            error=ValueError("test"),
        )
        assert not result.is_success


class TestParallelExecutorConfig:
    """Tests for ParallelExecutorConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = ParallelExecutorConfig.default()
        assert config.max_workers == 4
        assert config.task_timeout == 300.0
        assert config.max_retries == 2

    def test_conservative_config(self):
        """Test conservative configuration."""
        config = ParallelExecutorConfig.conservative()
        assert config.max_workers == 2
        assert config.max_retries == 3

    def test_aggressive_config(self):
        """Test aggressive configuration."""
        config = ParallelExecutorConfig.aggressive()
        assert config.max_workers == 8
        assert config.max_retries == 1


class TestParallelExecutor:
    """Tests for ParallelExecutor."""

    def test_add_task(self):
        """Test adding a task."""
        executor = ParallelExecutor()
        task = ParallelTask(task_id="test", func=lambda: "result")

        executor.add_task(task)

        assert "test" in executor._tasks
        assert executor._results["test"].status == TaskStatus.PENDING

    def test_add_duplicate_task_raises(self):
        """Test that adding duplicate task raises."""
        executor = ParallelExecutor()
        task = ParallelTask(task_id="test", func=lambda: "result")

        executor.add_task(task)

        with pytest.raises(ValueError):
            executor.add_task(task)

    def test_execute_single_task(self):
        """Test executing a single task."""
        executor = ParallelExecutor()
        task = ParallelTask(task_id="test", func=lambda: "success")

        executor.add_task(task)
        results = executor.execute_all()

        assert results["test"].status == TaskStatus.COMPLETED
        assert results["test"].result == "success"

    def test_execute_multiple_tasks(self):
        """Test executing multiple tasks."""
        executor = ParallelExecutor()

        for i in range(3):
            executor.add_task(
                ParallelTask(task_id=f"task{i}", func=lambda x=i: f"result{x}")  # type: ignore[misc]
            )

        results = executor.execute_all()

        assert len(results) == 3
        for i in range(3):
            assert results[f"task{i}"].status == TaskStatus.COMPLETED

    def test_execute_failing_task(self):
        """Test executing a failing task."""
        executor = ParallelExecutor(config=ParallelExecutorConfig(max_retries=0))

        def failing_func():
            raise ValueError("test error")

        task = ParallelTask(task_id="test", func=failing_func)
        executor.add_task(task)

        results = executor.execute_all()

        assert results["test"].status == TaskStatus.FAILED
        assert results["test"].error is not None

    def test_cancel(self):
        """Test cancelling pending tasks."""
        executor = ParallelExecutor()
        task = ParallelTask(task_id="test", func=lambda: "result")

        executor.add_task(task)
        executor.cancel()

        assert executor._results["test"].status == TaskStatus.CANCELLED

    def test_get_progress(self):
        """Test getting progress."""
        executor = ParallelExecutor()

        for i in range(3):
            executor.add_task(ParallelTask(task_id=f"task{i}", func=lambda: "result"))

        progress = executor.get_progress()
        assert progress["pending"] == 3

    def test_clear(self):
        """Test clearing executor."""
        executor = ParallelExecutor()
        executor.add_task(ParallelTask(task_id="test", func=lambda: "result"))

        executor.clear()

        assert len(executor._tasks) == 0
        assert len(executor._results) == 0

    def test_task_with_dependencies(self):
        """Test task dependency resolution."""
        executor = ParallelExecutor()

        executor.add_task(ParallelTask(task_id="task1", func=lambda: "r1"))
        executor.add_task(
            ParallelTask(
                task_id="task2",
                func=lambda: "r2",
                dependencies=["task1"],
            )
        )

        results = executor.execute_all()

        assert results["task1"].status == TaskStatus.COMPLETED
        assert results["task2"].status == TaskStatus.COMPLETED


class TestAsyncParallelExecutor:
    """Tests for AsyncParallelExecutor."""

    @pytest.mark.asyncio
    async def test_gather_single_task(self):
        """Test gathering single async task."""
        executor = AsyncParallelExecutor()

        async def task():
            return "success"

        results = await executor.gather([("test", task())])

        assert results["test"].status == TaskStatus.COMPLETED
        assert results["test"].result == "success"

    @pytest.mark.asyncio
    async def test_gather_multiple_tasks(self):
        """Test gathering multiple async tasks."""
        executor = AsyncParallelExecutor()

        async def task(n):
            await asyncio.sleep(0.01)
            return f"result{n}"

        tasks = [(f"task{i}", task(i)) for i in range(3)]
        results = await executor.gather(tasks)

        assert len(results) == 3
        for i in range(3):
            assert results[f"task{i}"].status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_gather_with_failure(self):
        """Test gathering with failing task."""
        executor = AsyncParallelExecutor()

        async def failing_task():
            raise ValueError("test")

        results = await executor.gather([("test", failing_task())])

        assert results["test"].status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_map(self):
        """Test map function."""
        executor = AsyncParallelExecutor()

        async def double(x):
            return x * 2

        results = await executor.map(double, [1, 2, 3])

        assert results["task_0"].result == 2
        assert results["task_1"].result == 4
        assert results["task_2"].result == 6
