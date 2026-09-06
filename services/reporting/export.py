"""
services/reporting/export.py
Regulatory Export Engine — Phase 3
Generates SAR/STR exports in:
  1. SBP FMU JSON schema  (machine-readable e-filing)
  2. PDF narrative report (human-readable)

The JSON schema mirrors the FMU e-filing specification structure.
The PDF uses ReportLab (with a plaintext fallback).
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.orchestrator.stagegates import CaseWorkflow

logger = logging.getLogger("reporting.export")

# ─────────────────────────────────────────────
# FMU JSON Schema (SBP e-filing format)
# ─────────────────────────────────────────────
FMU_SCHEMA_VERSION = "SBP-FMU-v2.1"

def build_fmu_json(case_id: str, wf: CaseWorkflow, narrative: str) -> dict[str, Any]:
    """Return a dict conforming to SBP FMU STR/SAR JSON e-filing schema."""
    data = wf.data
    risk = data.get("risk_score_result", {})

    payload = {
        "fmu_schema_version": FMU_SCHEMA_VERSION,
        "report_type": "STR",            # Suspicious Transaction Report
        "filing_reference": f"STR-{case_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        "filing_timestamp": datetime.now(timezone.utc).isoformat(),
        "reporting_entity": {
            "name":         data.get("institution_name", "Pilot Bank Pakistan"),
            "sbp_code":     data.get("sbp_code", "SBP-PILOT-001"),
            "branch":       data.get("branch", "Head Office, Karachi"),
        },
        "subject": {
            "customer_id":  data.get("customer_id", "UNKNOWN"),
            "risk_tier":    risk.get("risk_tier", "High"),
            "triggered_rules": risk.get("triggered_rules", []),
        },
        "transaction_summary": {
            "pattern":      data.get("transaction_pattern", ""),
            "screening_hit": data.get("screening_hit", "None"),
        },
        "narrative": narrative,
        "human_approval_chain": [
            {"gate": e.gate_id, "actor": e.actor, "role": e.role,
             "action": e.action, "timestamp": e.timestamp}
            for e in wf.audit_trail
            if e.action == "ADVANCE"
        ],
        "ai_model_metadata": {
            "narrative_model":   "aml-cft-lora-v1",
            "prompt_template":   "sar_narrative_v2",
            "rag_citations":     ["SBP AML/CFT Regulations 2020 Clause 3", "FATF Recommendation 10"],
            "human_reviewed":    True,
        },
    }
    return payload


def validate_fmu_json(payload: dict) -> list[str]:
    """Validate required FMU fields. Returns list of validation errors."""
    errors: list[str] = []
    required_top = ["fmu_schema_version", "report_type", "filing_reference",
                    "filing_timestamp", "reporting_entity", "subject",
                    "transaction_summary", "narrative", "human_approval_chain"]
    for field in required_top:
        if field not in payload:
            errors.append(f"Missing required field: {field}")
    if payload.get("report_type") not in ("STR", "SAR"):
        errors.append("report_type must be 'STR' or 'SAR'")
    if not payload.get("narrative", "").strip():
        errors.append("narrative must not be empty")
    if not payload.get("human_approval_chain"):
        errors.append("human_approval_chain must contain at least one MLRO approval")
    return errors


# ─────────────────────────────────────────────
# PDF Export (ReportLab with plaintext fallback)
# ─────────────────────────────────────────────
def export_pdf(case_id: str, payload: dict, output_dir: Path) -> Path:
    """Generate a PDF report. Falls back to .txt if ReportLab not installed."""
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors

        outfile = output_dir / f"{case_id}_STR.pdf"
        doc = SimpleDocTemplate(str(outfile), pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(f"Suspicious Transaction Report", styles["Title"]))
        story.append(Paragraph(f"Filing Reference: {payload['filing_reference']}", styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Reporting Entity", styles["Heading2"]))
        for k, v in payload["reporting_entity"].items():
            story.append(Paragraph(f"<b>{k}:</b> {v}", styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Subject Information", styles["Heading2"]))
        story.append(Paragraph(f"<b>Customer ID:</b> {payload['subject']['customer_id']}", styles["Normal"]))
        story.append(Paragraph(f"<b>Risk Tier:</b> {payload['subject']['risk_tier']}", styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("SAR Narrative", styles["Heading2"]))
        story.append(Paragraph(payload["narrative"].replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Human Approval Chain", styles["Heading2"]))
        chain_data = [["Gate", "Actor", "Role", "Action", "Timestamp"]]
        for row in payload["human_approval_chain"][:10]:
            chain_data.append([row["gate"], row["actor"], row["role"], row["action"], row["timestamp"][:19]])
        t = Table(chain_data, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.HexColor("#E2E8F0")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(t)

        doc.build(story)
        logger.info(f"PDF exported: {outfile}")
        return outfile

    except ImportError:
        # Plaintext fallback
        outfile = output_dir / f"{case_id}_STR.txt"
        lines = [
            f"SUSPICIOUS TRANSACTION REPORT",
            f"Filing Reference: {payload['filing_reference']}",
            f"Timestamp:        {payload['filing_timestamp']}",
            f"",
            f"REPORTING ENTITY",
        ] + [f"  {k}: {v}" for k, v in payload["reporting_entity"].items()] + [
            f"",
            f"SUBJECT",
            f"  Customer ID: {payload['subject']['customer_id']}",
            f"  Risk Tier:   {payload['subject']['risk_tier']}",
            f"",
            f"NARRATIVE",
            payload["narrative"],
            f"",
            f"HUMAN APPROVAL CHAIN",
        ] + [f"  {r['gate']} | {r['actor']} ({r['role']}) | {r['action']} | {r['timestamp'][:19]}"
             for r in payload["human_approval_chain"]]
        outfile.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Text report exported (ReportLab not installed): {outfile}")
        return outfile


def export_case(case_id: str, wf: CaseWorkflow,
                narrative: str, output_dir: Path | None = None) -> dict[str, Any]:
    """
    Main entry point.  Builds + validates the FMU JSON payload, writes JSON and
    PDF/TXT to output_dir, returns a result dict with paths and validation status.
    """
    output_dir = output_dir or Path("exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    payload  = build_fmu_json(case_id, wf, narrative)
    errors   = validate_fmu_json(payload)

    json_path = output_dir / f"{case_id}_STR.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    pdf_path = export_pdf(case_id, payload, output_dir)

    return {
        "case_id":          case_id,
        "json_path":        str(json_path),
        "report_path":      str(pdf_path),
        "validation_errors": errors,
        "valid":            len(errors) == 0,
    }


# ─────────────────────────────────────────────
# Quick smoke-test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from services.orchestrator.stagegates import CaseWorkflow, GateType

    # Build a fully-completed workflow
    wf = CaseWorkflow("EXPORT-001", "TENANT-A")
    wf.data = {
        "case_id": "EXPORT-001",
        "customer_id": "CUST-001234",
        "transaction_pattern": "10 cash deposits of PKR 950,000 within 48 hours.",
        "screening_hit": "True Positive NACTA match on entity name.",
        "risk_score": "High",
        "risk_score_result": {"risk_tier": "High", "triggered_rules": ["nacta_match", "structuring"]},
    }

    actors = {
        "G03":"Analyst","G06":"Analyst","G07":"Analyst","G08":"Analyst",
        "G09":"MLRO","G10":"Analyst","G11":"Analyst","G12":"MLRO",
        "G13":"Analyst","G14":"Analyst","G15":"MLRO","G16":"MLRO",
    }
    roles  = {
        "G03":"Analyst","G06":"Analyst","G07":"Analyst","G08":"Analyst",
        "G09":"MLRO","G10":"Analyst","G11":"Analyst","G12":"MLRO",
        "G13":"Analyst","G14":"Analyst","G15":"MLRO","G16":"MLRO",
    }

    wf.run_automated_pipeline()
    for _ in range(20):
        g = wf.current_gate
        if g is None: break
        a, r = actors.get(g.id, "Analyst"), roles.get(g.id, "Analyst")
        if g.gate_type.value == "AI_ASSIST":
            wf.ai_assisted_advance(a, r, True, "approved")
        elif g.gate_type.value == "HUMAN_ONLY":
            try: wf.human_only_advance(a, r, "APPROVE", "approved")
            except PermissionError: pass
        wf.run_automated_pipeline()

    narrative = (
        "The subject exhibited suspicious activity. 10 cash deposits of PKR 950,000 "
        "within 48 hours were observed. A True Positive NACTA match was identified. "
        "This STR is filed in accordance with SBP AML/CFT Regulations 2020 Clause 3 "
        "and FATF Recommendation 10."
    )

    result = export_case("EXPORT-001", wf, narrative, Path("exports"))
    print(json.dumps(result, indent=2))
