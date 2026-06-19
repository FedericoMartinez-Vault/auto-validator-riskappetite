"""Progress tracking, ETA estimation, and checkpoint logging for long test runs."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    if seconds < 0 or seconds == float("inf"):
        return "unknown"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class ProgressTracker:
    """Track per-test steps, elapsed time, ETA, and retries for a regression run."""

    def __init__(
        self,
        total_tests: int,
        log_path: Path,
        progress_path: Path,
        report_every: int = 10,
        initial_completed: int = 0,
    ) -> None:
        self.total_tests = total_tests
        self.log_path = log_path
        self.progress_path = progress_path
        self.report_every = report_every
        self.run_started = time.monotonic()
        self.completed_tests = initial_completed
        self.retry_count = 0
        self.test_durations: list[float] = []
        self.current_test_id = ""
        self.current_quote_no = ""
        self.current_step = "initializing"
        self.test_started: float | None = None

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{timestamp}] {message}"
        logger.info(message)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _avg_seconds_per_test(self) -> float:
        if not self.test_durations:
            return 0.0
        return sum(self.test_durations) / len(self.test_durations)

    def _eta_seconds(self) -> float:
        remaining = self.total_tests - self.completed_tests
        avg = self._avg_seconds_per_test()
        if avg <= 0 or remaining <= 0:
            return 0.0
        return avg * remaining

    def _snapshot(self) -> dict[str, Any]:
        elapsed = time.monotonic() - self.run_started
        return {
            "run_started_utc": datetime.fromtimestamp(
                time.time() - elapsed, tz=timezone.utc
            ).isoformat(),
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "total_tests": self.total_tests,
            "completed_tests": self.completed_tests,
            "remaining_tests": max(self.total_tests - self.completed_tests, 0),
            "current_test_id": self.current_test_id,
            "current_quote_no": self.current_quote_no,
            "current_step": self.current_step,
            "elapsed": _format_duration(elapsed),
            "elapsed_seconds": round(elapsed, 1),
            "eta": _format_duration(self._eta_seconds()),
            "eta_seconds": round(self._eta_seconds(), 1),
            "avg_seconds_per_test": round(self._avg_seconds_per_test(), 1),
            "retries_so_far": self.retry_count,
            "report_every": self.report_every,
        }

    def write_progress_file(self) -> None:
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        with self.progress_path.open("w", encoding="utf-8") as handle:
            json.dump(self._snapshot(), handle, indent=2, ensure_ascii=False)

    def log_run_start(self, agent_name: str, agent_id: str) -> None:
        self.run_started = time.monotonic()
        self._append_log(
            f"Run started | total_tests={self.total_tests} | agent={agent_name} ({agent_id})"
        )
        self.write_progress_file()

    def start_test(self, test_id: str, quote_no: str, index: int) -> None:
        self.current_test_id = test_id
        self.current_quote_no = quote_no
        self.test_started = time.monotonic()
        self.current_step = "starting_test"
        self._append_log(
            f"{test_id} ({index + 1}/{self.total_tests}) quote_no={quote_no} | step=start"
        )
        self.write_progress_file()

    def set_step(self, step: str) -> None:
        self.current_step = step
        elapsed_test = 0.0
        if self.test_started is not None:
            elapsed_test = time.monotonic() - self.test_started
        self._append_log(
            f"{self.current_test_id} quote_no={self.current_quote_no} | step={step} | "
            f"test_elapsed={_format_duration(elapsed_test)} | "
            f"run_elapsed={_format_duration(time.monotonic() - self.run_started)} | "
            f"eta={_format_duration(self._eta_seconds())}"
        )
        self.write_progress_file()

    def record_retry(self, attempt: int, max_attempts: int, error: str, wait_seconds: float) -> None:
        self.retry_count += 1
        self.current_step = f"retrying ({attempt}/{max_attempts})"
        self._append_log(
            f"{self.current_test_id} RETRY {attempt}/{max_attempts} | "
            f"error={error} | waiting={wait_seconds:.1f}s | "
            f"total_retries={self.retry_count}"
        )
        self.write_progress_file()

    def complete_test(
        self,
        parse_status: str,
        classification: str,
        error_message: str = "",
    ) -> None:
        if self.test_started is not None:
            self.test_durations.append(time.monotonic() - self.test_started)
        self.completed_tests += 1
        status = (
            f"parse_status={parse_status} classification={classification}"
            if not error_message
            else f"FAILED error={error_message}"
        )
        self._append_log(
            f"{self.current_test_id} DONE ({self.completed_tests}/{self.total_tests}) | "
            f"{status} | test_time={_format_duration(self.test_durations[-1])} | "
            f"run_elapsed={_format_duration(time.monotonic() - self.run_started)} | "
            f"eta={_format_duration(self._eta_seconds())}"
        )
        self.current_step = "test_complete"
        self.write_progress_file()

    def log_checkpoint(self, saved_files: list[str]) -> None:
        self._append_log(
            f"Checkpoint saved after {self.completed_tests}/{self.total_tests} tests | "
            f"files={', '.join(saved_files)}"
        )
        self.write_progress_file()

    def log_report_update(self, completed: int) -> None:
        self._append_log(
            f"Report package refreshed at {completed}/{self.total_tests} tests | "
            f"run_elapsed={_format_duration(time.monotonic() - self.run_started)} | "
            f"eta={_format_duration(self._eta_seconds())}"
        )
        self.write_progress_file()

    def eta_display(self) -> str:
        return _format_duration(self._eta_seconds())

    def should_refresh_report(self) -> bool:
        return self.completed_tests > 0 and self.completed_tests % self.report_every == 0

    def log_run_complete(self) -> None:
        elapsed = time.monotonic() - self.run_started
        self._append_log(
            f"Run complete | tests={self.completed_tests}/{self.total_tests} | "
            f"total_time={_format_duration(elapsed)} | retries={self.retry_count}"
        )
        self.current_step = "complete"
        self.write_progress_file()
