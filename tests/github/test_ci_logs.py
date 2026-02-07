"""Tests for CI log downloader."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.ci_logs import CIJob, CILogDownloader, ErrorBlock
from claude_task_master.github.exceptions import GitHubError, GitHubTimeoutError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def ci_downloader():
    """Create a CILogDownloader instance."""
    return CILogDownloader(repo="owner/repo", timeout=60)


@pytest.fixture
def sample_jobs_response():
    """Sample API response for jobs list."""
    return {
        "jobs": [
            {
                "id": 1,
                "name": "Lint",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "id": 2,
                "name": "Test",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 3,
                "name": "Build",
                "status": "completed",
                "conclusion": "cancelled",
            },
        ]
    }


@pytest.fixture
def sample_log_content():
    """Sample CI log content with errors."""
    return """2026-02-07T10:00:00Z Setup environment
2026-02-07T10:00:01Z Installing dependencies
2026-02-07T10:00:02Z Running tests
2026-02-07T10:00:03Z ##[error]Test failed: expected 200 got 500
2026-02-07T10:00:04Z Exit status 1
2026-02-07T10:00:05Z ##[error]Process completed with exit code 1
2026-02-07T10:00:06Z Cleanup
"""


# =============================================================================
# CILogDownloader.get_failed_jobs Tests
# =============================================================================


class TestGetFailedJobs:
    """Tests for getting failed jobs."""

    def test_get_failed_jobs_success(self, ci_downloader, sample_jobs_response):
        """Test successful retrieval of failed jobs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(sample_jobs_response),
                stderr="",
            )

            failed_jobs = ci_downloader.get_failed_jobs(run_id=123)

            assert len(failed_jobs) == 2
            assert failed_jobs[0].id == 1
            assert failed_jobs[0].name == "Lint"
            assert failed_jobs[0].conclusion == "failure"
            assert failed_jobs[1].id == 3
            assert failed_jobs[1].name == "Build"
            assert failed_jobs[1].conclusion == "cancelled"

    def test_get_failed_jobs_no_failures(self, ci_downloader):
        """Test when no jobs failed."""
        response = {
            "jobs": [
                {
                    "id": 1,
                    "name": "Test",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )

            failed_jobs = ci_downloader.get_failed_jobs(run_id=123)

            assert len(failed_jobs) == 0

    def test_get_failed_jobs_timeout(self, ci_downloader):
        """Test timeout when getting jobs."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh api", timeout=60)

            with pytest.raises(GitHubTimeoutError, match="Timeout getting jobs"):
                ci_downloader.get_failed_jobs(run_id=123)

    def test_get_failed_jobs_api_error(self, ci_downloader):
        """Test API error when getting jobs."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd="gh api",
                stderr="API rate limit exceeded",
            )

            with pytest.raises(GitHubError, match="Failed to get jobs"):
                ci_downloader.get_failed_jobs(run_id=123)

    def test_get_failed_jobs_includes_timed_out(self, ci_downloader):
        """Test that timed_out jobs are included in failed jobs."""
        response = {
            "jobs": [
                {
                    "id": 1,
                    "name": "LongTest",
                    "status": "completed",
                    "conclusion": "timed_out",
                }
            ]
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )

            failed_jobs = ci_downloader.get_failed_jobs(run_id=123)

            assert len(failed_jobs) == 1
            assert failed_jobs[0].conclusion == "timed_out"


# =============================================================================
# CILogDownloader.download_job_logs Tests
# =============================================================================


class TestDownloadJobLogs:
    """Tests for downloading job logs."""

    def test_download_job_logs_success(self, ci_downloader, sample_log_content):
        """Test successful log download."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=sample_log_content.encode("utf-8"),
                stderr=b"",
            )

            logs = ci_downloader.download_job_logs(job_id=123)

            assert "##[error]Test failed" in logs
            assert "Exit status 1" in logs
            assert len(logs) > 0

    def test_download_job_logs_empty(self, ci_downloader):
        """Test when logs are empty."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"",
                stderr=b"",
            )

            with pytest.raises(GitHubError, match="No log content available"):
                ci_downloader.download_job_logs(job_id=123)

    def test_download_job_logs_timeout(self, ci_downloader):
        """Test timeout when downloading logs."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh api", timeout=60)

            with pytest.raises(GitHubTimeoutError, match="Timeout downloading logs"):
                ci_downloader.download_job_logs(job_id=123)

    def test_download_job_logs_api_error(self, ci_downloader):
        """Test API error when downloading logs."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd="gh api",
                stderr="Not found",
            )

            with pytest.raises(GitHubError, match="Failed to download job logs"):
                ci_downloader.download_job_logs(job_id=123)

    def test_download_job_logs_encoding_errors(self, ci_downloader):
        """Test handling of encoding errors in logs."""
        # Binary content that's not valid UTF-8
        invalid_utf8 = b"Valid text \xff\xfe Invalid bytes"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=invalid_utf8,
                stderr=b"",
            )

            logs = ci_downloader.download_job_logs(job_id=123)

            # Should handle gracefully with replacement characters
            assert "Valid text" in logs
            assert len(logs) > 0


