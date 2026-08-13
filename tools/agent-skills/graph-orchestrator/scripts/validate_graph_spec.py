#!/usr/bin/env python3
"""Deterministically validate a bounded agent execution graph."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
ROOT_FIELDS = {
    "version",
    "graph_id",
    "entry_node",
    "external_inputs",
    "shared_state_schema",
    "nodes",
    "edges",
    "cycles",
    "fan_in",
    "approvals",
}
NODE_FIELDS = {
    "id",
    "role",
    "independence_group",
    "inputs",
    "outputs",
    "as_of_policy",
    "allowed_tools",
    "side_effect",
    "join_policy",
    "timeout_seconds",
    "retry_limit",
    "verifier",
    "required_approval",
}
SHARED_STATE_FIELDS = {
    "experiment_id",
    "code_sha",
    "data_manifest_hash",
    "formula_hash",
    "as_of_cutoff",
    "route",
    "feature_version",
    "fold_predictions",
    "metrics",
    "failure_class",
    "gate_decision",
    "approval_id",
}
MAKER_ROLES = {"maker", "candidate_builder", "implementer"}
SIDE_EFFECTS = {"none", "write", "external", "promotion"}


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    location: str
    message: str


def _finding(code: str, location: str, message: str) -> Finding:
    return Finding(code=code, location=location, message=message)


def _is_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))


def _artifact_map(value: Any, location: str, findings: list[Finding]) -> dict[str, str]:
    if not isinstance(value, dict):
        findings.append(_finding("TYPE", location, "must be an object of artifact names to schema identifiers"))
        return {}
    result: dict[str, str] = {}
    for name, schema in value.items():
        if not _is_identifier(name) or not _is_identifier(schema):
            findings.append(_finding("IDENTIFIER", f"{location}.{name}", "artifact and schema names must be identifiers"))
            continue
        result[name] = schema
    return result


def _strongly_connected_components(
    node_ids: set[str], outgoing: dict[str, list[str]]
) -> list[set[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in outgoing.get(node, []):
            if target not in node_ids:
                continue
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: set[str] = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node:
                    break
            components.append(component)

    for node in sorted(node_ids):
        if node not in indices:
            visit(node)
    return components


def validate_graph(spec: Any) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(spec, dict):
        return [_finding("TYPE", "$", "graph must be a JSON object")]

    missing_root = sorted(ROOT_FIELDS - set(spec))
    for field in missing_root:
        findings.append(_finding("REQUIRED", "$", f"missing root field: {field}"))
    for field in sorted(set(spec) - ROOT_FIELDS):
        findings.append(_finding("UNKNOWN_FIELD", f"$.{field}", "unknown root field"))
    if spec.get("version") != "1.0":
        findings.append(_finding("VERSION", "$.version", "must equal 1.0"))
    if not _is_identifier(spec.get("graph_id")):
        findings.append(_finding("IDENTIFIER", "$.graph_id", "must be a valid identifier"))

    external_inputs = _artifact_map(spec.get("external_inputs"), "$.external_inputs", findings)
    shared_state = _artifact_map(spec.get("shared_state_schema"), "$.shared_state_schema", findings)
    missing_state = sorted(SHARED_STATE_FIELDS - set(shared_state))
    for field in missing_state:
        findings.append(_finding("SHARED_STATE", "$.shared_state_schema", f"missing shared state field: {field}"))

    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        findings.append(_finding("TYPE", "$.nodes", "must be a non-empty array"))
        raw_nodes = []
    nodes: dict[str, dict[str, Any]] = {}
    for index, raw_node in enumerate(raw_nodes):
        location = f"$.nodes[{index}]"
        if not isinstance(raw_node, dict):
            findings.append(_finding("TYPE", location, "node must be an object"))
            continue
        for field in sorted(NODE_FIELDS - set(raw_node)):
            findings.append(_finding("REQUIRED", location, f"missing node field: {field}"))
        for field in sorted(set(raw_node) - NODE_FIELDS):
            findings.append(_finding("UNKNOWN_FIELD", f"{location}.{field}", "unknown node field"))
        node_id = raw_node.get("id")
        if not _is_identifier(node_id):
            findings.append(_finding("IDENTIFIER", f"{location}.id", "must be a valid identifier"))
            continue
        if node_id in nodes:
            findings.append(_finding("DUPLICATE_NODE", f"{location}.id", f"duplicate node id: {node_id}"))
            continue
        nodes[node_id] = raw_node
        if not _is_identifier(raw_node.get("role")):
            findings.append(_finding("IDENTIFIER", f"{location}.role", "must be a valid identifier"))
        if not _is_identifier(raw_node.get("independence_group")):
            findings.append(_finding("IDENTIFIER", f"{location}.independence_group", "must be a valid identifier"))
        _artifact_map(raw_node.get("inputs"), f"{location}.inputs", findings)
        _artifact_map(raw_node.get("outputs"), f"{location}.outputs", findings)
        if not isinstance(raw_node.get("as_of_policy"), str) or not raw_node.get("as_of_policy", "").strip():
            findings.append(_finding("AS_OF_POLICY", f"{location}.as_of_policy", "must be non-empty"))
        tools = raw_node.get("allowed_tools")
        if not isinstance(tools, list) or any(not isinstance(tool, str) or not tool for tool in tools):
            findings.append(_finding("TYPE", f"{location}.allowed_tools", "must be an array of non-empty strings"))
        if raw_node.get("side_effect") not in SIDE_EFFECTS:
            findings.append(_finding("SIDE_EFFECT", f"{location}.side_effect", "invalid side-effect class"))
        if raw_node.get("join_policy") not in {"any", "all"}:
            findings.append(_finding("JOIN_POLICY", f"{location}.join_policy", "must be any or all"))
        timeout = raw_node.get("timeout_seconds")
        retry = raw_node.get("retry_limit")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            findings.append(_finding("BOUND", f"{location}.timeout_seconds", "must be an integer >= 1"))
        if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
            findings.append(_finding("BOUND", f"{location}.retry_limit", "must be an integer >= 0"))
        for nullable_identifier in ("verifier", "required_approval"):
            value = raw_node.get(nullable_identifier)
            if value is not None and not _is_identifier(value):
                findings.append(_finding("IDENTIFIER", f"{location}.{nullable_identifier}", "must be an identifier or null"))

    entry = spec.get("entry_node")
    if entry not in nodes:
        findings.append(_finding("ENTRY", "$.entry_node", "entry node does not exist"))

    raw_edges = spec.get("edges")
    if not isinstance(raw_edges, list):
        findings.append(_finding("TYPE", "$.edges", "must be an array"))
        raw_edges = []
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    incoming_edges: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in nodes}
    self_loops: set[str] = set()
    valid_edges: list[dict[str, Any]] = []
    for index, edge in enumerate(raw_edges):
        location = f"$.edges[{index}]"
        if not isinstance(edge, dict):
            findings.append(_finding("TYPE", location, "edge must be an object"))
            continue
        required = {"from", "to", "condition", "artifacts"}
        for field in sorted(required - set(edge)):
            findings.append(_finding("REQUIRED", location, f"missing edge field: {field}"))
        for field in sorted(set(edge) - required):
            findings.append(_finding("UNKNOWN_FIELD", f"{location}.{field}", "unknown edge field"))
        source = edge.get("from")
        target = edge.get("to")
        if source not in nodes:
            findings.append(_finding("EDGE_NODE", f"{location}.from", f"unknown source node: {source}"))
        if target not in nodes:
            findings.append(_finding("EDGE_NODE", f"{location}.to", f"unknown target node: {target}"))
        condition = edge.get("condition")
        if not isinstance(condition, str) or not condition.strip():
            findings.append(_finding("CONDITION", f"{location}.condition", "must be non-empty"))
        artifacts = edge.get("artifacts")
        if not isinstance(artifacts, list) or any(not _is_identifier(item) for item in artifacts):
            findings.append(_finding("TYPE", f"{location}.artifacts", "must be an array of artifact identifiers"))
            artifacts = []
        if len(artifacts) != len(set(artifacts)):
            findings.append(_finding("DUPLICATE_ARTIFACT", f"{location}.artifacts", "must not contain duplicates"))
        if source not in nodes or target not in nodes:
            continue
        edge = {**edge, "artifacts": artifacts}
        valid_edges.append(edge)
        outgoing[source].append(target)
        incoming_edges[target].append(edge)
        if source == target:
            self_loops.add(source)
        source_outputs = nodes[source].get("outputs") if isinstance(nodes[source].get("outputs"), dict) else {}
        target_inputs = nodes[target].get("inputs") if isinstance(nodes[target].get("inputs"), dict) else {}
        for artifact in artifacts:
            if artifact not in source_outputs:
                findings.append(_finding("UNDECLARED_OUTPUT", location, f"{source} does not output {artifact}"))
                continue
            if artifact not in target_inputs:
                findings.append(_finding("UNDECLARED_INPUT", location, f"{target} does not accept {artifact}"))
                continue
            if source_outputs[artifact] != target_inputs[artifact]:
                findings.append(
                    _finding(
                        "SCHEMA_MISMATCH",
                        location,
                        f"{artifact}: {source_outputs[artifact]} -> {target_inputs[artifact]}",
                    )
                )

    if entry in nodes:
        reachable: set[str] = set()
        queue = [entry]
        while queue:
            current = queue.pop()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(outgoing.get(current, []))
        for node_id in sorted(set(nodes) - reachable):
            findings.append(_finding("ORPHAN", f"$.nodes[{node_id}]", "node is unreachable from entry"))

    for node_id, node in nodes.items():
        supplied = set(external_inputs)
        for edge in incoming_edges[node_id]:
            supplied.update(edge["artifacts"])
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for artifact in sorted(set(inputs) - supplied):
            findings.append(_finding("UNSATISFIED_INPUT", f"$.nodes[{node_id}].inputs.{artifact}", "no incoming edge or external input supplies it"))

    approvals_value = spec.get("approvals")
    if not isinstance(approvals_value, list):
        findings.append(_finding("TYPE", "$.approvals", "must be an array"))
        approvals_value = []
    approvals: dict[str, dict[str, Any]] = {}
    for index, approval in enumerate(approvals_value):
        location = f"$.approvals[{index}]"
        if not isinstance(approval, dict) or not _is_identifier(approval.get("id")):
            findings.append(_finding("APPROVAL", location, "approval must have a valid id"))
            continue
        approval_id = approval["id"]
        if approval_id in approvals:
            findings.append(_finding("DUPLICATE_APPROVAL", location, f"duplicate approval id: {approval_id}"))
        approvals[approval_id] = approval

    for node_id, node in nodes.items():
        role = node.get("role")
        verifier_id = node.get("verifier")
        if (role in MAKER_ROLES or node.get("side_effect") != "none") and not verifier_id:
            findings.append(
                _finding(
                    "VERIFIER_REQUIRED",
                    f"$.nodes[{node_id}].verifier",
                    "maker or side-effect node requires an independent verifier",
                )
            )
        if verifier_id:
            verifier = nodes.get(verifier_id)
            if verifier is None:
                findings.append(_finding("VERIFIER_NODE", f"$.nodes[{node_id}].verifier", "verifier node does not exist"))
            else:
                if verifier.get("role") != "verifier":
                    findings.append(_finding("VERIFIER_ROLE", f"$.nodes[{verifier_id}].role", "referenced verifier must have role verifier"))
                if verifier.get("independence_group") == node.get("independence_group"):
                    findings.append(_finding("VERIFIER_INDEPENDENCE", f"$.nodes[{node_id}].verifier", "maker and verifier must use different independence groups"))

        side_effect = node.get("side_effect")
        if side_effect in {"write", "external", "promotion"}:
            approval_id = node.get("required_approval")
            approval = approvals.get(approval_id)
            if approval is None:
                findings.append(_finding("APPROVAL_REQUIRED", f"$.nodes[{node_id}].required_approval", f"{side_effect} requires a declared approval"))
            else:
                if approval.get("scope") != side_effect:
                    findings.append(_finding("APPROVAL_SCOPE", f"$.approvals[{approval_id}]", f"scope must equal {side_effect}"))
                if approval.get("status") != "approved" or not approval.get("approved_by") or not approval.get("approved_at"):
                    findings.append(_finding("APPROVAL_STATUS", f"$.approvals[{approval_id}]", "side-effect approval must be approved and attributable"))
        elif node.get("required_approval") is not None:
            findings.append(_finding("UNUSED_APPROVAL", f"$.nodes[{node_id}].required_approval", "read-only node must not require an approval"))

        if side_effect == "promotion":
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            for artifact, schema in {
                "gate_decision": "GateDecision",
                "route": "Route",
                "strategy_version": "StrategyVersion",
            }.items():
                if inputs.get(artifact) != schema:
                    findings.append(_finding("PROMOTION_INPUT", f"$.nodes[{node_id}].inputs", f"promotion requires {artifact}: {schema}"))
            gate_sources = []
            for edge in incoming_edges[node_id]:
                if "gate_decision" in edge["artifacts"]:
                    gate_sources.append(edge["from"])
            if not gate_sources or any(nodes[source].get("role") != "gate" for source in gate_sources):
                findings.append(_finding("PROMOTION_GATE", f"$.nodes[{node_id}]", "promotion requires GateDecision from a gate node"))
            approval = approvals.get(node.get("required_approval"))
            if approval and (not approval.get("route") or not approval.get("strategy_version")):
                findings.append(_finding("PROMOTION_APPROVAL", f"$.approvals[{approval.get('id')}]", "promotion approval must bind route and strategy_version"))

    fan_in_value = spec.get("fan_in")
    if not isinstance(fan_in_value, list):
        findings.append(_finding("TYPE", "$.fan_in", "must be an array"))
        fan_in_value = []
    fan_in_by_node: dict[str, dict[str, Any]] = {}
    for index, barrier in enumerate(fan_in_value):
        location = f"$.fan_in[{index}]"
        if not isinstance(barrier, dict) or barrier.get("node") not in nodes:
            findings.append(_finding("FAN_IN_NODE", location, "fan-in node does not exist"))
            continue
        node_id = barrier["node"]
        if node_id in fan_in_by_node:
            findings.append(_finding("DUPLICATE_FAN_IN", location, f"duplicate fan-in declaration for {node_id}"))
        fan_in_by_node[node_id] = barrier

    for node_id, node in nodes.items():
        predecessors = {edge["from"] for edge in incoming_edges[node_id]}
        barrier = fan_in_by_node.get(node_id)
        if node.get("join_policy") == "all" and len(predecessors) >= 2:
            if barrier is None:
                findings.append(_finding("FAN_IN_REQUIRED", f"$.nodes[{node_id}]", "synchronized multi-input node requires fan_in declaration"))
                continue
            required_predecessors = set(barrier.get("required_predecessors", []))
            if required_predecessors != predecessors:
                findings.append(_finding("FAN_IN_PREDECESSORS", f"$.fan_in[{node_id}]", f"expected {sorted(predecessors)}, got {sorted(required_predecessors)}"))
            required_artifacts = barrier.get("required_artifacts")
            if not isinstance(required_artifacts, list) or not required_artifacts:
                findings.append(_finding("FAN_IN_ARTIFACTS", f"$.fan_in[{node_id}]", "required_artifacts must be non-empty"))
                required_artifacts = []
            for predecessor in predecessors:
                edge_artifacts: set[str] = set()
                for edge in incoming_edges[node_id]:
                    if edge["from"] == predecessor:
                        edge_artifacts.update(edge["artifacts"])
                missing = sorted(set(required_artifacts) - edge_artifacts)
                if missing:
                    findings.append(_finding("FAN_IN_ARTIFACTS", f"$.fan_in[{node_id}]", f"{predecessor} is missing {missing}"))
            if barrier.get("require_same_snapshot_hash"):
                if "data_manifest_hash" not in required_artifacts:
                    findings.append(_finding("FAN_IN_SNAPSHOT", f"$.fan_in[{node_id}]", "same-snapshot barrier must require data_manifest_hash"))
                inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
                if inputs.get("data_manifest_hash") != "ContentHash":
                    findings.append(_finding("FAN_IN_SNAPSHOT", f"$.nodes[{node_id}].inputs", "data_manifest_hash must use ContentHash schema"))
        elif barrier is not None:
            findings.append(_finding("UNUSED_FAN_IN", f"$.fan_in[{node_id}]", "fan_in requires join_policy all and at least two predecessors"))

    components = _strongly_connected_components(set(nodes), outgoing)
    detected_cycles = [
        component
        for component in components
        if len(component) > 1 or any(node in self_loops for node in component)
    ]
    cycles_value = spec.get("cycles")
    if not isinstance(cycles_value, list):
        findings.append(_finding("TYPE", "$.cycles", "must be an array"))
        cycles_value = []
    declared_cycles: list[tuple[set[str], dict[str, Any], int]] = []
    for index, cycle in enumerate(cycles_value):
        location = f"$.cycles[{index}]"
        if not isinstance(cycle, dict):
            findings.append(_finding("TYPE", location, "cycle must be an object"))
            continue
        members = set(cycle.get("nodes", [])) if isinstance(cycle.get("nodes"), list) else set()
        declared_cycles.append((members, cycle, index))
        for field in ("progress_signal", "abort_condition"):
            if not isinstance(cycle.get(field), str) or not cycle.get(field, "").strip():
                findings.append(_finding("CYCLE_BOUND", f"{location}.{field}", "must be non-empty"))
        max_iterations = cycle.get("max_iterations")
        if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) or max_iterations < 1:
            findings.append(_finding("CYCLE_BOUND", f"{location}.max_iterations", "must be an integer >= 1"))
        for exit_field in ("success_exit", "failure_exit"):
            exit_node = cycle.get(exit_field)
            if exit_node not in nodes or exit_node in members:
                findings.append(_finding("CYCLE_EXIT", f"{location}.{exit_field}", "must name a node outside the cycle"))
            elif not any(edge["from"] in members and edge["to"] == exit_node for edge in valid_edges):
                findings.append(_finding("CYCLE_EXIT", f"{location}.{exit_field}", "cycle has no edge to declared exit"))

    for component in detected_cycles:
        matches = [item for item in declared_cycles if item[0] == component]
        if not matches:
            findings.append(_finding("UNBOUNDED_CYCLE", "$.cycles", f"cycle {sorted(component)} has no exact bounded declaration"))
        elif len(matches) > 1:
            findings.append(_finding("DUPLICATE_CYCLE", "$.cycles", f"cycle {sorted(component)} is declared more than once"))
    for members, _, index in declared_cycles:
        if members not in detected_cycles:
            findings.append(_finding("STALE_CYCLE", f"$.cycles[{index}]", f"declared nodes {sorted(members)} are not one detected cycle"))

    return sorted(set(findings))


def _self_test_spec() -> dict[str, Any]:
    shared = {name: "StateValue" for name in sorted(SHARED_STATE_FIELDS)}
    nodes = [
        {
            "id": "entry",
            "role": "contract",
            "independence_group": "control",
            "inputs": {},
            "outputs": {"data_manifest_hash": "ContentHash", "contract": "Contract"},
            "as_of_policy": "Use the declared cutoff.",
            "allowed_tools": ["read"],
            "side_effect": "none",
            "join_policy": "any",
            "timeout_seconds": 60,
            "retry_limit": 0,
            "verifier": None,
            "required_approval": None,
        },
        {
            "id": "audit_a",
            "role": "auditor",
            "independence_group": "audit-a",
            "inputs": {"data_manifest_hash": "ContentHash", "contract": "Contract"},
            "outputs": {"data_manifest_hash": "ContentHash", "audit_a": "AuditA"},
            "as_of_policy": "Do not cross the cutoff.",
            "allowed_tools": ["read"],
            "side_effect": "none",
            "join_policy": "any",
            "timeout_seconds": 60,
            "retry_limit": 1,
            "verifier": None,
            "required_approval": None,
        },
        {
            "id": "audit_b",
            "role": "auditor",
            "independence_group": "audit-b",
            "inputs": {"data_manifest_hash": "ContentHash", "contract": "Contract"},
            "outputs": {"data_manifest_hash": "ContentHash", "audit_b": "AuditB"},
            "as_of_policy": "Do not cross the cutoff.",
            "allowed_tools": ["read"],
            "side_effect": "none",
            "join_policy": "any",
            "timeout_seconds": 60,
            "retry_limit": 1,
            "verifier": None,
            "required_approval": None,
        },
        {
            "id": "join",
            "role": "integrator",
            "independence_group": "control",
            "inputs": {"data_manifest_hash": "ContentHash", "audit_a": "AuditA", "audit_b": "AuditB"},
            "outputs": {"report": "Report"},
            "as_of_policy": "Require one snapshot.",
            "allowed_tools": ["read"],
            "side_effect": "none",
            "join_policy": "all",
            "timeout_seconds": 60,
            "retry_limit": 0,
            "verifier": None,
            "required_approval": None,
        },
    ]
    return {
        "version": "1.0",
        "graph_id": "self-test",
        "entry_node": "entry",
        "external_inputs": {},
        "shared_state_schema": shared,
        "nodes": nodes,
        "edges": [
            {"from": "entry", "to": "audit_a", "condition": "success", "artifacts": ["data_manifest_hash", "contract"]},
            {"from": "entry", "to": "audit_b", "condition": "success", "artifacts": ["data_manifest_hash", "contract"]},
            {"from": "audit_a", "to": "join", "condition": "success", "artifacts": ["data_manifest_hash", "audit_a"]},
            {"from": "audit_b", "to": "join", "condition": "success", "artifacts": ["data_manifest_hash", "audit_b"]},
        ],
        "cycles": [],
        "fan_in": [
            {
                "node": "join",
                "required_predecessors": ["audit_a", "audit_b"],
                "required_artifacts": ["data_manifest_hash"],
                "require_same_snapshot_hash": True,
            }
        ],
        "approvals": [],
    }


def run_self_test() -> None:
    valid = _self_test_spec()
    assert not validate_graph(valid), validate_graph(valid)

    orphan = copy.deepcopy(valid)
    orphan["nodes"].append({**copy.deepcopy(valid["nodes"][0]), "id": "orphan"})
    assert "ORPHAN" in {item.code for item in validate_graph(orphan)}

    mismatch = copy.deepcopy(valid)
    mismatch["nodes"][1]["inputs"]["contract"] = "WrongContract"
    assert "SCHEMA_MISMATCH" in {item.code for item in validate_graph(mismatch)}

    no_snapshot = copy.deepcopy(valid)
    no_snapshot["fan_in"][0]["require_same_snapshot_hash"] = True
    no_snapshot["fan_in"][0]["required_artifacts"] = ["audit_a"]
    assert "FAN_IN_SNAPSHOT" in {item.code for item in validate_graph(no_snapshot)}

    cycle = copy.deepcopy(valid)
    cycle["nodes"][1]["inputs"]["report"] = "Report"
    cycle["nodes"][3]["outputs"]["report"] = "Report"
    cycle["edges"].append({"from": "join", "to": "audit_a", "condition": "retry", "artifacts": ["report"]})
    assert "UNBOUNDED_CYCLE" in {item.code for item in validate_graph(cycle)}

    maker = copy.deepcopy(valid)
    maker["nodes"][1]["role"] = "maker"
    assert "VERIFIER_REQUIRED" in {item.code for item in validate_graph(maker)}

    write = copy.deepcopy(valid)
    write["nodes"][1]["side_effect"] = "write"
    assert "APPROVAL_REQUIRED" in {item.code for item in validate_graph(write)}

    promotion = copy.deepcopy(valid)
    promotion["nodes"][1]["side_effect"] = "promotion"
    assert "PROMOTION_GATE" in {item.code for item in validate_graph(promotion)}

    schema_path = Path(__file__).resolve().parents[1] / "references" / "graph-spec.schema.json"
    json.loads(schema_path.read_text(encoding="utf-8"))
    print("SELF-TEST PASS: 7 invalid fixtures rejected and valid fixture accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", nargs="?", type=Path, help="graph JSON file")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable findings")
    parser.add_argument("--self-test", action="store_true", help="run embedded fixture tests")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.graph is None:
        parser.error("graph is required unless --self-test is used")
    try:
        spec = json.loads(args.graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    findings = validate_graph(spec)
    if args.as_json:
        print(json.dumps({"valid": not findings, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"{item.code} {item.location}: {item.message}")
    else:
        print(f"VALID {spec.get('graph_id')}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
