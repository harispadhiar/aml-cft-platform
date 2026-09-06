"""
case_mgmt_mcp/server.py
MCP server wrapping marble-style case management with our 17-stagegate workflow.
Provides: create_case, advance_gate, get_case_state, list_cases, get_audit_trail
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# resolve project root
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from services.orchestrator.stagegates import CaseWorkflow, STAGEGATES, GateType
from services.risk_scoring.engine import RiskScoringEngine

logger = logging.getLogger("case-mgmt-mcp")

# ── In-memory store (swap for per-tenant Postgres in production) ──────────
_CASES: dict[str, CaseWorkflow] = {}
_RISK_ENGINE = RiskScoringEngine()

# ── Tool implementations (callable from agent or HTTP) ───────────────────

def create_case(tenant_id: str, case_id: str, case_data: dict) -> dict:
    """
    Create a new case, run deterministic risk scoring, auto-advance
    through initial automated gates, and halt at the first HITL gate.
    """
    wf = CaseWorkflow(case_id, tenant_id)
    wf.data = case_data
    _CASES[case_id] = wf

    # Score the case
    score_result = _RISK_ENGINE.score_case(case_data)
    wf.data["risk_score_result"] = score_result

    # Run automated pipeline until first HITL gate
    wf.run_automated_pipeline()

    return {
        "case_id": case_id,
        "current_gate": wf.current_gate.id if wf.current_gate else "COMPLETE",
        "risk_tier": score_result["risk_tier"],
        "triggered_rules": score_result["triggered_rules"],
    }


def advance_gate(case_id: str, actor: str, role: str, decision: str, reason: str) -> dict:
    """
    Advance a case through its current gate.
    - For AI_ASSIST gates: decision must be 'APPROVE' or 'OVERRIDE_REJECT'
    - For HUMAN_ONLY gates: decision must be 'APPROVE' or 'REJECT'
    - For AUTOMATED gates: returns error (advance automatically)
    HITL enforcement is inside CaseWorkflow — agent cannot bypass it.
    """
    wf = _CASES.get(case_id)
    if not wf:
        return {"error": f"Case {case_id} not found"}

    gate = wf.current_gate
    if gate is None:
        return {"error": "Workflow already complete"}

    try:
        if gate.gate_type == GateType.AI_ASSIST:
            wf.ai_assisted_advance(actor, role, approved=(decision == "APPROVE"), reason=reason)
        elif gate.gate_type == GateType.HUMAN_ONLY:
            wf.human_only_advance(actor, role, decision, reason)
        else:
            return {"error": f"Gate {gate.id} is AUTOMATED — cannot be manually advanced"}
    except PermissionError as e:
        return {"error": str(e), "code": "RBAC_DENIED"}

    # After advancing, run next automated gates
    wf.run_automated_pipeline()

    return {
        "case_id": case_id,
        "prev_gate": gate.id,
        "current_gate": wf.current_gate.id if wf.current_gate else "COMPLETE",
        "is_complete": wf.is_complete,
    }


def get_case_state(case_id: str) -> dict:
    wf = _CASES.get(case_id)
    if not wf:
        return {"error": f"Case {case_id} not found"}
    gate = wf.current_gate
    return {
        "case_id": case_id,
        "tenant_id": wf.tenant_id,
        "current_gate_id": gate.id if gate else "COMPLETE",
        "current_gate_name": gate.name if gate else "COMPLETE",
        "current_gate_type": gate.gate_type.value if gate else "N/A",
        "completed_gates": wf.completed_gates,
        "is_blocked_on_hitl": gate is not None and gate.gate_type != GateType.AUTOMATED,
        "is_complete": wf.is_complete,
        "data": wf.data,
    }


def list_cases(tenant_id: str | None = None, state_filter: str | None = None) -> list:
    results = []
    for case_id, wf in _CASES.items():
        if tenant_id and wf.tenant_id != tenant_id:
            continue
        gate = wf.current_gate
        gate_name = gate.name if gate else "COMPLETE"
        if state_filter and gate_name != state_filter:
            continue
        results.append({
            "case_id": case_id,
            "current_gate": gate.id if gate else "COMPLETE",
            "is_complete": wf.is_complete,
        })
    return results


def get_audit_trail(case_id: str) -> dict:
    wf = _CASES.get(case_id)
    if not wf:
        return {"error": f"Case {case_id} not found"}
    return {
        "case_id": case_id,
        "audit_events": [e.to_dict() for e in wf.audit_trail],
    }


# ── Expose as JSON-RPC style MCP tool set ─────────────────────────────────
MCP_TOOLS = {
    "create_case":     create_case,
    "advance_gate":    advance_gate,
    "get_case_state":  get_case_state,
    "list_cases":      list_cases,
    "get_audit_trail": get_audit_trail,
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Quick smoke test
    r = create_case("TENANT-A", "DEMO-001", {
        "case_id": "DEMO-001",
        "transaction_pattern": "10 cash deposits of PKR 950,000 within 48 hours.",
        "screening_hit": "True Positive NACTA match on entity name.",
        "risk_score": "High",
    })
    print("Created:", json.dumps(r, indent=2))
    print("State:", json.dumps(get_case_state("DEMO-001"), indent=2))