# =============================================================================
# CILogDownloader.extract_error_blocks Tests
# =============================================================================


class TestExtractErrorBlocks:
    """Tests for extracting error blocks."""

    def test_extract_error_blocks_basic(self, ci_downloader):
        """Test basic error extraction."""
        logs = """Line 1
Line 2
Line 3
##[error]Error here
Line 5
Line 6
Line 7
"""
        error_blocks = ci_downloader.extract_error_blocks(logs, context_lines=1)

        assert len(error_blocks) == 1
        assert "##[error]Error here" in error_blocks[0].content
        assert "Line 3" in error_blocks[0].content
        assert "Line 5" in error_blocks[0].content
        assert error_blocks[0].line_number == 4

    def test_extract_error_blocks_multiple(self, ci_downloader):
        """Test extracting multiple error blocks."""
        logs = """Line 1
##[error]First error
Line 3
Line 4
Exit status 1
Line 6
"""
        error_blocks = ci_downloader.extract_error_blocks(logs, context_lines=0)

        assert len(error_blocks) == 2
        assert "First error" in error_blocks[0].content
        assert "Exit status 1" in error_blocks[1].content

    def test_extract_error_blocks_no_errors(self, ci_downloader):
        """Test when no errors found."""
        logs = """Line 1
Line 2
Line 3
Success
"""
        error_blocks = ci_downloader.extract_error_blocks(logs)

        assert len(error_blocks) == 0

    def test_extract_error_blocks_context(self, ci_downloader):
        """Test context lines extraction."""
        logs = """Line 1
Line 2
Line 3
##[error]Error
Line 5
Line 6
Line 7
"""
        error_blocks = ci_downloader.extract_error_blocks(logs, context_lines=2)

        assert len(error_blocks) == 1
        block = error_blocks[0]
        assert "Line 2" in block.content
        assert "Line 3" in block.content
        assert "##[error]Error" in block.content
        assert "Line 5" in block.content
        assert "Line 6" in block.content
        assert block.context_before == 2
        assert block.context_after == 2

    def test_extract_error_blocks_at_start(self, ci_downloader):
        """Test error at start of logs."""
        logs = """##[error]Error at start
Line 2
Line 3
"""
        error_blocks = ci_downloader.extract_error_blocks(logs, context_lines=2)

        assert len(error_blocks) == 1
        block = error_blocks[0]
        assert block.context_before == 0  # No lines before
        assert "Line 2" in block.content

    def test_extract_error_blocks_at_end(self, ci_downloader):
        """Test error at end of logs."""
        logs = """Line 1
Line 2
##[error]Error at end"""
        error_blocks = ci_downloader.extract_error_blocks(logs, context_lines=2)

        assert len(error_blocks) == 1
        block = error_blocks[0]
        assert "Line 1" in block.content
        assert block.context_after == 0  # No lines after

    def test_is_error_line_various_formats(self, ci_downloader):
        """Test error detection with various formats."""
        assert ci_downloader._is_error_line("##[error]Something")
        assert ci_downloader._is_error_line("Exit status 1")
        assert ci_downloader._is_error_line("Error: something failed")
        assert ci_downloader._is_error_line("error: lowercase")
        assert ci_downloader._is_error_line("ERROR: uppercase")
        assert ci_downloader._is_error_line("FAIL some test")
        assert ci_downloader._is_error_line("Failed to build")
        assert ci_downloader._is_error_line("AssertionError: expected X")
        assert not ci_downloader._is_error_line("Success")
        assert not ci_downloader._is_error_line("Normal log line")


