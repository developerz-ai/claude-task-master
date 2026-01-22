"""Parallel Task Executor for concurrent task execution.

Enables running multiple independent tasks in parallel using
asyncio and thread pools for improved throughput.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, get_circuit_breaker

T = TypeVar("T")


class TaskStatus(Enum):
    """Status of a parallel task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult[T]:
    """Result of a parallel task execution."""

    task_id: str
    status: TaskStatus
    result: T | None = None
    error: Exception | None = None
    start_time: float | None = None
    end_time: float | None = None
    retries: int = 0

    @property
    def duration(self) -> float | None:
        """Get task duration in seconds."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None

    @property
    def is_success(self) -> bool:
        """Check if task completed successfully."""
        return self.status == TaskStatus.COMPLETED and self.error is None


@dataclass
class ParallelExecutorConfig:
    """Configuration for parallel executor."""

    max_workers: int = 4  # Max concurrent tasks
    task_timeout: float = 300.0  # Task timeout in seconds
    max_retries: int = 2  # Max retries per task
    use_circuit_breaker: bool = True  # Enable circuit breaker per task type
    batch_size: int = 10  # Max tasks to process in one batch

    @classmethod
    def default(cls) -> ParallelExecutorConfig:
        """Default configuration."""
        return cls()

    @classmethod
    def conservative(cls) -> ParallelExecutorConfig:
        """Conservative configuration - fewer parallel tasks."""
        return cls(max_workers=2, task_timeout=600.0, max_retries=3)

    @classmethod
    def aggressive(cls) -> ParallelExecutorConfig:
        """Aggressive configuration - more parallel tasks."""
        return cls(max_workers=8, task_timeout=180.0, max_retries=1)


@dataclass
class ParallelTask[T]:
    """A task to be executed in parallel."""

    task_id: str
    func: Callable[[], T]
    task_type: str = "default"  # For circuit breaker grouping
    priority: int = 0  # Higher = higher priority
    timeout: float | None = None  # Override default timeout
    dependencies: list[str] = field(default_factory=list)  # Task IDs this depends on


class ParallelExecutor:
    """Execute multiple tasks in parallel with fault tolerance.

    Features:
    - Thread pool for concurrent execution
    - Circuit breaker per task type
    - Timeout handling
    - Retry logic
    - Dependency resolution
    - Progress tracking

    Usage:
        executor = ParallelExecutor()

        # Add tasks
        executor.add_task(ParallelTask(
            task_id="task1",
            func=lambda: do_work(),
            task_type="api_call"
        ))

        # Execute all tasks
        results = executor.execute_all()

        # Or execute with async
        results = await executor.execute_all_async()
    """

    def __init__(self, config: ParallelExecutorConfig | None = None):
        """Initialize executor with configuration."""
        self.config = config or ParallelExecutorConfig.default()
        self._tasks: dict[str, ParallelTask] = {}
        self._results: dict[str, TaskResult] = {}
        self._lock = threading.RLock()
        self._executor: ThreadPoolExecutor | None = None
        self._cancelled = threading.Event()

    def add_task(self, task: ParallelTask) -> None:
        """Add a task to be executed.

        Args:
            task: The task to add.

        Raises:
            ValueError: If task with same ID already exists.
        """
        with self._lock:
            if task.task_id in self._tasks:
                raise ValueError(f"Task with ID '{task.task_id}' already exists")
            self._tasks[task.task_id] = task
            self._results[task.task_id] = TaskResult(
                task_id=task.task_id,
                status=TaskStatus.PENDING,
            )

    def add_tasks(self, tasks: list[ParallelTask]) -> None:
        """Add multiple tasks."""
        for task in tasks:
            self.add_task(task)

    def cancel(self) -> None:
        """Cancel all pending tasks."""
        self._cancelled.set()
        with self._lock:
            for _task_id, result in self._results.items():
                if result.status == TaskStatus.PENDING:
                    result.status = TaskStatus.CANCELLED

    def _get_circuit_breaker(self, task_type: str) -> CircuitBreaker | None:
        """Get circuit breaker for a task type."""
        if not self.config.use_circuit_breaker:
            return None
        return get_circuit_breaker(
            f"parallel_{task_type}",
            CircuitBreakerConfig.default(),
        )

    def _execute_task(self, task: ParallelTask) -> TaskResult:
        """Execute a single task with retry and circuit breaker."""
        result = self._results[task.task_id]
        result.start_time = time.time()
        result.status = TaskStatus.RUNNING

        circuit_breaker = self._get_circuit_breaker(task.task_type)

        for attempt in range(self.config.max_retries + 1):
            if self._cancelled.is_set():
                result.status = TaskStatus.CANCELLED
                result.end_time = time.time()
                return result

            try:
                # Execute with circuit breaker if enabled
                if circuit_breaker:
                    task_result = circuit_breaker.call(task.func)
                else:
                    task_result = task.func()

                result.result = task_result
                result.status = TaskStatus.COMPLETED
                result.end_time = time.time()
                result.retries = attempt
                return result

            except Exception as e:
                result.error = e
                result.retries = attempt

                # Check if we should retry
                if attempt < self.config.max_retries:
                    # Exponential backoff
                    backoff = min(2**attempt, 30)
                    time.sleep(backoff)
                    continue

                # Final failure
                result.status = TaskStatus.FAILED
                result.end_time = time.time()
                return result

        # Should not reach here
        result.status = TaskStatus.FAILED
        result.end_time = time.time()
        return result

    def _resolve_dependencies(self) -> list[list[ParallelTask]]:
        """Resolve task dependencies and return execution batches.

        Returns:
            List of batches, where each batch contains tasks
            that can be executed in parallel.
        """
        # Build dependency graph
        remaining = set(self._tasks.keys())
        completed: set[str] = set()
        batches: list[list[ParallelTask]] = []

        while remaining:
            # Find tasks with all dependencies satisfied
            ready = []
            for task_id in remaining:
                task = self._tasks[task_id]
                if all(dep in completed for dep in task.dependencies):
                    ready.append(task)

            if not ready:
                # Circular dependency or missing dependency
                raise ValueError(
                    f"Cannot resolve dependencies. Remaining: {remaining}, Completed: {completed}"
                )

            # Sort by priority (higher first)
            ready.sort(key=lambda t: t.priority, reverse=True)

            # Create batch (respecting batch size)
            batch = ready[: self.config.batch_size]
            batches.append(batch)

            # Mark as completed
            for task in batch:
                remaining.remove(task.task_id)
                completed.add(task.task_id)

        return batches

    def execute_all(self) -> dict[str, TaskResult]:
        """Execute all tasks synchronously.

        Tasks are executed in batches based on dependencies.
        Tasks within a batch are executed in parallel.

        Returns:
            Dictionary mapping task IDs to results.
        """
        self._cancelled.clear()

        try:
            batches = self._resolve_dependencies()
        except ValueError as e:
            # Mark all tasks as failed
            for task_id in self._tasks:
                self._results[task_id].status = TaskStatus.FAILED
                self._results[task_id].error = e
            return self._results.copy()

        # Execute batches
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            self._executor = executor

            for batch in batches:
                if self._cancelled.is_set():
                    break

                # Submit all tasks in batch
                futures: dict[str, Future] = {}
                for task in batch:
                    if self._cancelled.is_set():
                        break
                    future = executor.submit(self._execute_task, task)
                    futures[task.task_id] = future

                # Wait for all tasks in batch to complete
                for task_id, future in futures.items():
                    try:
                        timeout = self._tasks[task_id].timeout or self.config.task_timeout
                        future.result(timeout=timeout + 10)  # Extra buffer for cleanup
                    except Exception as e:
                        # Handle timeout or other errors
                        result = self._results[task_id]
                        if result.status == TaskStatus.RUNNING:
                            result.status = TaskStatus.FAILED
                            result.error = e
                            result.end_time = time.time()

            self._executor = None

        return self._results.copy()

    async def execute_all_async(self) -> dict[str, TaskResult]:
        """Execute all tasks asynchronously.

        Returns:
            Dictionary mapping task IDs to results.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.execute_all)

    def get_results(self) -> dict[str, TaskResult]:
        """Get current results."""
        return self._results.copy()

    def get_progress(self) -> dict[str, int]:
        """Get execution progress.

        Returns:
            Dictionary with counts for each status.
        """
        counts = {status.value: 0 for status in TaskStatus}
        for result in self._results.values():
            counts[result.status.value] += 1
        return counts

    def clear(self) -> None:
        """Clear all tasks and results."""
        with self._lock:
            self._tasks.clear()
            self._results.clear()
            self._cancelled.clear()


