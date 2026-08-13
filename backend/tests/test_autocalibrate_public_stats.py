"""Public performance history must not include unpromoted candidates."""

from dataclasses import replace
from pathlib import Path

from app.services.autocalibrate.strategy_store import StrategyVersion


def test_public_weekly_metrics_exclude_candidates(client, monkeypatch):
    active = StrategyVersion(
        version_id="active",
        created_at="2026-01-01T00:00:00",
        params={},
        status="active",
        metrics={"pass_rate": 91.0},
        candidate_id="candidate-1",
        gate_decision_id="gate-1",
        approval_id="approval-1",
        data_manifest_hash="a" * 64,
        code_sha="abcdef1",
        route="QUALIFICATION",
    )
    archived_one = replace(
        active,
        version_id="archived-1",
        created_at="2025-12-01T00:00:00",
        status="archived",
        metrics={"pass_rate": 89.0},
    )
    archived_two = replace(
        active,
        version_id="archived-2",
        created_at="2025-12-15T00:00:00",
        status="archived",
        metrics={"pass_rate": 90.0},
    )
    candidate = replace(
        active,
        version_id="candidate",
        created_at="2026-02-01T00:00:00",
        status="candidate",
        metrics={"pass_rate": 99.9},
    )

    class Store:
        @staticmethod
        def load_active():
            return active

        @staticmethod
        def list_versions():
            return [archived_one, archived_two, active, candidate]

    monkeypatch.setattr(
        "app.services.autocalibrate.strategy_store.get_default_store",
        lambda: Store(),
    )

    response = client.get("/api/v1/autocalibrate/stats")

    assert response.status_code == 200
    assert response.json()["weekly"] == [89.0, 90.0, 91.0]
    assert 99.9 not in response.json()["weekly"]


def test_public_stats_do_not_invent_default_performance_or_double_count(
    client, monkeypatch
):
    load_kwargs = {}

    class UnavailableStore:
        @staticmethod
        def load_active():
            raise OSError("missing")

    monkeypatch.setattr(
        "app.services.autocalibrate.strategy_store.get_default_store",
        lambda: UnavailableStore(),
    )
    def load_verified_records(**kwargs):
        load_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(
        "app.services.autocalibrate.dataset.load_records",
        load_verified_records,
    )

    payload = client.get("/api/v1/autocalibrate/stats").json()

    assert payload["passRate"] is None
    assert payload["dropRate"] is None
    assert payload["dataCount"] == 0
    assert payload["evidenceStatus"] == "NOT_VERIFIED"
    assert load_kwargs["require_observation_time"] is True


def test_public_stats_hide_legacy_active_metrics_without_evidence_lineage(
    client, monkeypatch
):
    legacy = StrategyVersion(
        version_id="legacy-active",
        created_at="2025-01-01T00:00:00",
        params={},
        status="active",
        metrics={"pass_rate": 99.9},
    )

    class Store:
        @staticmethod
        def load_active():
            return legacy

        @staticmethod
        def list_versions():
            return [legacy]

    monkeypatch.setattr(
        "app.services.autocalibrate.strategy_store.get_default_store",
        lambda: Store(),
    )
    monkeypatch.setattr(
        "app.services.autocalibrate.dataset.load_records",
        lambda **_kwargs: [],
    )

    payload = client.get("/api/v1/autocalibrate/stats").json()

    assert payload["passRate"] is None
    assert payload["dropRate"] is None
    assert payload["weekly"] is None
    assert payload["evidenceStatus"] == "NOT_VERIFIED"


def test_public_pages_do_not_embed_legacy_unverified_performance_claims():
    html_root = Path(__file__).parents[2] / "infra" / "nginx" / "html"
    landing = (html_root / "index.html").read_text(encoding="utf-8")
    dashboard = (html_root / "dashboard.html").read_text(encoding="utf-8")

    assert "94.9" not in landing
    assert "5.1%" not in landing
    assert "4,848" not in landing
    assert "94.9" not in dashboard
    assert "검증 대기" in landing
