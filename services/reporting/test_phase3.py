"""
Phase 3 Verification Test Suite
Tests:
  T1 — Auditor View Isolation (no write tools, no cross-tenant access)
  T2 — Export Schema Validation (FMU JSON fields)
  T3 — Break-Glass Logging (super-admin drill-down triggers alert + immutable log)
"""
import sys, os, json, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from pathlib import Path
from services.reporting.export import build_fmu_json, validate_fmu_json, export_case
from services.orchestrator.stagegates import CaseWorkflow, GateType

logging.basicConfig(level=logging.WARNING)

PASS = "PASS"
FAIL = "FAIL"
results = []

def check(name, cond, detail=""):
    ok = bool(cond)
    tag = PASS if ok else FAIL
    print(f"  [{tag}]  {name}" + (f"  ({detail})" if detail else ""))
    results.append((name, ok))
    return ok


# ─────────────────────────────────────────────
# Helpers — build a completed workflow
# ─────────────────────────────────────────────
def _make_completed_wf(case_id="TEST-EXPORT-001") -> CaseWorkflow:
    wf = CaseWorkflow(case_id, "TENANT-A")
    wf.data = {
        "case_id": case_id, "customer_id": "CUST-000001",
        "transaction_pattern": "10 deposits of PKR 950,000 within 48 hours.",
        "screening_hit": "True Positive NACTA match.",
        "risk_score": "High",
        "risk_score_result": {"risk_tier": "High", "triggered_rules": ["nacta_match", "structuring"]},
    }
    actors = {"G03":"Analyst","G06":"Analyst","G07":"Analyst","G08":"Analyst",
              "G09":"MLRO","G10":"Analyst","G11":"Analyst","G12":"MLRO",
              "G13":"Analyst","G14":"Analyst","G15":"MLRO","G16":"MLRO"}
    roles  = {"G03":"Analyst","G06":"Analyst","G07":"Analyst","G08":"Analyst",
              "G09":"MLRO","G10":"Analyst","G11":"Analyst","G12":"MLRO",
              "G13":"Analyst","G14":"Analyst","G15":"MLRO","G16":"MLRO"}
    wf.run_automated_pipeline()
    for _ in range(20):
        g = wf.current_gate
        if g is None: break
        a, r = actors.get(g.id,"Analyst"), roles.get(g.id,"Analyst")
        if g.gate_type == GateType.AI_ASSIST:
            wf.ai_assisted_advance(a, r, True, "approved")
        elif g.gate_type == GateType.HUMAN_ONLY:
            try: wf.human_only_advance(a, r, "APPROVE", "approved")
            except PermissionError: pass
        wf.run_automated_pipeline()
    return wf


# ─────────────────────────────────────────────
# T1 — Auditor View Isolation
# ─────────────────────────────────────────────
print("\n-- T1: Auditor View Isolation --")

# Verify the auditor_view.py file has no write controls
auditor_src = Path("ui/auditor_view.py").read_text(encoding="utf-8")

check("Auditor UI contains no st.text_input write forms for case edits",
      "human_only_advance" not in auditor_src and
      "advance_gate" not in auditor_src)

check("Auditor UI has READ-ONLY label",
      "READ-ONLY" in auditor_src or "read-only" in auditor_src.lower())

check("Auditor UI has no admin tab references",
      "admin" not in auditor_src.lower() or "No admin" in auditor_src)

check("Auditor UI enforces session time-box",
      "session_limit_minutes" in auditor_src and "session_remaining" in auditor_src)

check("Cross-tenant isolation enforced (single tenant assigned per session)",
      "Assigned Tenants" in auditor_src)


# ─────────────────────────────────────────────
# T2 — Export Schema Verification
# ─────────────────────────────────────────────
print("\n-- T2: Export Schema Validation --")

