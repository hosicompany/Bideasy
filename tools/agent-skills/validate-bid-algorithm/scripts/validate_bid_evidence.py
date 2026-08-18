#!/usr/bin/env python3
"""Validate time-safe, notice-level bid algorithm evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
CODE_SHA = re.compile(r"^[0-9a-f]{7,64}$")
ROUTES = {"PRICE_DOMINANT", "QUALIFICATION", "COMPREHENSIVE", "NEGOTIATION", "UNSUPPORTED"}
PROVIDER_KINDS = {"internal", "competitor", "user_baseline"}
SPLITS = {"train", "validation", "sealed_test"}
ROOT_FIELDS = {"schema_version", "experiment", "aggregation", "records"}
MANIFEST_EXPERIMENT_FIELDS = {
    "id",
    "route",
    "primary_metric",
    "champion_provider",
    "challenger_provider",
    "candidate_id",
    "code_sha",
    "data_manifest_hash",
    "training_cutoff_at",
    "candidate_selected_at",
    "sealed_test_opened_at",
    "minimum_primary_effect",
    "minimum_paired_notices",
    "coverage_noninferiority_margin",
    "basis_ratio_min",
    "basis_ratio_max",
    "formula_hash",
    "competitor_providers",
    "allowed_exclusion_reasons",
}
EXPERIMENT_FIELDS = MANIFEST_EXPERIMENT_FIELDS | {"manifest_sha256"}
MANIFEST_ROOT_FIELDS = {"schema_version", "experiment", "cohort"}
COHORT_FIELDS = {"notice_id", "split", "included", "exclusion_reason"}
AGGREGATION_FIELDS = {"sample_unit", "reported_sample_size", "distinct_notice_count", "raw_row_count"}
RECORD_FIELDS = {
    "notice_id",
    "route",
    "provider",
    "provider_kind",
    "split",
    "recommendation_at",
    "deadline_at",
    "information_cutoff_at",
    "observed_at",
    "feature_observed_at",
    "outcome_observed_at",
    "used_for_training",
    "basic_price",
    "reserved_price",
    "recommendation_price",
    "actual_lower_limit_price",
    "winner_price",
    "included",
    "exclusion_reason",
    "bid_valid",
    "rank",
    "rank_population",
    "valid_participant_count",
    "formula_hash",
    "artifact_sha256",
    "primary_success",
    "dropout",
    "realized_contribution_profit",
}


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    location: str
    message: str


def _finding(code: str, location: str, message: str) -> Finding:
    return Finding(code=code, location=location, message=message)


def _parse_time(value: Any, location: str, findings: list[Finding], nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        findings.append(_finding("TIMESTAMP", location, "must be an RFC 3339 string with an explicit UTC offset"))
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        findings.append(_finding("TIMESTAMP", location, "invalid RFC 3339 timestamp"))
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        findings.append(_finding("TIMESTAMP", location, "timestamp must include a UTC offset"))
        return None
    return parsed


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _remember_notice_fact(
    facts: dict[str, dict[str, set[Any]]],
    notice_id: str,
    field: str,
    value: Any,
) -> None:
    """Record a validated, hashable notice-level fact for cross-provider checks."""
    facts[notice_id][field].add(value)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_frozen_manifest(
    manifest: Any,
    findings: list[Finding],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str | None]:
    if not isinstance(manifest, dict):
        findings.append(
            _finding(
                "MANIFEST_REQUIRED",
                "$manifest",
                "an independently stored frozen manifest object is required",
            )
        )
        return {}, {}, None
    for field in sorted(MANIFEST_ROOT_FIELDS - set(manifest)):
        findings.append(_finding("REQUIRED", "$manifest", f"missing manifest field: {field}"))
    for field in sorted(set(manifest) - MANIFEST_ROOT_FIELDS):
        findings.append(_finding("UNKNOWN_FIELD", f"$manifest.{field}", "unknown manifest field"))
    if manifest.get("schema_version") != "1.0":
        findings.append(_finding("VERSION", "$manifest.schema_version", "must equal 1.0"))

    experiment = manifest.get("experiment")
    if not isinstance(experiment, dict):
        findings.append(_finding("TYPE", "$manifest.experiment", "must be an object"))
        experiment = {}
    for field in sorted(MANIFEST_EXPERIMENT_FIELDS - set(experiment)):
        findings.append(
            _finding("REQUIRED", "$manifest.experiment", f"missing manifest experiment field: {field}")
        )
    for field in sorted(set(experiment) - MANIFEST_EXPERIMENT_FIELDS):
        findings.append(
            _finding("UNKNOWN_FIELD", f"$manifest.experiment.{field}", "unknown manifest experiment field")
        )

    allowed_value = experiment.get("allowed_exclusion_reasons")
    if not isinstance(allowed_value, list) or any(
        not isinstance(reason, str) or not reason for reason in allowed_value
    ):
        findings.append(
            _finding(
                "EXCLUSION_CONTRACT",
                "$manifest.experiment.allowed_exclusion_reasons",
                "must be an array of non-empty reason codes",
            )
        )
        allowed_reasons: set[str] = set()
    else:
        allowed_reasons = set(allowed_value)
        if len(allowed_reasons) != len(allowed_value):
            findings.append(
                _finding(
                    "EXCLUSION_CONTRACT",
                    "$manifest.experiment.allowed_exclusion_reasons",
                    "must not contain duplicates",
                )
            )

    cohort = manifest.get("cohort")
    if not isinstance(cohort, list):
        findings.append(_finding("TYPE", "$manifest.cohort", "must be an array"))
        cohort = []
    cohort_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(cohort):
        location = f"$manifest.cohort[{index}]"
        if not isinstance(item, dict):
            findings.append(_finding("TYPE", location, "cohort entry must be an object"))
            continue
        for field in sorted(COHORT_FIELDS - set(item)):
            findings.append(_finding("REQUIRED", location, f"missing cohort field: {field}"))
        for field in sorted(set(item) - COHORT_FIELDS):
            findings.append(_finding("UNKNOWN_FIELD", f"{location}.{field}", "unknown cohort field"))
        notice_id = item.get("notice_id")
        if not isinstance(notice_id, str) or not notice_id.strip():
            findings.append(_finding("NOTICE_ID", f"{location}.notice_id", "must be a non-empty string"))
            continue
        if notice_id in cohort_by_id:
            findings.append(_finding("DUPLICATE_NOTICE", location, f"duplicate frozen notice: {notice_id}"))
        cohort_by_id[notice_id] = item
        split = item.get("split")
        if split not in SPLITS:
            findings.append(_finding("SPLIT", f"{location}.split", "must be train, validation, or sealed_test"))
        included = item.get("included")
        exclusion_reason = item.get("exclusion_reason")
        if not isinstance(included, bool):
            findings.append(_finding("TYPE", f"{location}.included", "must be boolean"))
        elif included and exclusion_reason is not None:
            findings.append(_finding("EXCLUSION_CONTRACT", location, "included notice cannot have an exclusion reason"))
        elif not included and exclusion_reason not in allowed_reasons:
            findings.append(
                _finding(
                    "EXCLUSION_CONTRACT",
                    f"{location}.exclusion_reason",
                    "excluded notice must use a frozen allowed exclusion reason",
                )
            )
    return experiment, cohort_by_id, canonical_sha256(manifest)


def validate_evidence(document: Any, frozen_manifest: Any = None) -> list[Finding]:
    findings: list[Finding] = []
    manifest_experiment, frozen_cohort, frozen_manifest_hash = _validate_frozen_manifest(
        frozen_manifest,
        findings,
    )
    if not isinstance(document, dict):
        return [_finding("TYPE", "$", "evidence must be a JSON object")]
    for field in sorted(ROOT_FIELDS - set(document)):
        findings.append(_finding("REQUIRED", "$", f"missing root field: {field}"))
    for field in sorted(set(document) - ROOT_FIELDS):
        findings.append(_finding("UNKNOWN_FIELD", f"$.{field}", "unknown root field"))
    if document.get("schema_version") != "1.0":
        findings.append(_finding("VERSION", "$.schema_version", "must equal 1.0"))

    experiment = document.get("experiment")
    if not isinstance(experiment, dict):
        findings.append(_finding("TYPE", "$.experiment", "must be an object"))
        experiment = {}
    for field in sorted(EXPERIMENT_FIELDS - set(experiment)):
        findings.append(_finding("REQUIRED", "$.experiment", f"missing experiment field: {field}"))
    for field in sorted(set(experiment) - EXPERIMENT_FIELDS):
        findings.append(_finding("UNKNOWN_FIELD", f"$.experiment.{field}", "unknown experiment field"))
    manifest_reference = experiment.get("manifest_sha256")
    if not isinstance(manifest_reference, str) or not SHA256.fullmatch(manifest_reference):
        findings.append(
            _finding(
                "MANIFEST_HASH",
                "$.experiment.manifest_sha256",
                "must be lowercase SHA-256 hex",
            )
        )
    elif frozen_manifest_hash is not None and manifest_reference != frozen_manifest_hash:
        findings.append(
            _finding(
                "MANIFEST_HASH",
                "$.experiment.manifest_sha256",
                "does not match the independently loaded frozen manifest",
            )
        )
    for field in sorted(MANIFEST_EXPERIMENT_FIELDS):
        if field in experiment and field in manifest_experiment and experiment[field] != manifest_experiment[field]:
            findings.append(
                _finding(
                    "MANIFEST_MISMATCH",
                    f"$.experiment.{field}",
                    "differs from the independently loaded frozen manifest",
                )
            )

    experiment_route = experiment.get("route")
    if experiment_route not in ROUTES:
        findings.append(_finding("ROUTE", "$.experiment.route", "unsupported route"))
    if experiment.get("primary_metric") != "eligible_price_first":
        findings.append(
            _finding(
                "GATE_CONTRACT",
                "$.experiment.primary_metric",
                "must equal eligible_price_first for this scorer",
            )
        )
    champion_provider = experiment.get("champion_provider")
    challenger_provider = experiment.get("challenger_provider")
    candidate_id = experiment.get("candidate_id")
    for field_name, value in (
        ("champion_provider", champion_provider),
        ("challenger_provider", challenger_provider),
        ("candidate_id", candidate_id),
    ):
        if not isinstance(value, str) or not value.strip():
            findings.append(
                _finding(
                    "GATE_CONTRACT",
                    f"$.experiment.{field_name}",
                    "must be a non-empty frozen identifier",
                )
            )
    if champion_provider == challenger_provider and isinstance(champion_provider, str):
        findings.append(
            _finding(
                "GATE_CONTRACT",
                "$.experiment",
                "champion_provider and challenger_provider must differ",
            )
        )
    code_sha = experiment.get("code_sha")
    if not isinstance(code_sha, str) or not CODE_SHA.fullmatch(code_sha):
        findings.append(
            _finding("CODE_SHA", "$.experiment.code_sha", "must be 7-64 lowercase hex characters")
        )
    data_manifest_hash = experiment.get("data_manifest_hash")
    if not isinstance(data_manifest_hash, str) or not SHA256.fullmatch(data_manifest_hash):
        findings.append(
            _finding(
                "DATA_MANIFEST_HASH",
                "$.experiment.data_manifest_hash",
                "must be lowercase SHA-256 hex",
            )
        )

    training_cutoff = _parse_time(experiment.get("training_cutoff_at"), "$.experiment.training_cutoff_at", findings)
    candidate_selected = _parse_time(experiment.get("candidate_selected_at"), "$.experiment.candidate_selected_at", findings)
    sealed_opened = _parse_time(
        experiment.get("sealed_test_opened_at"),
        "$.experiment.sealed_test_opened_at",
        findings,
        nullable=True,
    )
    if candidate_selected and sealed_opened and candidate_selected > sealed_opened:
        findings.append(_finding("SEALED_TEST", "$.experiment", "candidate must be selected before the sealed test is opened"))
    if training_cutoff and candidate_selected and training_cutoff > candidate_selected:
        findings.append(
            _finding(
                "TRAIN_TEST_LEAKAGE",
                "$.experiment",
                "candidate_selected_at must not precede training_cutoff_at",
            )
        )

    minimum_primary_effect = experiment.get("minimum_primary_effect")
    if (
        not _finite_number(minimum_primary_effect)
        or float(minimum_primary_effect) < 0.0
        or float(minimum_primary_effect) > 1.0
    ):
        findings.append(
            _finding(
                "GATE_CONTRACT",
                "$.experiment.minimum_primary_effect",
                "must be a finite preregistered rate in [0, 1]",
            )
        )
    minimum_paired_notices = experiment.get("minimum_paired_notices")
    if (
        not isinstance(minimum_paired_notices, int)
        or isinstance(minimum_paired_notices, bool)
        or minimum_paired_notices < 1
    ):
        findings.append(
            _finding(
                "GATE_CONTRACT",
                "$.experiment.minimum_paired_notices",
                "must be a positive preregistered distinct-notice count",
            )
        )
    elif experiment.get("route") == "QUALIFICATION" and minimum_paired_notices < 400:
        findings.append(
            _finding(
                "GATE_CONTRACT",
                "$.experiment.minimum_paired_notices",
                "QUALIFICATION promotion requires at least 400 clean distinct notices",
            )
        )
    coverage_margin = experiment.get("coverage_noninferiority_margin")
    if (
        not _finite_number(coverage_margin)
        or float(coverage_margin) < 0.0
        or float(coverage_margin) > 1.0
    ):
        findings.append(
            _finding(
                "GATE_CONTRACT",
                "$.experiment.coverage_noninferiority_margin",
                "must be a finite preregistered rate in [0, 1]",
            )
        )

    basis_min = experiment.get("basis_ratio_min")
    basis_max = experiment.get("basis_ratio_max")
    if not _positive_number(basis_min) or not _positive_number(basis_max) or basis_min > basis_max:
        findings.append(_finding("BASIS_BOUNDS", "$.experiment", "basis ratio bounds must be positive and ordered"))
        basis_min, basis_max = 0.94, 1.06

    formula_hash = experiment.get("formula_hash")
    if not isinstance(formula_hash, str) or not SHA256.fullmatch(formula_hash):
        findings.append(_finding("FORMULA_HASH", "$.experiment.formula_hash", "must be lowercase SHA-256 hex"))

    competitor_providers_value = experiment.get("competitor_providers")
    if not isinstance(competitor_providers_value, list) or any(
        not isinstance(provider, str) or not provider for provider in competitor_providers_value
    ):
        findings.append(_finding("TYPE", "$.experiment.competitor_providers", "must be an array of provider names"))
        competitor_providers: set[str] = set()
    else:
        competitor_providers = set(competitor_providers_value)
        if len(competitor_providers) != len(competitor_providers_value):
            findings.append(_finding("DUPLICATE_PROVIDER", "$.experiment.competitor_providers", "must not contain duplicates"))
    allowed_exclusions_value = experiment.get("allowed_exclusion_reasons")
    if isinstance(allowed_exclusions_value, list):
        allowed_exclusions = {
            reason for reason in allowed_exclusions_value if isinstance(reason, str)
        }
    else:
        allowed_exclusions = set()

    aggregation = document.get("aggregation")
    if not isinstance(aggregation, dict):
        findings.append(_finding("TYPE", "$.aggregation", "must be an object"))
        aggregation = {}
    for field in sorted(AGGREGATION_FIELDS - set(aggregation)):
        findings.append(_finding("REQUIRED", "$.aggregation", f"missing aggregation field: {field}"))
    for field in sorted(set(aggregation) - AGGREGATION_FIELDS):
        findings.append(_finding("UNKNOWN_FIELD", f"$.aggregation.{field}", "unknown aggregation field"))
    if aggregation.get("sample_unit") != "notice":
        findings.append(_finding("SAMPLE_UNIT", "$.aggregation.sample_unit", "must equal notice"))

    records = document.get("records")
    if not isinstance(records, list):
        findings.append(_finding("TYPE", "$.records", "must be an array"))
        records = []

    seen_provider_notice: set[tuple[str, str]] = set()
    notice_facts: dict[str, dict[str, set[Any]]] = defaultdict(lambda: defaultdict(set))
    included_notices: set[str] = set()
    observed_notices: set[str] = set()
    sealed_rows = 0

    for index, record in enumerate(records):
        location = f"$.records[{index}]"
        if not isinstance(record, dict):
            findings.append(_finding("TYPE", location, "record must be an object"))
            continue
        for field in sorted(RECORD_FIELDS - set(record)):
            findings.append(_finding("REQUIRED", location, f"missing record field: {field}"))
        for field in sorted(set(record) - RECORD_FIELDS):
            findings.append(_finding("UNKNOWN_FIELD", f"{location}.{field}", "unknown record field"))

        notice_id = record.get("notice_id")
        provider = record.get("provider")
        if not isinstance(notice_id, str) or not notice_id.strip():
            findings.append(_finding("NOTICE_ID", f"{location}.notice_id", "must be a non-empty string"))
            notice_id = f"__invalid_notice_{index}"
        else:
            observed_notices.add(notice_id)
            if notice_id not in frozen_cohort:
                findings.append(
                    _finding(
                        "COHORT_MISMATCH",
                        f"{location}.notice_id",
                        "notice is not present in the independently frozen cohort",
                    )
                )
        if not isinstance(provider, str) or not provider.strip():
            findings.append(_finding("PROVIDER", f"{location}.provider", "must be a non-empty string"))
            provider = f"__invalid_provider_{index}"
        pair = (notice_id, provider)
        if pair in seen_provider_notice:
            findings.append(_finding("DUPLICATE_DECISION", location, f"duplicate provider decision for notice {notice_id}: {provider}"))
        seen_provider_notice.add(pair)

        route = record.get("route")
        if route not in ROUTES:
            findings.append(_finding("ROUTE", f"{location}.route", "unsupported route"))
        else:
            _remember_notice_fact(notice_facts, notice_id, "route", route)
            if experiment_route in ROUTES and route != experiment_route:
                findings.append(
                    _finding(
                        "NOTICE_ROUTE",
                        f"{location}.route",
                        "record route differs from frozen experiment route",
                    )
                )
        provider_kind = record.get("provider_kind")
        if provider_kind not in PROVIDER_KINDS:
            findings.append(_finding("PROVIDER_KIND", f"{location}.provider_kind", "unsupported provider kind"))
        split = record.get("split")
        if split not in SPLITS:
            findings.append(_finding("SPLIT", f"{location}.split", "must be train, validation, or sealed_test"))
        else:
            _remember_notice_fact(notice_facts, notice_id, "split", split)
            frozen_entry = frozen_cohort.get(notice_id)
            if frozen_entry is not None and split != frozen_entry.get("split"):
                findings.append(
                    _finding(
                        "COHORT_MISMATCH",
                        f"{location}.split",
                        "split differs from the independently frozen cohort",
                    )
                )
            if split == "sealed_test":
                sealed_rows += 1

        recommendation_at = _parse_time(record.get("recommendation_at"), f"{location}.recommendation_at", findings)
        deadline_at = _parse_time(record.get("deadline_at"), f"{location}.deadline_at", findings)
        information_cutoff_at = _parse_time(
            record.get("information_cutoff_at"), f"{location}.information_cutoff_at", findings
        )
        observed_at = _parse_time(record.get("observed_at"), f"{location}.observed_at", findings)
        outcome_observed_at = _parse_time(
            record.get("outcome_observed_at"), f"{location}.outcome_observed_at", findings, nullable=True
        )
        if deadline_at is not None:
            _remember_notice_fact(notice_facts, notice_id, "deadline_at", deadline_at)
        if information_cutoff_at is not None:
            _remember_notice_fact(notice_facts, notice_id, "information_cutoff_at", information_cutoff_at)
        if outcome_observed_at is not None or record.get("outcome_observed_at") is None:
            _remember_notice_fact(notice_facts, notice_id, "outcome_observed_at", outcome_observed_at)
        if information_cutoff_at and recommendation_at and information_cutoff_at > recommendation_at:
            findings.append(_finding("TIME_LEAKAGE", location, "information cutoff is after recommendation time"))
        if recommendation_at and deadline_at and recommendation_at >= deadline_at:
            findings.append(_finding("PREDEADLINE", location, "recommendation was produced after the deadline"))
        if recommendation_at and observed_at and observed_at < recommendation_at:
            findings.append(_finding("OBSERVATION_TIME", location, "output was observed before it was produced"))
        if record.get("included") is True and observed_at and deadline_at and observed_at >= deadline_at:
            findings.append(
                _finding(
                    "PREDEADLINE_CAPTURE",
                    location,
                    "scored output was not immutably observed before the deadline",
                )
            )
        if (
            record.get("included") is True
            and observed_at
            and outcome_observed_at
            and observed_at >= outcome_observed_at
        ):
            findings.append(
                _finding(
                    "RETROSPECTIVE_OUTPUT",
                    location,
                    "scored output was observed after the outcome became available",
                )
            )
        if outcome_observed_at and deadline_at and outcome_observed_at < deadline_at:
            findings.append(_finding("OUTCOME_TIME", location, "outcome was observed before the bid deadline"))
        if (
            split == "sealed_test"
            and recommendation_at is not None
            and candidate_selected is not None
            and recommendation_at < candidate_selected
        ):
            findings.append(
                _finding(
                    "SEALED_TEST",
                    location,
                    "sealed-test recommendation predates frozen candidate selection",
                )
            )
        if split == "validation" and candidate_selected is not None:
            if recommendation_at is not None and recommendation_at > candidate_selected:
                findings.append(
                    _finding(
                        "CANDIDATE_SELECTION",
                        location,
                        "validation recommendation was produced after candidate selection",
                    )
                )
            if outcome_observed_at is not None and outcome_observed_at > candidate_selected:
                findings.append(
                    _finding(
                        "CANDIDATE_SELECTION",
                        location,
                        "validation outcome was not observable when the candidate was selected",
                    )
                )

        feature_times = record.get("feature_observed_at")
        if not isinstance(feature_times, list):
            findings.append(_finding("TYPE", f"{location}.feature_observed_at", "must be an array"))
            feature_times = []
        for feature_index, value in enumerate(feature_times):
            feature_time = _parse_time(value, f"{location}.feature_observed_at[{feature_index}]", findings)
            if feature_time and information_cutoff_at and feature_time > information_cutoff_at:
                findings.append(_finding("TIME_LEAKAGE", f"{location}.feature_observed_at[{feature_index}]", "feature was observed after the information cutoff"))
            if feature_time and recommendation_at and feature_time > recommendation_at:
                findings.append(_finding("TIME_LEAKAGE", f"{location}.feature_observed_at[{feature_index}]", "feature was observed after recommendation time"))

        used_for_training = record.get("used_for_training")
        if not isinstance(used_for_training, bool):
            findings.append(_finding("TYPE", f"{location}.used_for_training", "must be boolean"))
        elif used_for_training:
            if split != "train":
                findings.append(_finding("TRAIN_TEST_LEAKAGE", location, "only train rows may be used for training"))
            if outcome_observed_at is None or training_cutoff is None or outcome_observed_at > training_cutoff:
                findings.append(_finding("TRAIN_TEST_LEAKAGE", location, "training outcome was not known by training_cutoff_at"))

        if split == "sealed_test" and outcome_observed_at is not None:
            if sealed_opened is None:
                findings.append(_finding("SEALED_TEST", location, "sealed_test_opened_at is required for evaluated sealed rows"))
            elif outcome_observed_at > sealed_opened:
                findings.append(_finding("SEALED_TEST", location, "sealed test was opened before this outcome was observable"))

        included = record.get("included")
        if not isinstance(included, bool):
            findings.append(_finding("TYPE", f"{location}.included", "must be boolean"))
            included = False
        else:
            _remember_notice_fact(notice_facts, notice_id, "included", included)
        if included:
            included_notices.add(notice_id)
        frozen_entry = frozen_cohort.get(notice_id)
        if frozen_entry is not None and included != frozen_entry.get("included"):
            findings.append(
                _finding(
                    "COHORT_MISMATCH",
                    f"{location}.included",
                    "inclusion state differs from the independently frozen cohort",
                )
            )
        basic_price = record.get("basic_price")
        reserved_price = record.get("reserved_price")
        if basic_price is None or _positive_number(basic_price):
            _remember_notice_fact(
                notice_facts,
                notice_id,
                "basic_price",
                None if basic_price is None else float(basic_price),
            )
        else:
            findings.append(_finding("TYPE", f"{location}.basic_price", "must be a positive number or null"))
        if reserved_price is None or _positive_number(reserved_price):
            _remember_notice_fact(
                notice_facts,
                notice_id,
                "reserved_price",
                None if reserved_price is None else float(reserved_price),
            )
        else:
            findings.append(_finding("TYPE", f"{location}.reserved_price", "must be a positive number or null"))
        ratio: float | None = None
        if _positive_number(basic_price) and _positive_number(reserved_price):
            ratio = float(reserved_price) / float(basic_price)
        elif included:
            findings.append(_finding("BASIS_MISSING", location, "included record requires positive basic_price and reserved_price"))
        exclusion_reason = record.get("exclusion_reason")
        if exclusion_reason is not None and (not isinstance(exclusion_reason, str) or not exclusion_reason):
            findings.append(_finding("TYPE", f"{location}.exclusion_reason", "must be a non-empty string or null"))
        else:
            _remember_notice_fact(notice_facts, notice_id, "exclusion_reason", exclusion_reason)
        if frozen_entry is not None and exclusion_reason != frozen_entry.get("exclusion_reason"):
            findings.append(
                _finding(
                    "COHORT_MISMATCH",
                    f"{location}.exclusion_reason",
                    "exclusion reason differs from the independently frozen cohort",
                )
            )
        if included and exclusion_reason is not None:
            findings.append(
                _finding(
                    "EXCLUSION_STATE",
                    location,
                    "included record must not carry an exclusion reason",
                )
            )
        if not included and not isinstance(exclusion_reason, str):
            findings.append(
                _finding(
                    "EXCLUSION_STATE",
                    location,
                    "excluded record requires a preregistered exclusion reason",
                )
            )
        if not included and isinstance(exclusion_reason, str) and exclusion_reason not in allowed_exclusions:
            findings.append(
                _finding(
                    "EXCLUSION_CONTRACT",
                    f"{location}.exclusion_reason",
                    "reason was not allowed by the frozen manifest",
                )
            )
        if ratio is not None and not (float(basis_min) <= ratio <= float(basis_max)):
            if included:
                findings.append(_finding("BASIS_CONSISTENCY", location, f"included basis ratio {ratio:.6f} is outside [{basis_min}, {basis_max}]"))
            if exclusion_reason != "basis_inconsistent":
                findings.append(_finding("BASIS_EXCLUSION", location, "out-of-range basis row must use exclusion_reason basis_inconsistent"))
        if exclusion_reason == "basis_inconsistent" and (
            ratio is None or float(basis_min) <= ratio <= float(basis_max)
        ):
            findings.append(
                _finding(
                    "BASIS_EXCLUSION",
                    location,
                    "basis_inconsistent requires an observed out-of-range basis ratio",
                )
            )
        if exclusion_reason == "missing_basis" and (
            _positive_number(basic_price) and _positive_number(reserved_price)
        ):
            findings.append(
                _finding(
                    "BASIS_EXCLUSION",
                    location,
                    "missing_basis requires an actually missing basis amount",
                )
            )
        if exclusion_reason == "pending_outcome" and outcome_observed_at is not None:
            findings.append(
                _finding(
                    "EXCLUSION_CONTRACT",
                    location,
                    "pending_outcome requires outcome_observed_at to be null",
                )
            )

        bid_valid = record.get("bid_valid")
        if bid_valid is not None and not isinstance(bid_valid, bool):
            findings.append(_finding("TYPE", f"{location}.bid_valid", "must be boolean or null"))
        rank = record.get("rank")
        rank_population = record.get("rank_population")
        valid_participant_count = record.get("valid_participant_count")
        if valid_participant_count is not None and (
            not isinstance(valid_participant_count, int)
            or isinstance(valid_participant_count, bool)
            or valid_participant_count < 1
        ):
            findings.append(
                _finding(
                    "INVALID_RANK",
                    f"{location}.valid_participant_count",
                    "must be a positive integer or null",
                )
            )
        else:
            _remember_notice_fact(
                notice_facts,
                notice_id,
                "valid_participant_count",
                valid_participant_count,
            )
        if bid_valid is False and rank is not None:
            findings.append(_finding("INVALID_RANK", location, "invalid bid must not have a rank"))
        if rank is not None:
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                findings.append(_finding("INVALID_RANK", f"{location}.rank", "rank must be a one-based integer"))
            if bid_valid is not True:
                findings.append(_finding("INVALID_RANK", location, "rank requires bid_valid true"))
            if rank_population != "valid_only":
                findings.append(_finding("INVALID_RANK", f"{location}.rank_population", "rank must be computed over valid_only participants"))
            if not isinstance(valid_participant_count, int) or isinstance(valid_participant_count, bool) or valid_participant_count < 1:
                findings.append(_finding("INVALID_RANK", f"{location}.valid_participant_count", "rank requires a positive valid participant count"))
            elif isinstance(rank, int) and not isinstance(rank, bool) and rank > valid_participant_count:
                findings.append(_finding("INVALID_RANK", location, "rank exceeds valid participant count"))
        elif rank_population not in {None, "valid_only"}:
            findings.append(_finding("INVALID_RANK", f"{location}.rank_population", "only valid_only is permitted"))

        record_formula_hash = record.get("formula_hash")
        if not isinstance(record_formula_hash, str) or not SHA256.fullmatch(record_formula_hash):
            findings.append(_finding("FORMULA_HASH", f"{location}.formula_hash", "must be lowercase SHA-256 hex"))
        elif record_formula_hash != formula_hash:
            findings.append(_finding("FORMULA_HASH", f"{location}.formula_hash", "record formula hash differs from experiment"))

        artifact_hash = record.get("artifact_sha256")
        if included and (not isinstance(artifact_hash, str) or not SHA256.fullmatch(artifact_hash)):
            findings.append(
                _finding(
                    "DECISION_ARTIFACT",
                    f"{location}.artifact_sha256",
                    "every scored output requires an immutable decision artifact SHA-256",
                )
            )

        is_competitor = provider_kind == "competitor" or provider in competitor_providers
        if is_competitor:
            if provider_kind != "competitor":
                findings.append(_finding("COMPETITOR_KIND", location, "listed competitor provider must use provider_kind competitor"))
            if provider not in competitor_providers:
                findings.append(
                    _finding(
                        "COMPETITOR_SCOPE",
                        location,
                        "competitor provider was not frozen in experiment.competitor_providers",
                    )
                )
            if not isinstance(artifact_hash, str) or not SHA256.fullmatch(artifact_hash):
                findings.append(_finding("COMPETITOR_ARTIFACT", f"{location}.artifact_sha256", "competitor record requires raw artifact SHA-256"))
            if observed_at and deadline_at and observed_at >= deadline_at:
                findings.append(_finding("COMPETITOR_CUTOFF", location, "competitor output was captured after the deadline"))
            if information_cutoff_at and observed_at and information_cutoff_at > observed_at:
                findings.append(_finding("COMPETITOR_CUTOFF", location, "competitor observation precedes its information cutoff"))

        for boolean_field in ("primary_success", "dropout"):
            value = record.get(boolean_field)
            if value is not None and not isinstance(value, bool):
                findings.append(_finding("TYPE", f"{location}.{boolean_field}", "must be boolean or null"))
        if included and (
            outcome_observed_at is None
            or not isinstance(record.get("primary_success"), bool)
            or not isinstance(record.get("dropout"), bool)
        ):
            findings.append(
                _finding(
                    "OUTCOME_MISSING",
                    location,
                    "included performance row requires an observed outcome and boolean primary_success/dropout",
                )
            )
        recommendation_price = record.get("recommendation_price")
        actual_lower_limit_price = record.get("actual_lower_limit_price")
        winner_price = record.get("winner_price")
        outcome_prices = {
            "recommendation_price": recommendation_price,
            "actual_lower_limit_price": actual_lower_limit_price,
            "winner_price": winner_price,
        }
        for price_field, price_value in outcome_prices.items():
            if price_value is not None and not _positive_number(price_value):
                findings.append(
                    _finding(
                        "TYPE",
                        f"{location}.{price_field}",
                        "must be a positive number or null",
                    )
                )
        if _positive_number(actual_lower_limit_price):
            _remember_notice_fact(
                notice_facts,
                notice_id,
                "actual_lower_limit_price",
                float(actual_lower_limit_price),
            )
        if _positive_number(winner_price):
            _remember_notice_fact(
                notice_facts,
                notice_id,
                "winner_price",
                float(winner_price),
            )
        if included and not all(_positive_number(value) for value in outcome_prices.values()):
            findings.append(
                _finding(
                    "OUTCOME_MISSING",
                    location,
                    "included row requires recommendation, lower-limit, and winner prices",
                )
            )
        if all(_positive_number(value) for value in outcome_prices.values()):
            expected_dropout = float(recommendation_price) < float(actual_lower_limit_price)
            if record.get("dropout") is not expected_dropout:
                findings.append(
                    _finding(
                        "OUTCOME_DERIVATION",
                        f"{location}.dropout",
                        "dropout disagrees with recommendation_price < actual_lower_limit_price",
                    )
                )
            if expected_dropout and bid_valid is not False:
                findings.append(
                    _finding(
                        "OUTCOME_DERIVATION",
                        f"{location}.bid_valid",
                        "a below-limit recommendation must be invalid",
                    )
                )
            expected_primary = bid_valid is True and rank == 1
            if record.get("primary_success") is not expected_primary:
                findings.append(
                    _finding(
                        "OUTCOME_DERIVATION",
                        f"{location}.primary_success",
                        "eligible_price_first must equal bid_valid=true and rank=1",
                    )
                )
            if expected_primary and float(recommendation_price) > float(winner_price):
                findings.append(
                    _finding(
                        "RANK_TRUTH",
                        f"{location}.rank",
                        "rank 1 recommendation cannot exceed the authoritative winning price",
                    )
                )
        profit = record.get("realized_contribution_profit")
        if profit is not None and (
            not isinstance(profit, (int, float)) or isinstance(profit, bool) or not math.isfinite(profit)
        ):
            findings.append(_finding("TYPE", f"{location}.realized_contribution_profit", "must be a finite number or null"))

    mismatch_contract = {
        "route": ("NOTICE_ROUTE", "providers for one notice use different routes"),
        "split": ("TRAIN_TEST_LEAKAGE", "notice appears in multiple temporal splits"),
        "deadline_at": ("NOTICE_DEADLINE", "providers for one notice use different deadlines"),
        "information_cutoff_at": (
            "COMPETITOR_CUTOFF",
            "providers for one notice use different information cutoffs",
        ),
        "basic_price": ("NOTICE_TRUTH", "providers for one notice use different authoritative basic prices"),
        "reserved_price": ("NOTICE_TRUTH", "providers for one notice use different authoritative reserved prices"),
        "actual_lower_limit_price": (
            "NOTICE_TRUTH",
            "providers for one notice use different actual lower-limit prices",
        ),
        "winner_price": (
            "NOTICE_TRUTH",
            "providers for one notice use different authoritative winner prices",
        ),
        "outcome_observed_at": (
            "NOTICE_TRUTH",
            "providers for one notice use different authoritative outcome observation times",
        ),
        "included": ("NOTICE_COHORT", "providers for one notice disagree on cohort inclusion"),
        "exclusion_reason": ("NOTICE_COHORT", "providers for one notice use different exclusion reasons"),
        "valid_participant_count": (
            "VALID_POPULATION",
            "providers for one notice use different valid-participant populations",
        ),
    }
    for notice_id, fields in sorted(notice_facts.items()):
        for field, values in sorted(fields.items()):
            if len(values) <= 1:
                continue
            code, message = mismatch_contract[field]
            findings.append(_finding(code, f"$.records[{notice_id}].{field}", message))
    if sealed_rows and candidate_selected is None:
        findings.append(_finding("SEALED_TEST", "$.experiment.candidate_selected_at", "sealed rows require candidate selection time"))

    missing_notices = sorted(set(frozen_cohort) - observed_notices)
    if missing_notices:
        findings.append(
            _finding(
                "COHORT_MISMATCH",
                "$.records",
                "frozen cohort notices are missing from evidence: " + ", ".join(missing_notices[:10]),
            )
        )

    frozen_included_notices = {
        notice_id
        for notice_id, entry in frozen_cohort.items()
        if entry.get("included") is True
    }
    distinct_count = len(frozen_included_notices)
    for field in ("reported_sample_size", "distinct_notice_count"):
        value = aggregation.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            findings.append(_finding("TYPE", f"$.aggregation.{field}", "must be a non-negative integer"))
        elif value != distinct_count:
            findings.append(_finding("DISTINCT_NOTICE", f"$.aggregation.{field}", f"expected {distinct_count} included distinct notices, got {value}"))
    raw_row_count = aggregation.get("raw_row_count")
    if raw_row_count is not None and raw_row_count != len(records):
        findings.append(_finding("ROW_COUNT", "$.aggregation.raw_row_count", f"expected {len(records)}, got {raw_row_count}"))

    return sorted(set(findings))


def _valid_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    formula = "a" * 64
    base_record = {
        "notice_id": "N-001",
        "route": "PRICE_DOMINANT",
        "provider": "active",
        "provider_kind": "internal",
        "split": "sealed_test",
        "recommendation_at": "2026-01-03T09:00:00+09:00",
        "deadline_at": "2026-01-04T10:00:00+09:00",
        "information_cutoff_at": "2026-01-03T08:59:00+09:00",
        "observed_at": "2026-01-03T09:00:01+09:00",
        "feature_observed_at": ["2026-01-03T08:00:00+09:00"],
        "outcome_observed_at": "2026-01-05T12:00:00+09:00",
        "used_for_training": False,
        "basic_price": 100.0,
        "reserved_price": 100.0,
        "recommendation_price": 95.0,
        "actual_lower_limit_price": 87.0,
        "winner_price": 90.0,
        "included": True,
        "exclusion_reason": None,
        "bid_valid": True,
        "rank": 2,
        "rank_population": "valid_only",
        "valid_participant_count": 10,
        "formula_hash": formula,
        "artifact_sha256": "c" * 64,
        "primary_success": False,
        "dropout": False,
        "realized_contribution_profit": None,
    }
    competitor = copy.deepcopy(base_record)
    competitor.update(
        {
            "provider": "dimatools",
            "provider_kind": "competitor",
            "observed_at": "2026-01-03T09:01:00+09:00",
            "recommendation_at": "2026-01-03T09:01:00+09:00",
            "artifact_sha256": "b" * 64,
            "primary_success": True,
            "rank": 1,
            "recommendation_price": 89.0,
        }
    )
    manifest = {
        "schema_version": "1.0",
        "experiment": {
            "id": "fixture",
            "route": "PRICE_DOMINANT",
            "primary_metric": "eligible_price_first",
            "champion_provider": "active",
            "challenger_provider": "dimatools",
            "candidate_id": "candidate-v1",
            "code_sha": "abcdef1",
            "data_manifest_hash": "d" * 64,
            "training_cutoff_at": "2026-01-01T00:00:00+09:00",
            "candidate_selected_at": "2026-01-02T00:00:00+09:00",
            "sealed_test_opened_at": "2026-02-01T00:00:00+09:00",
            "minimum_primary_effect": 0.1,
            "minimum_paired_notices": 1,
            "coverage_noninferiority_margin": 0.0,
            "basis_ratio_min": 0.94,
            "basis_ratio_max": 1.06,
            "formula_hash": formula,
            "competitor_providers": ["dimatools"],
            "allowed_exclusion_reasons": [
                "basis_inconsistent",
                "missing_basis",
                "pending_outcome",
            ],
        },
        "cohort": [
            {
                "notice_id": "N-001",
                "split": "sealed_test",
                "included": True,
                "exclusion_reason": None,
            }
        ],
    }
    document = {
        "schema_version": "1.0",
        "experiment": {
            **manifest["experiment"],
            "manifest_sha256": canonical_sha256(manifest),
        },
        "aggregation": {
            "sample_unit": "notice",
            "reported_sample_size": 1,
            "distinct_notice_count": 1,
            "raw_row_count": 2,
        },
        "records": [base_record, competitor],
    }
    return document, manifest


def run_self_test() -> None:
    valid, manifest = _valid_fixture()
    assert not validate_evidence(valid, manifest), validate_evidence(valid, manifest)

    cases: list[tuple[str, dict[str, Any], dict[str, Any], str]] = []
    leaked = copy.deepcopy(valid)
    leaked["records"][0]["feature_observed_at"] = ["2026-01-03T09:30:00+09:00"]
    cases.append(("future feature", leaked, manifest, "TIME_LEAKAGE"))
    rows_as_samples = copy.deepcopy(valid)
    rows_as_samples["aggregation"]["reported_sample_size"] = 2
    cases.append(("arm-row inflation", rows_as_samples, manifest, "DISTINCT_NOTICE"))
    bad_basis = copy.deepcopy(valid)
    bad_basis["records"][0]["reserved_price"] = 110.0
    cases.append(("basis mismatch", bad_basis, manifest, "BASIS_CONSISTENCY"))
    bad_rank = copy.deepcopy(valid)
    bad_rank["records"][0]["bid_valid"] = False
    cases.append(("invalid bid rank", bad_rank, manifest, "INVALID_RANK"))
    late_competitor = copy.deepcopy(valid)
    late_competitor["records"][1]["observed_at"] = "2026-01-04T11:00:00+09:00"
    cases.append(("late competitor", late_competitor, manifest, "COMPETITOR_CUTOFF"))
    late_internal = copy.deepcopy(valid)
    late_internal["records"][0]["observed_at"] = "2026-01-06T11:00:00+09:00"
    cases.append(
        ("retrospective internal output", late_internal, manifest, "PREDEADLINE_CAPTURE")
    )
    wrong_formula = copy.deepcopy(valid)
    wrong_formula["experiment"]["formula_hash"] = "c" * 64
    for record in wrong_formula["records"]:
        record["formula_hash"] = "c" * 64
    cases.append(("formula drift", wrong_formula, manifest, "MANIFEST_MISMATCH"))
    derived_dropout = copy.deepcopy(valid)
    derived_dropout["records"][0]["dropout"] = True
    cases.append(("invented dropout label", derived_dropout, manifest, "OUTCOME_DERIVATION"))
    derived_primary = copy.deepcopy(valid)
    derived_primary["records"][0]["primary_success"] = True
    cases.append(("invented primary label", derived_primary, manifest, "OUTCOME_DERIVATION"))
    impossible_rank = copy.deepcopy(valid)
    impossible_rank["records"][0].update(
        recommendation_price=99.0,
        rank=1,
        primary_success=True,
    )
    cases.append(("impossible first rank", impossible_rank, manifest, "RANK_TRUTH"))
    missing_artifact = copy.deepcopy(valid)
    missing_artifact["records"][0]["artifact_sha256"] = None
    cases.append(("missing internal artifact", missing_artifact, manifest, "DECISION_ARTIFACT"))
    missing_cohort = copy.deepcopy(valid)
    missing_cohort["records"] = []
    missing_cohort["aggregation"].update(
        reported_sample_size=1,
        distinct_notice_count=1,
        raw_row_count=0,
    )
    cases.append(("omitted frozen notice", missing_cohort, manifest, "COHORT_MISMATCH"))
    posthoc_exclusion = copy.deepcopy(valid)
    for record in posthoc_exclusion["records"]:
        record["included"] = False
        record["exclusion_reason"] = "pending_outcome"
        record["outcome_observed_at"] = None
    posthoc_exclusion["aggregation"].update(
        reported_sample_size=0,
        distinct_notice_count=0,
    )
    cases.append(("post-hoc exclusion", posthoc_exclusion, manifest, "COHORT_MISMATCH"))
    changed_candidate = copy.deepcopy(valid)
    changed_candidate["experiment"]["candidate_id"] = "candidate-picked-after-open"
    cases.append(("post-hoc candidate", changed_candidate, manifest, "MANIFEST_MISMATCH"))

    mismatch_cases = [
        ("route mismatch", "route", "QUALIFICATION", "NOTICE_ROUTE"),
        ("split mismatch", "split", "validation", "TRAIN_TEST_LEAKAGE"),
        ("deadline mismatch", "deadline_at", "2026-01-04T11:00:00+09:00", "NOTICE_DEADLINE"),
        (
            "cutoff mismatch",
            "information_cutoff_at",
            "2026-01-03T08:58:00+09:00",
            "COMPETITOR_CUTOFF",
        ),
        ("basic-price mismatch", "basic_price", 101.0, "NOTICE_TRUTH"),
        ("reserved-price mismatch", "reserved_price", 101.0, "NOTICE_TRUTH"),
        (
            "outcome-time mismatch",
            "outcome_observed_at",
            "2026-01-05T13:00:00+09:00",
            "NOTICE_TRUTH",
        ),
        ("valid-population mismatch", "valid_participant_count", 11, "VALID_POPULATION"),
    ]
    for name, field, value, expected in mismatch_cases:
        mismatch = copy.deepcopy(valid)
        mismatch["records"][1][field] = value
        cases.append((name, mismatch, manifest, expected))

    cohort_mismatch = copy.deepcopy(valid)
    cohort_mismatch["records"][1]["included"] = False
    cohort_mismatch["records"][1]["exclusion_reason"] = "pending_outcome"
    cases.append(("inclusion mismatch", cohort_mismatch, manifest, "NOTICE_COHORT"))

    preselection = copy.deepcopy(valid)
    preselection["experiment"]["candidate_selected_at"] = "2026-01-03T09:30:00+09:00"
    cases.append(("sealed recommendation predates selection", preselection, manifest, "SEALED_TEST"))

    late_validation = copy.deepcopy(valid)
    for record in late_validation["records"]:
        record["split"] = "validation"
    cases.append(("validation outcome follows selection", late_validation, manifest, "CANDIDATE_SELECTION"))

    missing_gate_contract = copy.deepcopy(valid)
    del missing_gate_contract["experiment"]["minimum_paired_notices"]
    cases.append(("missing preregistered sample threshold", missing_gate_contract, manifest, "REQUIRED"))

    undersized_qualification = copy.deepcopy(valid)
    qualification_manifest = copy.deepcopy(manifest)
    qualification_manifest["experiment"]["route"] = "QUALIFICATION"
    undersized_qualification["experiment"]["route"] = "QUALIFICATION"
    undersized_qualification["experiment"]["manifest_sha256"] = canonical_sha256(
        qualification_manifest
    )
    for record in undersized_qualification["records"]:
        record["route"] = "QUALIFICATION"
    cases.append(
        (
            "qualification sample threshold below 400",
            undersized_qualification,
            qualification_manifest,
            "GATE_CONTRACT",
        )
    )

    for name, fixture, fixture_manifest, expected in cases:
        codes = {finding.code for finding in validate_evidence(fixture, fixture_manifest)}
        assert expected in codes, (name, expected, codes)
    print(f"SELF-TEST PASS: {len(cases)} invalid fixtures rejected and valid fixture accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", type=Path, help="evidence JSON file")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="independently stored frozen manifest JSON",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable findings")
    parser.add_argument("--self-test", action="store_true", help="run embedded fixture tests")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.evidence is None or args.manifest is None:
        parser.error("evidence and --manifest are required unless --self-test is used")
    try:
        document = json.loads(args.evidence.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    findings = validate_evidence(document, manifest)
    if args.as_json:
        print(json.dumps({"valid": not findings, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"{item.code} {item.location}: {item.message}")
    else:
        print(f"VALID {document.get('experiment', {}).get('id')}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
