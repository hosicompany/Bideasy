---
name: graph-orchestrator
description: Design and validate bounded execution graphs for complex agent workflows with parallel audits, typed artifacts, maker-checker separation, local retry loops, fan-in barriers, human approvals, and promotion gates. Use for multi-stage work that has conditional branches, cycles, multiple agents, side effects, or evidence-based release decisions. Do not use for simple linear tasks, knowledge graphs, GraphRAG, graph databases, or GNN model design.
---

# Graph Orchestrator

Turn a complex workflow into a typed, bounded state machine before running it. Keep deterministic control in the graph and reserve model judgment for explicitly named nodes.

## Workflow

1. Identify the entry contract, shared state, artifacts, side effects, approvals, and terminal outcomes.
2. Read [topology-patterns.md](references/topology-patterns.md) and choose the smallest topology that represents the work.
3. Author a JSON graph conforming to [graph-spec.schema.json](references/graph-spec.schema.json).
4. Give every node explicit inputs, outputs, information-time policy, tools, timeout, retry limit, side-effect class, and verifier.
5. Keep maker and verifier in different `independence_group` values. Route failures to the node that owns the failure instead of restarting the whole graph.
6. Give every directed cycle a finite iteration budget, progress signal, abort condition, and success/failure exits.
7. Declare synchronized joins with `join_policy: all`, a matching `fan_in` barrier, and a shared `data_manifest_hash` from every predecessor.
8. Require an approved, scoped approval record for every write, external action, or promotion. Require a typed `GateDecision` input from a gate node before promotion.
9. Validate before execution:

```bash
python3 scripts/validate_graph_spec.py path/to/graph.json
```

10. Do not execute an invalid graph. Preserve the validated graph, validator output, and shared-state identifiers with the experiment artifacts.

## Invariants

- Treat artifacts as immutable values identified by schema name and content hash.
- Treat `as_of_policy` as a hard information boundary, not explanatory prose.
- Make each side-effecting node idempotent and rollback-capable in its implementation contract.
- Keep pending approvals outside an executable graph. The validator accepts only `status: approved` for an active side-effecting node.
- Use `join_policy: any` for retry returns or alternative conditional paths; use `all` only for a synchronization barrier.
- Never use a graph to broaden authority. A graph coordinates only actions already authorized by the user.

Run `python3 scripts/validate_graph_spec.py --self-test` after changing the validator or schema.