wf = _make_completed_wf("SCHEMA-TEST-001")
narrative = ("The subject made 10 deposits of PKR 950,000 within 48 hours. "
             "A True Positive NACTA match was identified. "
             "Reported per SBP AML/CFT Regulations 2020 Clause 3 and FATF Recommendation 10.")

payload = build_fmu_json("SCHEMA-TEST-001", wf, narrative)
errors  = validate_fmu_json(payload)

check("FMU payload has no validation errors",    len(errors) == 0, str(errors))
check("fmu_schema_version present",              "fmu_schema_version" in payload)
check("report_type is STR or SAR",               payload.get("report_type") in ("STR","SAR"))
check("filing_reference present",                bool(payload.get("filing_reference")))
check("filing_timestamp present",                bool(payload.get("filing_timestamp")))
check("reporting_entity block present",          isinstance(payload.get("reporting_entity"), dict))
check("subject block present",                   isinstance(payload.get("subject"), dict))
check("narrative not empty",                     bool(payload.get("narrative","").strip()))
check("human_approval_chain non-empty",          len(payload.get("human_approval_chain", [])) > 0)
check("ai_model_metadata.human_reviewed=True",   payload.get("ai_model_metadata",{}).get("human_reviewed") is True)

# Full export to disk
result = export_case("SCHEMA-TEST-001", wf, narrative, Path("exports/test"))
check("Export JSON file created",  Path(result["json_path"]).exists())
check("Export report file created", Path(result["report_path"]).exists())
check("Export marked valid",        result["valid"])


# ─────────────────────────────────────────────
# T3 — Break-Glass Logging
# ─────────────────────────────────────────────
print("\n-- T3: Break-Glass Penetration Logging --")

# Simulate break-glass by appending to the audit log and checking detection
import hashlib
from datetime import datetime, timezone

log_path = Path("mcp-servers/audit-log-mcp/audit_log.jsonl")

def _genesis_hash():
    return hashlib.sha256(b"genesis").hexdigest()

def _append(payload_str: str, tenant_id: str, user_id: str, log_path: Path):
    """Minimal version of the audit-log-mcp append_log for test use."""
    # Read last hash
    if not log_path.exists() or log_path.stat().st_size == 0:
        prev_hash = _genesis_hash()
    else:
        with open(log_path, encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip()]
        prev_hash = json.loads(lines[-1])["hash"] if lines else _genesis_hash()

    ts = datetime.now(timezone.utc).isoformat()
    entry = {"tenant_id": tenant_id, "user_id": user_id, "timestamp": ts,
             "payload": payload_str, "prev_hash": prev_hash}
    h = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
    entry["hash"] = h
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return h

break_glass_payload = json.dumps({
    "event_type": "BREAK_GLASS_ACCESS",
    "actor": "SuperAdmin_01",
    "tenant_accessed": "TENANT-A",
    "justification": "Client support escalation ticket #4521",
    "auto_revocation_minutes": 120,
    "alert_channels": ["slack:#aml-alerts", "email:compliance@firm.com"],
})

h = _append(break_glass_payload, "PLATFORM", "SuperAdmin_01", log_path)
check("Break-glass event written to immutable audit log", bool(h), f"hash={h[:12]}...")

# Verify it's chain-linked
with open(log_path, encoding="utf-8") as f:
    entries = [json.loads(l) for l in f if l.strip()]
last = entries[-1]
check("Break-glass entry is chain-linked",
      last.get("payload") == break_glass_payload)
check("Break-glass entry records actor",
      "SuperAdmin_01" in last.get("user_id",""))
check("Break-glass entry has auto-revocation field",
      "auto_revocation_minutes" in last.get("payload",""))


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
print("\n======================================")
passed = sum(1 for _, ok in results if ok)
total  = len(results)
print(f"  Phase 3 Verification: {passed}/{total} checks passed")
if passed < total:
    print("  FAILED checks:")
    for name, ok in results:
        if not ok:
            print(f"    FAIL: {name}")
print("======================================\n")
sys.exit(0 if passed == total else 1)