# =============================================================================
# CILogDownloader.download_failed_run_logs Tests
# =============================================================================


class TestDownloadFailedRunLogs:
    """Tests for downloading all failed run logs."""

    def test_download_failed_run_logs_success(
        self, ci_downloader, sample_jobs_response, sample_log_content, tmp_path
    ):
        """Test successful download of all failed job logs."""
        with patch("subprocess.run") as mock_run:
            # First call: get jobs
            # Subsequent calls: download logs
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_jobs_response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
            ]

            logs = ci_downloader.download_failed_run_logs(run_id=123, output_dir=tmp_path)

            assert len(logs) == 2
            assert "Lint" in logs
            assert "Build" in logs
            assert "##[error]" in logs["Lint"]

            # Check chunked directories were created
            lint_dir = tmp_path / "Lint"
            build_dir = tmp_path / "Build"
            assert lint_dir.exists()
            assert build_dir.exists()

            # Check log files were created (should be 1.log since content is small)
            assert (lint_dir / "1.log").exists()
            assert (build_dir / "1.log").exists()

    def test_download_failed_run_logs_no_output_dir(
        self, ci_downloader, sample_jobs_response, sample_log_content
    ):
        """Test download without saving to files."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_jobs_response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
            ]

            logs = ci_downloader.download_failed_run_logs(run_id=123)

            assert len(logs) == 2
            assert "Lint" in logs

    def test_download_failed_run_logs_no_failures(self, ci_downloader):
        """Test when no jobs failed."""
        response: dict[str, list] = {"jobs": []}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )

            logs = ci_downloader.download_failed_run_logs(run_id=123)

            assert len(logs) == 0

    def test_download_failed_run_logs_partial_failure(
        self, ci_downloader, sample_jobs_response, sample_log_content
    ):
        """Test when one job log download fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_jobs_response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
                subprocess.CalledProcessError(returncode=1, cmd="gh api", stderr="Error"),
            ]

            logs = ci_downloader.download_failed_run_logs(run_id=123)

            # Should still get the successful one
            assert len(logs) == 1
            assert "Lint" in logs

    def test_download_failed_run_logs_sanitizes_filenames(
        self, ci_downloader, sample_log_content, tmp_path
    ):
        """Test that job names are sanitized for filenames."""
        response = {
            "jobs": [
                {
                    "id": 1,
                    "name": "Test / Linux",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ]
        }

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
            ]

            ci_downloader.download_failed_run_logs(run_id=123, output_dir=tmp_path)

            # Slash should be replaced with underscore
            sanitized_dir = tmp_path / "Test___Linux"
            assert sanitized_dir.exists()
            assert (sanitized_dir / "1.log").exists()

    def test_download_failed_run_logs_chunks_large_logs(
        self, ci_downloader, sample_jobs_response, tmp_path
    ):
        """Test that large logs are split into chunks."""
        # Create log with 1200 lines (should split into 3 files with max 500 lines)
        large_log = "\n".join([f"Line {i}" for i in range(1200)])

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_jobs_response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=large_log.encode("utf-8"),
                    stderr=b"",
                ),
                MagicMock(
                    returncode=0,
                    stdout=large_log.encode("utf-8"),
                    stderr=b"",
                ),
            ]

            ci_downloader.download_failed_run_logs(
                run_id=123, output_dir=tmp_path, max_lines_per_file=500
            )

            # Check that Lint job created 3 chunks
            lint_dir = tmp_path / "Lint"
            assert (lint_dir / "1.log").exists()
            assert (lint_dir / "2.log").exists()
            assert (lint_dir / "3.log").exists()

            # Verify line counts (count actual lines, not newlines)
            chunk1_content = (lint_dir / "1.log").read_text()
            chunk2_content = (lint_dir / "2.log").read_text()
            chunk3_content = (lint_dir / "3.log").read_text()

            # Each chunk should have roughly 500 lines
            assert 490 <= len(chunk1_content.splitlines()) <= 500
            assert 490 <= len(chunk2_content.splitlines()) <= 500
            assert 190 <= len(chunk3_content.splitlines()) <= 210  # Remaining lines

    def test_save_logs_chunked_preserves_content(self, ci_downloader, tmp_path):
        """Test that chunking preserves complete log content."""
        logs = "\n".join([f"Line {i}" for i in range(100)])

        ci_downloader._save_logs_chunked(
            logs=logs,
            job_name="Test",
            output_dir=tmp_path,
            max_lines_per_file=30,
        )

        # Read all chunks back
        test_dir = tmp_path / "Test"
        chunk1 = (test_dir / "1.log").read_text()
        chunk2 = (test_dir / "2.log").read_text()
        chunk3 = (test_dir / "3.log").read_text()
        chunk4 = (test_dir / "4.log").read_text()

        # Combine and verify - remove trailing newline for comparison
        combined = (chunk1 + chunk2 + chunk3 + chunk4).rstrip("\n")
        assert combined == logs


