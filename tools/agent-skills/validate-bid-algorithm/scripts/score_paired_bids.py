#!/usr/bin/env python3
"""Score champion and challenger on paired distinct-notice evidence."""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from validate_bid_evidence import canonical_sha256, validate_evidence


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot take percentile of an empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap_means(differences: list[float], samples: int, seed: int) -> list[float]:
    if not differences:
        return []
    if len(differences) == 1:
        return [differences[0]] * samples
    rng = random.Random(seed)
    size = len(differences)
    return [sum(differences[rng.randrange(size)] for _ in range(size)) / size for _ in range(samples)]


def _usable(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("included") is True
        and isinstance(record.get("primary_success"), bool)
        and isinstance(record.get("dropout"), bool)
    )


def _build_index(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (record["notice_id"], record["provider"])
        if key in index:
            raise ValueError(f"duplicate provider decision for notice: {key[0]} / {key[1]}")
        index[key] = record
    return index


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _score_segment(
    records: list[dict[str, Any]],
    champion: str,
    challenger: str,
    route: str,
    min_effect: float,
    minimum_paired_notices: int,
    coverage_noninferiority_margin: float,
    bootstrap_samples: int,
    seed: int,
    *,
    promotion_gate: bool,
    evaluation_split: str,
) -> dict[str, Any] | None:
    if route == "QUALIFICATION" and minimum_paired_notices < 400:
        raise ValueError(
            "QUALIFICATION promotion requires at least 400 clean distinct notices"
        )
    segment_records = [record for record in records if route == "ALL" or record["route"] == route]
    all_notices = sorted({record["notice_id"] for record in segment_records if record.get("included") is True})
    if not all_notices:
        return None
    index = _build_index(segment_records)
    champion_usable = {
        notice_id
        for notice_id in all_notices
        if _usable(index.get((notice_id, champion)))
    }
    challenger_usable = {
        notice_id
        for notice_id in all_notices
        if _usable(index.get((notice_id, challenger)))
    }
    intersection = sorted(champion_usable & challenger_usable)

    primary_differences: list[float] = []
    dropout_differences: list[float] = []
    profit_differences: list[float] = []
    champion_primary = 0
    challenger_primary = 0
    champion_dropout = 0
    challenger_dropout = 0
    for notice_id in intersection:
        champion_record = index[(notice_id, champion)]
        challenger_record = index[(notice_id, challenger)]
        champion_success = int(champion_record["primary_success"])
        challenger_success = int(challenger_record["primary_success"])
        champion_failed = int(champion_record["dropout"])
        challenger_failed = int(challenger_record["dropout"])
        champion_primary += champion_success
        challenger_primary += challenger_success
        champion_dropout += champion_failed
        challenger_dropout += challenger_failed
        primary_differences.append(float(challenger_success - champion_success))
        dropout_differences.append(float(challenger_failed - champion_failed))
        champion_profit = champion_record.get("realized_contribution_profit")
        challenger_profit = challenger_record.get("realized_contribution_profit")
        if isinstance(champion_profit, (int, float)) and isinstance(challenger_profit, (int, float)):
            profit_differences.append(float(challenger_profit - champion_profit))

    route_seed = seed + sum(ord(character) for character in route)
    primary_bootstrap = _bootstrap_means(primary_differences, bootstrap_samples, route_seed)
    dropout_bootstrap = _bootstrap_means(dropout_differences, bootstrap_samples, route_seed + 1)
    profit_bootstrap = _bootstrap_means(profit_differences, bootstrap_samples, route_seed + 2)
    paired_count = len(intersection)
    primary_delta = sum(primary_differences) / paired_count if paired_count else None
    dropout_delta = sum(dropout_differences) / paired_count if paired_count else None
    primary_ci = (
        [_percentile(primary_bootstrap, 0.025), _percentile(primary_bootstrap, 0.975)]
        if primary_bootstrap
        else [None, None]
    )
    dropout_upper = _percentile(dropout_bootstrap, 0.95) if dropout_bootstrap else None
    profit_ci = (
        [_percentile(profit_bootstrap, 0.025), _percentile(profit_bootstrap, 0.975)]
        if profit_bootstrap
        else [None, None]
    )

    full_champion_success = sum(
        int(index[(notice_id, champion)]["primary_success"])
        for notice_id in champion_usable
    )
    full_challenger_success = sum(
        int(index[(notice_id, challenger)]["primary_success"])
        for notice_id in challenger_usable
    )
    denominator = len(all_notices)
    primary_gate = primary_ci[0] is not None and primary_ci[0] > min_effect
    dropout_gate = (
        dropout_delta is not None
        and dropout_delta <= 0.0
        and dropout_upper is not None
        and dropout_upper <= 0.0
    )
    champion_coverage = len(champion_usable) / denominator
    challenger_coverage = len(challenger_usable) / denominator
    coverage_delta = challenger_coverage - champion_coverage
    coverage_gate = coverage_delta >= -coverage_noninferiority_margin
    sample_size_gate = paired_count >= minimum_paired_notices
    supported_route_gate = route != "UNSUPPORTED"
    result = {
        "evaluation_split": evaluation_split,
        "route": route,
        "eligible_distinct_notices": denominator,
        "paired_distinct_notices": paired_count,
        "coverage": {
            champion: _round(champion_coverage),
            challenger: _round(challenger_coverage),
            "challenger_minus_champion": _round(coverage_delta),
        },
        "intersection": {
            "primary_success_rate": {
                champion: _round(champion_primary / paired_count) if paired_count else None,
                challenger: _round(challenger_primary / paired_count) if paired_count else None,
            },
            "primary_paired_delta": _round(primary_delta),
            "primary_paired_95_ci": [_round(primary_ci[0]), _round(primary_ci[1])],
            "dropout_rate": {
                champion: _round(champion_dropout / paired_count) if paired_count else None,
                challenger: _round(challenger_dropout / paired_count) if paired_count else None,
            },
            "dropout_paired_delta": _round(dropout_delta),
            "dropout_delta_one_sided_95_upper": _round(dropout_upper),
            "profit_paired_count": len(profit_differences),
            "mean_profit_paired_delta": _round(
                sum(profit_differences) / len(profit_differences) if profit_differences else None
            ),
            "profit_paired_95_ci": [_round(profit_ci[0]), _round(profit_ci[1])],
        },
        "full_cohort_abstention_penalized": {
            "primary_success_rate": {
                champion: _round(full_champion_success / denominator),
                challenger: _round(full_challenger_success / denominator),
            }
        },
    }
    if promotion_gate:
        result["gate"] = {
            "evidence_split": "sealed_test",
            "minimum_primary_effect": min_effect,
            "minimum_paired_notices": minimum_paired_notices,
            "coverage_noninferiority_margin": coverage_noninferiority_margin,
            "primary_effect_pass": primary_gate,
            "dropout_noninferiority_pass": dropout_gate,
            "sample_size_pass": sample_size_gate,
            "coverage_noninferiority_pass": coverage_gate,
            "supported_route_pass": supported_route_gate,
            "pass": (
                primary_gate
                and dropout_gate
                and sample_size_gate
                and coverage_gate
                and supported_route_gate
            ),
        }
    else:
        result["interpretation"] = "diagnostic_only_not_eligible_for_promotion"
    return result


def score_document(
    document: dict[str, Any],
    frozen_manifest: dict[str, Any],
    champion: str,
    challenger: str,
    min_effect: float | None,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    if champion == challenger:
        raise ValueError("champion and challenger must be different")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")
    # manifest 는 독립 저장된 사전등록본이다. 이걸 빼고 문서에 든 값만 믿으면
    # 표본·코호트를 사후에 고쳐 놓고 채점해도 통과한다(MANIFEST_REQUIRED).
    evidence_findings = validate_evidence(document, frozen_manifest)
    if evidence_findings:
        first = evidence_findings[0]
        raise ValueError(
            f"evidence validation failed: {first.code} {first.location}: {first.message}"
        )
    experiment = document["experiment"]
    preregistered_min_effect = float(experiment["minimum_primary_effect"])
    if min_effect is not None and not math.isclose(
        min_effect,
        preregistered_min_effect,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            "--min-effect must match experiment.minimum_primary_effect; "
            "promotion gates cannot be changed after preregistration"
        )
    minimum_paired_notices = int(experiment["minimum_paired_notices"])
    coverage_margin = float(experiment["coverage_noninferiority_margin"])
    records = document["records"]
    _build_index(records)
    sealed_records = [record for record in records if record.get("split") == "sealed_test"]
    routes = sorted(
        {record["route"] for record in sealed_records if record.get("included") is True}
    )
    if not routes:
        raise ValueError("no included sealed_test records are available for promotion scoring")
    segments = []
    for route in routes:
        segment = _score_segment(
            sealed_records,
            champion,
            challenger,
            route,
            preregistered_min_effect,
            minimum_paired_notices,
            coverage_margin,
            bootstrap_samples,
            seed,
            promotion_gate=True,
            evaluation_split="sealed_test",
        )
        if segment is not None:
            segments.append(segment)

    diagnostics = []
    for split in ("train", "validation", "sealed_test"):
        split_records = [record for record in records if record.get("split") == split]
        diagnostic_routes = sorted(
            {record["route"] for record in split_records if record.get("included") is True}
        )
        for route in ["ALL", *diagnostic_routes]:
            diagnostic = _score_segment(
                split_records,
                champion,
                challenger,
                route,
                preregistered_min_effect,
                minimum_paired_notices,
                coverage_margin,
                bootstrap_samples,
                seed,
                promotion_gate=False,
                evaluation_split=split,
            )
            if diagnostic is not None:
                diagnostics.append(diagnostic)
    return {
        "schema_version": "1.0",
        "experiment_id": document["experiment"]["id"],
        "champion": champion,
        "challenger": challenger,
        "sample_unit": "distinct_notice",
        "bootstrap": {
            "method": "paired_percentile",
            "samples": bootstrap_samples,
            "seed": seed,
        },
        "promotion_scope": {
            "evaluation_split": "sealed_test",
            "aggregation": "route_specific_only",
            "train_and_validation_are_diagnostic_only": True,
        },
        "segments": segments,
        "diagnostic_cohorts": diagnostics,
    }


def _frozen_with_cohort(
    manifest: dict[str, Any], *entries: dict[str, Any]
) -> dict[str, Any]:
    """코호트를 추가한 manifest 사본. 문서의 `manifest_sha256` 도 함께 갱신해야 한다."""
    frozen = copy.deepcopy(manifest)
    frozen["cohort"].extend(copy.deepcopy(entry) for entry in entries)
    return frozen


def run_self_test() -> None:
    from validate_bid_evidence import _valid_fixture

    fixture, manifest = _valid_fixture()
    assert not validate_evidence(fixture, manifest), validate_evidence(fixture, manifest)
    first = score_document(fixture, manifest, "active", "dimatools", 0.1, 1000, 7)
    second = score_document(fixture, manifest, "active", "dimatools", 0.1, 1000, 7)
    assert first == second
    overall = first["segments"][0]
    assert overall["eligible_distinct_notices"] == 1
    assert overall["paired_distinct_notices"] == 1
    assert overall["intersection"]["primary_paired_delta"] == 1.0
    assert overall["gate"]["pass"] is True
    assert overall["gate"]["evidence_split"] == "sealed_test"
    assert all("gate" not in cohort for cohort in first["diagnostic_cohorts"])

    # validation split 이 증거에 섞여 있어도 승격 판정(segments)은 sealed_test 만 본다.
    # 코호트는 manifest 에 함께 얼려야 하고(그래야 사후 추가가 아니다), 시각만 옮기고
    # 결과 필드는 원본 그대로 둔다 — 여기서 rank·성공 여부를 지어내면 증거가 아니라 창작이다.
    contaminated = copy.deepcopy(fixture)
    for record in copy.deepcopy(fixture["records"]):
        record.update(
            {
                "notice_id": "N-VALIDATION",
                "split": "validation",
                "recommendation_at": "2026-01-01T01:00:00+09:00",
                "deadline_at": "2026-01-01T12:00:00+09:00",
                "information_cutoff_at": "2026-01-01T00:59:00+09:00",
                "observed_at": "2026-01-01T01:01:00+09:00",
                "feature_observed_at": ["2026-01-01T00:30:00+09:00"],
                "outcome_observed_at": "2026-01-01T13:00:00+09:00",
            }
        )
        contaminated["records"].append(record)
    contaminated["aggregation"].update(
        {"reported_sample_size": 2, "distinct_notice_count": 2, "raw_row_count": 4}
    )
    contaminated_manifest = _frozen_with_cohort(
        manifest,
        {
            "notice_id": "N-VALIDATION",
            "split": "validation",
            "included": True,
            "exclusion_reason": None,
        },
    )
    contaminated["experiment"]["manifest_sha256"] = canonical_sha256(contaminated_manifest)
    assert not validate_evidence(contaminated, contaminated_manifest), validate_evidence(
        contaminated, contaminated_manifest
    )
    contaminated_score = score_document(
        contaminated, contaminated_manifest, "active", "dimatools", 0.1, 1000, 7
    )
    assert contaminated_score["segments"] == first["segments"]
    assert any(
        cohort["evaluation_split"] == "validation"
        for cohort in contaminated_score["diagnostic_cohorts"]
    )

    # 사전등록 하한을 올리는 건 manifest 를 함께 올려야 성립한다 — 문서에서만 올리면
    # 사후 기준 변경이라 manifest 대조에서 걸린다.
    undersized = copy.deepcopy(fixture)
    undersized["experiment"]["minimum_paired_notices"] = 2
    undersized_manifest = copy.deepcopy(manifest)
    undersized_manifest["experiment"]["minimum_paired_notices"] = 2
    undersized["experiment"]["manifest_sha256"] = canonical_sha256(undersized_manifest)
    assert not validate_evidence(undersized, undersized_manifest), validate_evidence(
        undersized, undersized_manifest
    )
    undersized_score = score_document(
        undersized, undersized_manifest, "active", "dimatools", 0.1, 1000, 7
    )
    assert undersized_score["segments"][0]["gate"]["sample_size_pass"] is False
    assert undersized_score["segments"][0]["gate"]["pass"] is False

    coverage_loss = copy.deepcopy(fixture)
    champion_only = copy.deepcopy(fixture["records"][0])
    champion_only["notice_id"] = "N-002"
    champion_only["primary_success"] = False
    coverage_loss["records"].append(champion_only)
    coverage_loss["aggregation"].update(
        {"reported_sample_size": 2, "distinct_notice_count": 2, "raw_row_count": 3}
    )
    coverage_manifest = _frozen_with_cohort(
        manifest,
        {
            "notice_id": "N-002",
            "split": champion_only["split"],
            "included": True,
            "exclusion_reason": None,
        },
    )
    coverage_loss["experiment"]["manifest_sha256"] = canonical_sha256(coverage_manifest)
    assert not validate_evidence(coverage_loss, coverage_manifest), validate_evidence(
        coverage_loss, coverage_manifest
    )
    coverage_score = score_document(
        coverage_loss, coverage_manifest, "active", "dimatools", 0.1, 1000, 7
    )
    assert coverage_score["segments"][0]["gate"]["coverage_noninferiority_pass"] is False
    assert coverage_score["segments"][0]["gate"]["pass"] is False

    try:
        score_document(fixture, manifest, "active", "dimatools", 0.2, 1000, 7)
    except ValueError as exc:
        assert "must match" in str(exc)
    else:
        raise AssertionError("runtime minimum effect overrode the preregistered gate")
    duplicate = list(fixture["records"]) + [dict(fixture["records"][0])]
    try:
        _build_index(duplicate)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate provider-notice decision was accepted")
    print(
        "SELF-TEST PASS: sealed-only deterministic paired scoring, preregistered gates, "
        "coverage protection, and duplicate rejection"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", type=Path, help="validated evidence JSON file")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="independently stored frozen manifest JSON",
    )
    parser.add_argument("--champion", required=False, help="champion provider/strategy identifier")
    parser.add_argument("--challenger", required=False, help="challenger provider/strategy identifier")
    parser.add_argument(
        "--min-effect",
        type=float,
        default=None,
        help="optional assertion matching experiment.minimum_primary_effect",
    )
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--self-test", action="store_true", help="run embedded fixture tests")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.evidence is None or args.manifest is None or not args.champion or not args.challenger:
        parser.error(
            "evidence, --manifest, --champion, and --challenger are required unless --self-test is used"
        )
    try:
        document = json.loads(args.evidence.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    findings = validate_evidence(document, manifest)
    if findings:
        print("ERROR: evidence validation failed; score was not computed", file=sys.stderr)
        for finding in findings:
            print(f"{finding.code} {finding.location}: {finding.message}", file=sys.stderr)
        return 2
    try:
        result = score_document(
            document,
            manifest,
            args.champion,
            args.challenger,
            args.min_effect,
            args.bootstrap_samples,
            args.seed,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
