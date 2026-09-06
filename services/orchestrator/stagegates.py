"""
17-Stagegate HITL Taxonomy — drawn from vyayasan/kyc-analyst checkpoint list.
Each gate is either:
  - AUTOMATED  : fully automated, no human needed
  - AI_ASSIST  : AI-assisted, mandatory human approval before next stage
  - HUMAN_ONLY : human decision required, AI cannot act
"""
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, List
import logging
import json
from datetime import datetime, timezone

logger = logging.getLogger("workflow")

# ─────────────────────────────────────────────
# Gate types
# ─────────────────────────────────────────────
class GateType(Enum):
    AUTOMATED  = "AUTOMATED"
    AI_ASSIST  = "AI_ASSIST"
    HUMAN_ONLY = "HUMAN_ONLY"

@dataclass
class Gate:
    id: str
    name: str
    gate_type: GateType
    description: str

# ─────────────────────────────────────────────
# 17-Stagegate Taxonomy (kyc-analyst-derived)
# ─────────────────────────────────────────────
STAGEGATES: List[Gate] = [
    Gate("G01", "CUSTOMER_DATA_INGESTION",         GateType.AUTOMATED,  "Raw customer/transaction data pulled from core banking"),
    Gate("G02", "WATCHLIST_SCREENING",              GateType.AUTOMATED,  "Auto screen against OFAC/UN/NACTA/SBP lists"),
    Gate("G03", "SCREENING_HIT_TRIAGE",             GateType.AI_ASSIST,  "AI classifies screening hit as FP/TP candidate; human confirms"),
    Gate("G04", "ADVERSE_MEDIA_CHECK",              GateType.AUTOMATED,  "Automated adverse media retrieval"),
    Gate("G05", "RISK_SCORE_COMPUTATION",           GateType.AUTOMATED,  "Deterministic rules + ML ensemble produces risk score"),
    Gate("G06", "RISK_TIER_ASSIGNMENT",             GateType.AI_ASSIST,  "AI suggests tier; analyst must confirm or override"),
    Gate("G07", "KYC_DOCUMENT_REVIEW",              GateType.HUMAN_ONLY, "Analyst manually verifies uploaded identity documents"),
    Gate("G08", "ENHANCED_DUE_DILIGENCE_TRIGGER",  GateType.AI_ASSIST,  "AI flags EDD requirement; analyst activates EDD workflow"),
    Gate("G09", "EDD_COMPLETION_REVIEW",            GateType.HUMAN_ONLY, "MLRO reviews completed EDD package"),
    Gate("G10", "RED_FLAG_CLASSIFICATION",          GateType.AI_ASSIST,  "AI maps red flags to FATF typologies; analyst approves mapping"),
    Gate("G11", "TRANSACTION_PATTERN_ANALYSIS",     GateType.AI_ASSIST,  "AI summarises structuring/velocity patterns; analyst confirms"),
    Gate("G12", "SANCTIONS_TRUE_POSITIVE_CONFIRM",  GateType.HUMAN_ONLY, "Only human can confirm true-positive sanctions match"),
    Gate("G13", "SAR_STR_NARRATIVE_DRAFT",          GateType.AI_ASSIST,  "Fine-tuned model drafts SAR narrative; analyst edits & approves"),
    Gate("G14", "ANALYST_SIGN_OFF",                 GateType.HUMAN_ONLY, "Tier-1/2 analyst formally signs off before escalation"),
    Gate("G15", "MLRO_ESCALATION_REVIEW",           GateType.HUMAN_ONLY, "MLRO reviews full case dossier"),
    Gate("G16", "MLRO_FILING_APPROVAL",             GateType.HUMAN_ONLY, "MLRO gives final approval; triggers FMU e-filing"),
    Gate("G17", "REGULATORY_EXPORT_DISPATCH",       GateType.AUTOMATED,  "System exports SAR/STR in SBP FMU schema and archives"),
]

GATE_MAP = {g.id: g for g in STAGEGATES}

# ─────────────────────────────────────────────
# Audit event helpers
# ─────────────────────────────────────────────
@dataclass
class AuditEvent:
    timestamp: str
    gate_id: str
    gate_name: str
    actor: str
    role: str
    action: str
    detail: str

    def to_dict(self):
        return self.__dict__