# =============================================================================
# CILogDownloader.get_error_summary Tests
# =============================================================================


class TestGetErrorSummary:
    """Tests for error summary generation."""

    def test_get_error_summary_success(
        self, ci_downloader, sample_jobs_response, sample_log_content
    ):
        """Test error summary generation."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_jobs_response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
                MagicMock(
                    returncode=0,
                    stdout=sample_log_content.encode("utf-8"),
                    stderr=b"",
                ),
            ]

            summary = ci_downloader.get_error_summary(run_id=123, max_errors_per_job=3)

            assert "Failed jobs: 2" in summary
            assert "## Lint" in summary
            assert "## Build" in summary
            assert "##[error]" in summary

    def test_get_error_summary_no_failures(self, ci_downloader):
        """Test summary when no failures."""
        response: dict[str, list] = {"jobs": []}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )

            summary = ci_downloader.get_error_summary(run_id=123)

            assert "No failed jobs found" in summary

    def test_get_error_summary_limits_errors(self, ci_downloader, sample_jobs_response):
        """Test that summary limits number of errors shown."""
        # Log with many errors
        logs_with_many_errors = "\n".join([f"##[error]Error {i}" for i in range(10)])

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_jobs_response),
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout=logs_with_many_errors.encode("utf-8"),
                    stderr=b"",
                ),
                MagicMock(
                    returncode=0,
                    stdout=logs_with_many_errors.encode("utf-8"),
                    stderr=b"",
                ),
            ]

            summary = ci_downloader.get_error_summary(run_id=123, max_errors_per_job=2)

            # Should mention that there are more errors
            assert "... and" in summary
            assert "more errors" in summary


# =============================================================================
# CIJob dataclass Tests
# =============================================================================


class TestCIJob:
    """Tests for CIJob dataclass."""

    def test_cijob_creation(self):
        """Test creating a CIJob instance."""
        job = CIJob(
            id=123,
            name="Test",
            status="completed",
            conclusion="failure",
            run_id=456,
        )

        assert job.id == 123
        assert job.name == "Test"
        assert job.status == "completed"
        assert job.conclusion == "failure"
        assert job.run_id == 456


# =============================================================================
# ErrorBlock dataclass Tests
# =============================================================================


class TestErrorBlock:
    """Tests for ErrorBlock dataclass."""

    def test_error_block_creation(self):
        """Test creating an ErrorBlock instance."""
        block = ErrorBlock(
            content="Error content",
            line_number=10,
            context_before=3,
            context_after=3,
        )

        assert block.content == "Error content"
        assert block.line_number == 10
        assert block.context_before == 3
        assert block.context_after == 3
