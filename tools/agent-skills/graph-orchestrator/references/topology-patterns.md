# Execution graph topology patterns

Use the smallest pattern that preserves the real control flow. A node represents a contract, not a conversational turn.

## Typed linear stage

Use a linear edge when one deterministic output is the sole prerequisite of the next stage. Put each artifact name and schema identifier in both node contracts and on the edge. Never pass an undeclared artifact.

## Parallel audit and synchronized fan-in

Fan out independent audits only when they can operate on the same immutable snapshot. Give every audit its own `independence_group`. At the join:

- set `join_policy` to `all`;
- list every predecessor in one `fan_in` declaration;
- require `data_manifest_hash` from every predecessor;
- refuse partial results or mixed snapshot hashes.

Use `join_policy: any` for alternative conditional paths and retry returns. Those paths are not synchronization barriers.

## Maker-checker

Assign `role: maker`, `candidate_builder`, or `implementer` to the producing node and `role: verifier` to the checker. Point the maker's `verifier` field to the checker and use different `independence_group` values. The verifier must rebuild conclusions from immutable artifacts rather than the maker's narrative.

## Bounded local improvement loop

Route a classified failure to the node that owns it. Declare the detected strongly connected component in `cycles` with:

- a finite `max_iterations`;
- a measurable `progress_signal`;
- a non-progress or risk `abort_condition`;
- explicit success and failure nodes outside the cycle.

Do not use “until it works” or token budget exhaustion as a stop condition.

## Human-in-the-loop side effects

Mark repository mutation as `write`, outbound contact or spending as `external`, and strategy activation or deployment as `promotion`. Reference a scoped approval whose status is `approved`. A promotion node must additionally consume:

- `gate_decision: GateDecision` from a node with `role: gate`;
- `route` and `strategy_version` artifacts;
- a promotion approval bound to the same route and strategy version.

Keep pending approvals out of an executable graph. Represent the pause with a terminal report and produce a new validated graph after approval.

## Failure routing

Prefer failure taxonomy such as `DATA`, `LEAKAGE`, `FORMULA`, `BASELINE`, `MODEL`, and `EVIDENCE`. Preserve the experiment ID, snapshot hash, formula hash, failure class, and gate decision across every return edge.

## Shared state

Every graph must type these shared fields:

`experiment_id`, `code_sha`, `data_manifest_hash`, `formula_hash`, `as_of_cutoff`, `route`, `feature_version`, `fold_predictions`, `metrics`, `failure_class`, `gate_decision`, `approval_id`.

Store large values as immutable artifacts and keep only identifiers or hashes in orchestration state.