class AsyncParallelExecutor:
    """Async-native parallel executor using asyncio.gather.

    Better for I/O-bound tasks like API calls where you want
    true async concurrency rather than thread pools.

    Usage:
        executor = AsyncParallelExecutor()

        async def task1():
            return await api_call_1()

        async def task2():
            return await api_call_2()

        results = await executor.gather([
            ("task1", task1()),
            ("task2", task2()),
        ])
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        timeout: float = 300.0,
    ):
        """Initialize async executor.

        Args:
            max_concurrent: Maximum concurrent coroutines.
            timeout: Default timeout per task.
        """
        self.max_concurrent = max_concurrent
        self.timeout = timeout

    async def gather(
        self,
        tasks: list[tuple[str, Any]],  # (task_id, coroutine)
        return_exceptions: bool = True,
    ) -> dict[str, TaskResult]:
        """Execute multiple coroutines concurrently.

        Args:
            tasks: List of (task_id, coroutine) tuples.
            return_exceptions: If True, exceptions are returned as results.

        Returns:
            Dictionary mapping task IDs to results.
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: dict[str, TaskResult[Any]] = {}

        async def run_task(task_id: str, coro: Any) -> TaskResult[Any]:
            async with semaphore:
                result: TaskResult[Any] = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.RUNNING,
                    start_time=time.time(),
                )
                try:
                    task_result = await asyncio.wait_for(coro, timeout=self.timeout)
                    result.result = task_result
                    result.status = TaskStatus.COMPLETED
                except TimeoutError as e:
                    result.error = e
                    result.status = TaskStatus.FAILED
                except Exception as e:
                    result.error = e
                    result.status = TaskStatus.FAILED
                finally:
                    result.end_time = time.time()
                return result

        # Create wrapped tasks
        wrapped_tasks = [run_task(task_id, coro) for task_id, coro in tasks]

        # Execute all concurrently
        task_results = await asyncio.gather(*wrapped_tasks, return_exceptions=True)

        # Map results
        for i, (task_id, _) in enumerate(tasks):
            task_result = task_results[i]
            if isinstance(task_result, BaseException):
                results[task_id] = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=task_result if isinstance(task_result, Exception) else None,
                )
            else:
                results[task_id] = task_result

        return results

    async def map(
        self,
        func: Callable[[Any], Any],
        items: list[Any],
        task_id_prefix: str = "task",
    ) -> dict[str, TaskResult]:
        """Apply a function to multiple items concurrently.

        Args:
            func: Async function to apply.
            items: Items to process.
            task_id_prefix: Prefix for generated task IDs.

        Returns:
            Dictionary mapping task IDs to results.
        """
        tasks = [(f"{task_id_prefix}_{i}", func(item)) for i, item in enumerate(items)]
        return await self.gather(tasks)
