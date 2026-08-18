# Bid algorithm evidence contract

## Purpose

Use one immutable JSON artifact for validation and paired scoring. The artifact contains already-produced recommendations and observed outcomes. It must not contain a copied implementation of the production bid formula.

## Root shape

```json
{
  "schema_version": "1.0",
  "experiment": {
    "id": "exp-2026-08-qualification-01",
    "route": "QUALIFICATION",
    "primary_metric": "eligible_price_first",
    "training_cutoff_at": "2026-05-31T23:59:59+09:00",
    "candidate_selected_at": "2026-06-01T09:00:00+09:00",
    "sealed_test_opened_at": "2026-08-01T09:00:00+09:00",
    "minimum_primary_effect": 0.01,
    "minimum_paired_notices": 400,
    "coverage_noninferiority_margin": 0.0,
    "basis_ratio_min": 0.94,
    "basis_ratio_max": 1.06,
    "formula_hash": "<64 lowercase hex characters>",
    "expected_formula_hash": "<same hash from the manifest>",
    "competitor_providers": ["dimatools", "kbid", "bidpro"]
  },
  "aggregation": {
    "sample_unit": "notice",
    "reported_sample_size": 400,
    "distinct_notice_count": 400,
    "raw_row_count": 1600
  },
  "records": []
}
```

Use RFC 3339 timestamps with an explicit UTC offset. Use lowercase SHA-256 hex for hashes.

`minimum_primary_effect`, `minimum_paired_notices`, and
`coverage_noninferiority_margin` are frozen promotion-gate inputs. The coverage
margin is the largest permitted challenger-minus-champion coverage loss, so
`0.0` requires challenger coverage to be at least champion coverage. All three
must be registered before sealed outcomes are opened.

## Record fields

Every record represents one provider or strategy decision for one notice.

| Field | Contract |
|---|---|
| `notice_id` | Stable public notice identifier. |
| `route` | `PRICE_DOMINANT`, `QUALIFICATION`, `COMPREHENSIVE`, `NEGOTIATION`, or `UNSUPPORTED`. |
| `provider` | Stable strategy/provider identifier. Unique within a notice. |
| `provider_kind` | `internal`, `competitor`, or `user_baseline`. |
| `split` | `train`, `validation`, or `sealed_test`; one notice cannot cross splits. |
| `recommendation_at` | Time the decision was produced. Must precede the deadline. |
| `deadline_at` | Notice submission deadline. |
| `information_cutoff_at` | Latest information allowed for this comparison. All providers for a notice must match. |
| `observed_at` | Time the output was captured. Competitor outputs must be captured before deadline. |
| `feature_observed_at` | Array of timestamps for all input facts. Every value must be at or before the information cutoff. |
| `outcome_observed_at` | Time the opening/outcome became known, or `null` for pending rows. |
| `used_for_training` | `true` only for `train` rows whose outcome was known by `training_cutoff_at`. |
| `basic_price`, `reserved_price` | Authoritative positive numeric values, or `null` when excluded. |
| `recommendation_price` | The captured pre-deadline recommendation used for this provider decision. |
| `actual_lower_limit_price`, `winner_price` | Authoritative post-opening truth. They must match across providers for a notice. |
| `included` | Whether this row participates in performance scoring. |
| `exclusion_reason` | `basis_inconsistent`, `missing_basis`, `pending_outcome`, or another preregistered reason; otherwise `null`. |
| `bid_valid` | Whether the bid satisfies the legal lower-bound calculation; may be `null` before evaluation. |
| `rank` | One-based price rank, or `null`. Invalid bids must never have a rank. |
| `rank_population` | Must be `valid_only` whenever rank is present. |
| `valid_participant_count` | Count of valid participants used for rank, or `null`. |
| `formula_hash` | Hash of the authoritative formula/version used to create the decision. |
| `artifact_sha256` | Required for competitor rows; hash of the raw screenshot/export/response. |
| `primary_success` | Must equal `bid_valid == true && rank == 1` (`eligible_price_first`), or `null` when pending. |
| `dropout` | Must equal `recommendation_price < actual_lower_limit_price`, or `null` when pending. |
| `realized_contribution_profit` | Precomputed realized contribution profit, or `null`; never infer it from winning-price proximity. |

For every provider row sharing a `notice_id`, the following notice-level truth
must be identical: `route`, `split`, `deadline_at`, `information_cutoff_at`,
`basic_price`, `reserved_price`, `outcome_observed_at`, `included`,
`exclusion_reason`, and `valid_participant_count`. Provider-specific decisions
such as `bid_valid`, `rank`, `primary_success`, `dropout`, and realized profit
may differ.

## Temporal isolation

- Permit training only from outcomes known at or before `training_cutoff_at`.
- Assign a notice to exactly one split across all providers.
- Require validation recommendations and outcomes to exist no later than candidate selection.
- Select the candidate before opening the sealed test.
- Produce every sealed-test recommendation only after candidate selection.
- Do not reopen a sealed test and then tune against the same outcomes.
- Record every feature observation time; a nominal “year split” is insufficient evidence.

## Basis and rank integrity

- Apply the manifest's inclusive `basis_ratio_min` and `basis_ratio_max` to `reserved_price / basic_price`.
- Exclude an out-of-range record with `exclusion_reason: basis_inconsistent`.
- Do not synthesize a basis amount or multiply an estimate by `1.1`.
- Keep `rank` null when `bid_valid` is false.
- When rank is present, require `rank_population: valid_only` and `1 <= rank <= valid_participant_count`.

## Competitor comparability

For a competitor row, require a pre-deadline capture, an immutable raw artifact hash, and the same `information_cutoff_at` as every internal comparator for that notice. Preserve provider, plan/tier, collector identity, and source terms outside this minimal scoring artifact when policy requires them.

## Interpretation

`score_paired_bids.py` reports:

- route-specific `sealed_test` promotion gates only;
- same-notice intersection performance and deterministic paired bootstrap intervals;
- full-cohort success with abstentions/missing outputs counted as no success;
- provider coverage and its preregistered non-inferiority test;
- preregistered minimum paired-notice, primary-effect, and dropout gate components;
- train, validation, sealed, and cross-route cohort summaries marked diagnostic-only.

No train, validation, or `ALL` route aggregate can produce a promotion pass.

Do not call `valid-price reach` a final win. Do not publish cross-service superiority unless every named service passes the preregistered same-cohort paired gate and has non-inferior coverage.