# ─────────────────────────────────────────────
# Case State Machine
# ─────────────────────────────────────────────
class CaseWorkflow:
    def __init__(self, case_id: str, tenant_id: str):
        self.case_id   = case_id
        self.tenant_id = tenant_id
        self.current_gate_idx: int = 0           # pointer into STAGEGATES list
        self.completed_gates: List[str] = []
        self.blocked: bool = False               # True when HITL gate not yet cleared
        self.audit_trail: List[AuditEvent] = []
        self.data: dict = {}                     # arbitrary case payload

    # ── current gate shortcuts ──────────────────
    @property
    def current_gate(self) -> Optional[Gate]:
        if self.current_gate_idx < len(STAGEGATES):
            return STAGEGATES[self.current_gate_idx]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_gate_idx >= len(STAGEGATES)

    # ── internal helpers ────────────────────────
    def _audit(self, actor: str, role: str, action: str, detail: str):
        gate = self.current_gate
        evt = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_id=gate.id if gate else "DONE",
            gate_name=gate.name if gate else "COMPLETE",
            actor=actor, role=role, action=action, detail=detail,
        )
        self.audit_trail.append(evt)
        logger.info(f"[{self.case_id}] [{evt.gate_id}] {actor}({role}): {action} — {detail}")

    def _advance(self, actor: str, role: str, detail: str = ""):
        gate = self.current_gate
        if gate is None:
            return
        self.completed_gates.append(gate.id)
        self._audit(actor, role, "ADVANCE", detail or f"Gate {gate.id} cleared")
        self.current_gate_idx += 1
        self.blocked = False

    # ── public API ──────────────────────────────
    def auto_advance(self):
        """Advance automated gates without human input."""
        gate = self.current_gate
        if gate and gate.gate_type == GateType.AUTOMATED:
            self._advance("System", "AUTOMATION", "Automated gate processed")
            return True
        return False

    def ai_assisted_advance(self, actor: str, role: str, approved: bool, reason: str):
        """Advance AI_ASSIST gate — requires explicit human approval."""
        gate = self.current_gate
        if not gate or gate.gate_type != GateType.AI_ASSIST:
            raise ValueError(f"Gate {gate.id if gate else 'N/A'} is not an AI_ASSIST gate")
        if not approved:
            self._audit(actor, role, "OVERRIDE_REJECT", reason)
            return False
        self._advance(actor, role, reason)
        return True

    def human_only_advance(self, actor: str, role: str, decision: str, reason: str):
        """
        Advance HUMAN_ONLY gate.  Enforces per-gate role requirements.
        Returns True on success, raises PermissionError on role mismatch.
        """
        gate = self.current_gate
        if not gate or gate.gate_type != GateType.HUMAN_ONLY:
            raise ValueError(f"Gate {gate.id if gate else 'N/A'} is not a HUMAN_ONLY gate")

        # Per-gate role enforcement
        required_roles = {
            "G07": ["Analyst", "MLRO"],
            "G09": ["MLRO"],
            "G12": ["MLRO", "Analyst"],
            "G14": ["Analyst", "MLRO"],
            "G15": ["MLRO"],
            "G16": ["MLRO"],
        }
        allowed = required_roles.get(gate.id, ["Analyst", "MLRO"])
        if role not in allowed:
            raise PermissionError(f"Role '{role}' cannot clear gate {gate.id} (requires one of {allowed})")

        if decision == "REJECT":
            self._audit(actor, role, "HUMAN_REJECT", reason)
            return False

        self._advance(actor, role, reason)
        return True

    def run_automated_pipeline(self):
        """Fast-forward all consecutive AUTOMATED gates from current position."""
        while self.current_gate and self.current_gate.gate_type == GateType.AUTOMATED:
            self.auto_advance()

    def audit_json(self) -> str:
        return json.dumps([e.to_dict() for e in self.audit_trail], indent=2)


# ─────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    wf = CaseWorkflow("CASE-99999", "TENANT-A")

    # G01, G02 — automated
    wf.run_automated_pipeline()

    # G03 SCREENING_HIT_TRIAGE — AI_ASSIST
    wf.ai_assisted_advance("Analyst_A", "Analyst", approved=True, reason="Confirmed TP NACTA hit")

    # G04, G05 — automated
    wf.run_automated_pipeline()

    # G06 RISK_TIER_ASSIGNMENT — AI_ASSIST
    wf.ai_assisted_advance("Analyst_A", "Analyst", approved=True, reason="Confirmed High tier")

    # G07 KYC_DOCUMENT_REVIEW — HUMAN_ONLY (Analyst)
    wf.human_only_advance("Analyst_A", "Analyst", "APPROVE", "Documents verified")

    # G08 EDD — AI_ASSIST
    wf.ai_assisted_advance("Analyst_A", "Analyst", approved=True, reason="EDD triggered")

    # G09 EDD_COMPLETION — HUMAN_ONLY (MLRO)
    try:
        wf.human_only_advance("Analyst_A", "Analyst", "APPROVE", "Analyst tries to approve MLRO gate")
    except PermissionError as e:
        print(f"RBAC ENFORCED: {e}")

    wf.human_only_advance("MLRO_01", "MLRO", "APPROVE", "EDD package accepted")

    # G10, G11 — AI_ASSIST
    wf.ai_assisted_advance("Analyst_A", "Analyst", approved=True, reason="Red flags mapped to FATF typology 8")
    wf.ai_assisted_advance("Analyst_A", "Analyst", approved=True, reason="Structuring pattern confirmed")

    # G12 SANCTIONS_TRUE_POSITIVE — HUMAN_ONLY
    wf.human_only_advance("MLRO_01", "MLRO", "APPROVE", "NACTA TP confirmed, funds frozen")

    # G13 SAR_NARRATIVE_DRAFT — AI_ASSIST
    wf.ai_assisted_advance("Analyst_A", "Analyst", approved=True, reason="Narrative approved with edits")

    # G14 ANALYST_SIGN_OFF — HUMAN_ONLY
    wf.human_only_advance("Analyst_A", "Analyst", "APPROVE", "Signed off and escalated to MLRO")

    # G15 MLRO_ESCALATION_REVIEW — HUMAN_ONLY
    wf.human_only_advance("MLRO_01", "MLRO", "APPROVE", "MLRO reviewed full dossier")

    # G16 MLRO_FILING_APPROVAL — HUMAN_ONLY
    wf.human_only_advance("MLRO_01", "MLRO", "APPROVE", "SAR approved for FMU filing")

    # G17 REGULATORY_EXPORT — AUTOMATED
    wf.run_automated_pipeline()

    print(f"\nWorkflow complete: {wf.is_complete}")
    print(f"Gates completed: {wf.completed_gates}")
    print(f"\nAudit trail ({len(wf.audit_trail)} events written)")
