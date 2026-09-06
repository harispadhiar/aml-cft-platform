"""
Phase 1 Verification Test Suite
Tests:
  T1 — HITL Gate Enforcement (auto-SAR blocked)
  T2 — Workflow Progression (Analyst → MLRO → FILED)
  T3 — Audit Context Completeness
  T4 — RBAC enforcement on human-only gates
"""
import sys, os, json, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from services.orchestrator.stagegates import CaseWorkflow, GateType, STAGEGATES

logging.basicConfig(level=logging.WARNING)   # suppress noise during tests

PASS = "\033[92m✔ PASS\033[0m"
FAIL = "\033[91m✘ FAIL\033[0m"
results = []

def check(name, cond, detail=""):
    ok = bool(cond)
    tag = PASS if ok else FAIL
    print(f"  {tag}  {name}" + (f" — {detail}" if detail else ""))
    results.append((name, ok))
    return ok


# ─────────────────────────────────────────────
# T1 — HITL Gate Enforcement
# ─────────────────────────────────────────────
print("\n── T1: HITL Gate Enforcement ──")

wf = CaseWorkflow("HITL-TEST", "TENANT-A")
# Advance automated gates G01, G02
wf.run_automated_pipeline()

# Confirm we are now blocked on G03 (AI_ASSIST)
check("Case halts at first HITL gate (G03)",
      wf.current_gate and wf.current_gate.gate_type != GateType.AUTOMATED,
      f"Stopped at {wf.current_gate.id if wf.current_gate else 'N/A'}")

# Attempt to skip directly to G16 (MLRO_FILING_APPROVAL) — must fail
try:
    wf.human_only_advance("AI_Agent", "AGENT", "APPROVE", "Auto-filing attempt")
    check("AI agent bypasses HITL gate (must NOT happen)", False, "No exception raised!")
except (ValueError, PermissionError) as e:
    check("Orchestrator blocks automated transition past HITL gate",
          True, str(e)[:60])


# ─────────────────────────────────────────────
# T2 — Full Workflow Progression
# ─────────────────────────────────────────────
print("\n── T2: Workflow Progression Analyst → MLRO → FILED ──")

wf2 = CaseWorkflow("WORKFLOW-TEST", "TENANT-A")

def run_gate(wf, actor, role, decision="APPROVE", reason="Approved"):
    gate = wf.current_gate
    if gate is None:
        return
    if gate.gate_type == GateType.AUTOMATED:
        wf.run_automated_pipeline()
    elif gate.gate_type == GateType.AI_ASSIST:
        wf.ai_assisted_advance(actor, role, approved=(decision == "APPROVE"), reason=reason)
        wf.run_automated_pipeline()
    elif gate.gate_type == GateType.HUMAN_ONLY:
        try:
            wf.human_only_advance(actor, role, decision, reason)
        except PermissionError:
            pass   # handled in T4
        wf.run_automated_pipeline()

# Drive the workflow end-to-end
gate_actors = {
    "G03": ("Analyst_A", "Analyst"),
    "G06": ("Analyst_A", "Analyst"),
    "G07": ("Analyst_A", "Analyst"),
    "G08": ("Analyst_A", "Analyst"),
    "G09": ("MLRO_01",   "MLRO"),
    "G10": ("Analyst_A", "Analyst"),
    "G11": ("Analyst_A", "Analyst"),
    "G12": ("MLRO_01",   "MLRO"),
    "G13": ("Analyst_A", "Analyst"),
    "G14": ("Analyst_A", "Analyst"),
    "G15": ("MLRO_01",   "MLRO"),
    "G16": ("MLRO_01",   "MLRO"),
}

wf2.run_automated_pipeline()   # G01, G02
for _ in range(20):            # Safety cap
    gate = wf2.current_gate
    if gate is None:
        break
    actor, role = gate_actors.get(gate.id, ("Analyst_A", "Analyst"))
    run_gate(wf2, actor, role)

check("Workflow reaches COMPLETE state", wf2.is_complete,
      f"Gates done: {len(wf2.completed_gates)}/17")
check("All 17 gates completed",
      len(wf2.completed_gates) == 17,
      f"Completed: {wf2.completed_gates}")


# ─────────────────────────────────────────────
# T3 — Audit Context Completeness
# ─────────────────────────────────────────────
print("\n── T3: Audit Context Completeness ──")

audit = wf2.audit_trail
check("Audit trail non-empty", len(audit) > 0, f"{len(audit)} events")
check("Every event has timestamp",  all(e.timestamp for e in audit))
check("Every event has gate_id",    all(e.gate_id   for e in audit))
check("Every event has actor",      all(e.actor     for e in audit))
check("Every event has role",       all(e.role      for e in audit))
check("Every event has action",     all(e.action    for e in audit))
check("Every event has detail",     all(e.detail    for e in audit))

# Check System + MLRO + Analyst all appear in trail
actors_in_trail = {e.actor for e in audit}
roles_in_trail  = {e.role  for e in audit}
check("System events recorded",  "System"     in actors_in_trail)
check("Analyst events recorded", "Analyst_A"  in actors_in_trail)
check("MLRO events recorded",    "MLRO_01"    in actors_in_trail)


# ─────────────────────────────────────────────
# T4 — RBAC: Analyst cannot approve MLRO-only gates
# ─────────────────────────────────────────────
print("\n── T4: RBAC Enforcement ──")

wf3 = CaseWorkflow("RBAC-TEST", "TENANT-A")
# Advance to G09 (EDD_COMPLETION — MLRO only)
try:
    wf3.run_automated_pipeline()          # G01, G02
    wf3.ai_assisted_advance("A","Analyst",True,"ok")    # G03
    wf3.run_automated_pipeline()          # G04, G05
    wf3.ai_assisted_advance("A","Analyst",True,"ok")    # G06
    wf3.human_only_advance("A","Analyst","APPROVE","ok") # G07
    wf3.ai_assisted_advance("A","Analyst",True,"ok")    # G08
    # Now at G09 — Analyst tries to approve
    try:
        wf3.human_only_advance("Analyst_A", "Analyst", "APPROVE", "Trying to bypass")
        check("Analyst blocked from MLRO-only gate G09", False, "No exception!")
    except PermissionError as e:
        check("Analyst blocked from MLRO-only gate G09", True, str(e)[:70])
except Exception as e:
    check("RBAC test setup error", False, str(e))


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
print("\n══════════════════════════════════════")
passed = sum(1 for _, ok in results if ok)
total  = len(results)
print(f"  Phase 1 Verification: {passed}/{total} checks passed")
if passed < total:
    print("  FAILED checks:")
    for name, ok in results:
        if not ok:
            print(f"    ✘ {name}")
print("══════════════════════════════════════\n")
sys.exit(0 if passed == total else 1)
