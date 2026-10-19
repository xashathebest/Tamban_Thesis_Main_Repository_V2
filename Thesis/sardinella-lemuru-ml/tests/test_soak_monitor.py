"""Short checks of soak-monitor sampling, not a soak test."""
from types import SimpleNamespace

from src.evaluation.soak_monitor import sample


def test_process_and_unreachable_http_are_reported():
    process = SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=123), cpu_percent=lambda: 12.0,
                              num_threads=lambda: 3, num_handles=lambda: 4)
    row = sample(process, "http://127.0.0.1:1/api/status/live")
    assert (row["rss_bytes"], row["cpu_percent"], row["threads"], row["handles_or_fds"]) == (123, 12.0, 3, 4)
    assert "http_error" in row and row["request_ms"] >= 0
