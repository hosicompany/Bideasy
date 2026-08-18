from datetime import datetime

from scripts import repair_mock_bid_participant_snapshots as repair


def _crawl_result(*, rejected=0, ok=True, participant_ok=True, **overrides):
    result = {
        "ok": ok,
        "participant_ok": participant_ok,
        "failed_windows": [],
        "participant_errors": 0,
        "participant_axis_rejected": rejected,
    }
    result.update(overrides)
    return result


def test_axis_rejection_retries_and_stops_after_recovery(monkeypatch):
    results = [_crawl_result(rejected=3), _crawl_result(rejected=0)]
    calls = []

    def fake_crawl(*, windows, max_pages):
        calls.append((windows, max_pages))
        return results[len(calls) - 1]

    monkeypatch.setattr(repair, "crawl_recent_openings", fake_crawl)
    windows = [(datetime(2026, 8, 4), datetime(2026, 8, 4, 23, 59))]

    attempts = repair._crawl_with_axis_retries(
        windows=windows,
        max_pages=250,
        max_attempts=3,
    )

    assert attempts == results
    assert calls == [(windows, 250), (windows, 250)]


def test_axis_rejection_stops_at_attempt_limit(monkeypatch):
    result = _crawl_result(rejected=1)
    calls = 0

    def fake_crawl(**_kwargs):
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(repair, "crawl_recent_openings", fake_crawl)

    attempts = repair._crawl_with_axis_retries([], max_pages=250, max_attempts=2)

    assert attempts == [result, result]
    assert calls == 2


def test_structural_failure_is_not_retried(monkeypatch):
    result = _crawl_result(
        rejected=4,
        participant_ok=False,
        participant_structural_errors=1,
    )
    calls = 0

    def fake_crawl(**_kwargs):
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(repair, "crawl_recent_openings", fake_crawl)

    attempts = repair._crawl_with_axis_retries([], max_pages=250, max_attempts=3)

    assert attempts == [result]
    assert calls == 1
