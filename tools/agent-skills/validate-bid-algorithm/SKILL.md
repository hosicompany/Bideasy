---
name: validate-bid-algorithm
description: Audit and compare public-procurement bid recommendation algorithms with time-safe, notice-level, paired evidence. Use when validating champion/challenger strategies, mock-bid or opening-result datasets, recommendation accuracy, rank calculations, basis-price consistency, formula provenance, temporal splits, or same-cutoff competitor observations. This skill never submits bids, contacts competitors, promotes a strategy, or recreates production bid formulas.
---

# Validate Bid Algorithm

Validate evidence before interpreting performance. Count distinct notices, enforce information-time boundaries, and compare precomputed decisions rather than reimplementing production formulas.

## Workflow

1. Read [bid-evaluation-contract.md](references/bid-evaluation-contract.md) before creating or accepting an evidence artifact.
2. Use the execution topology in [bid-validation-graph.json](references/bid-validation-graph.json) with `$graph-orchestrator` for multi-agent or iterative work.
3. Freeze the experiment manifest before inspecting sealed-test outcomes. Preserve code SHA, data content hash, formula hash, cutoff, route, folds, metrics, minimum effect, and stop rule.
4. Export recommendations and outcomes from their authoritative systems. Do not copy calculation formulas into this skill.
5. Validate the evidence:

```bash
python3 scripts/validate_bid_evidence.py evidence.json --manifest manifest.json
```

The frozen manifest is a separate argument on purpose. Reading it out of the
evidence document would let the same edit rewrite both the sample and the
standard it is judged against.

6. Fix evidence defects before scoring. Never relabel an invalid row merely to pass validation.
7. Score the same-notice intersection and abstention-penalized full cohort:

```bash
python3 scripts/score_paired_bids.py evidence.json \
  --manifest manifest.json \
  --champion active --challenger candidate
```

Scoring re-runs the full validation against the same frozen manifest and refuses
to emit a score when it fails, so the gate cannot be reached by skipping step 5.

`--min-effect` is only an optional assertion: when supplied, it must equal the
manifest's frozen `minimum_primary_effect`. It cannot change the gate.

8. Report population, period, route, exclusions, distinct-notice count, coverage, paired confidence intervals, worst segment, and residual unknowns.
9. Stop at a shadow recommendation. Require a separate gate and human approval for activation or deployment.

## Guardrails

- Reject features observed after the declared information cutoff or recommendation time.
- Reject row-count claims presented as notice counts.
- Exclude inconsistent basis-price rows using the preregistered ratio bounds; never repair them with `×1.1`.
- Assign ranks only to valid bids and only against valid participants.
- Accept competitor evidence only when it was captured before deadline with the same notice cutoff and an immutable raw-artifact hash.
- Reject provider rows that disagree on notice-level route, split, deadline, cutoff, price truth, outcome time, cohort state, or valid-participant population.
- Require every record's formula hash to match the experiment formula hash.
- Compute promotion gates only from route-specific `sealed_test` evidence. Keep train, validation, and cross-route aggregates diagnostic-only.
- Require the preregistered distinct-paired-notice threshold and coverage non-inferiority margin to pass.
- Treat price-closeness metrics as diagnostics, not proof of winning or profitability.
- Keep tenant cost, margin, and submitted price out of central training unless explicit consent and policy authorize it.

Run both scripts with `--self-test` after changing their contracts or calculations.
