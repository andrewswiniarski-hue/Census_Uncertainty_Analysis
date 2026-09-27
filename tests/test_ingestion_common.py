"""Tests for ingestion/_common.py's download_with_retry.

Run:
    python -m pytest tests/test_ingestion_common.py -v

No network: the download function is a fake, and sleep is captured, not taken.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INGESTION = REPO_ROOT / "ingestion"
if str(INGESTION) not in sys.path:
    sys.path.insert(0, str(INGESTION))

from _common import download_with_retry  # noqa: E402


class FlakyDownload:
    """Fails the first `failures` calls, then returns a value, recording every call."""

    def __init__(self, failures: int, error: Exception | None = None):
        self.failures = failures
        self.error = error or RuntimeError("Unable to get metadata on the variable B01001_015M")
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if len(self.calls) <= self.failures:
            raise self.error
        return "frame"


def _run(fn, **kw):
    sleeps: list[float] = []
    logs: list[str] = []
    result = download_with_retry(fn, "acs/acs5", 2024, sleep=sleeps.append, log=logs.append, **kw)
    return result, sleeps, logs


def test_first_try_success_does_not_sleep():
    fn = FlakyDownload(failures=0)
    result, sleeps, logs = _run(fn)
    assert result == "frame"
    assert len(fn.calls) == 1
    assert sleeps == [] and logs == []


def test_recovers_after_intermittent_failures_with_doubling_delays():
    fn = FlakyDownload(failures=2)
    result, sleeps, logs = _run(fn, attempts=5, base_delay=2.0)
    assert result == "frame"
    assert len(fn.calls) == 3
    assert sleeps == [2.0, 4.0]
    assert len(logs) == 2 and "attempt 1 of 5" in logs[0]


def test_reraises_the_original_error_after_the_last_attempt():
    err = ValueError("genuinely bad request")
    fn = FlakyDownload(failures=99, error=err)
    with pytest.raises(ValueError, match="genuinely bad request"):
        _run(fn, attempts=3)
    assert len(fn.calls) == 3


def test_arguments_pass_through_unchanged():
    fn = FlakyDownload(failures=1)
    _run(fn, download_variables=["NAME", "B19013_001E"], api_key="k", state="*")
    assert fn.calls[-1] == (("acs/acs5", 2024),
                            {"download_variables": ["NAME", "B19013_001E"], "api_key": "k", "state": "*"})


def test_rejects_zero_attempts():
    with pytest.raises(ValueError):
        download_with_retry(FlakyDownload(0), attempts=0)
