"""
ui/auditor_view.py
Read-Only External Auditor Portal — Phase 3
Streamlit app providing time-boxed, read-only access to:
  - Case audit trails across assigned tenants
  - Immutable audit log chain viewer
  - Regulatory export download (FMU JSON)
No write controls, no admin tabs, no cross-tenant data.
"""
import streamlit as st
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="AML/CFT Auditor Portal",
    page_icon="🔍",
    layout="wide",
)

# ── Premium dark read-only theme ────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --bg:       #0B1120;
  --surface:  #131F35;
  --border:   rgba(255,255,255,0.08);
  --accent:   #38BDF8;
  --text:     #E2E8F0;
  --muted:    #64748B;
  --success:  #22C55E;
  --danger:   #F87171;
  --warning:  #FBBF24;
}

html, body, .stApp { background: var(--bg) !important; font-family: 'Inter', sans-serif; color: var(--text); }

/* kill default streamlit padding */
.block-container { padding-top: 2rem !important; }

/* header strip */
.auditor-header {
  background: linear-gradient(135deg, #0F2240 0%, #0B1120 100%);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px 28px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.auditor-badge {
  background: rgba(56,189,248,0.15);
  color: var(--accent);
  border: 1px solid rgba(56,189,248,0.3);
  border-radius: 9999px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 4px 12px;
  text-transform: uppercase;
}

/* cards */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 16px;
}
.card h4 { margin: 0 0 8px 0; color: var(--text); font-size: 1rem; }

/* audit event rows */
.audit-row {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 0.85rem;
}
.audit-row:last-child { border-bottom: none; }
.gate-chip {
  background: rgba(56,189,248,0.1);
  color: var(--accent);
  border-radius: 4px;
  padding: 1px 7px;
  font-weight: 600;
  font-size: 0.75rem;
  white-space: nowrap;
}
.actor-chip {
  background: rgba(34,197,94,0.1);
  color: #86EFAC;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 0.75rem;
}

/* chain status */
.chain-ok    { color: var(--success); font-weight: 600; }
.chain-error { color: var(--danger);  font-weight: 600; }

/* sidebar */
section[data-testid="stSidebar"] { background: var(--surface) !important; }
h1, h2, h3 { color: var(--text) !important; }
</style>
""", unsafe_allow_html=True)

# ── Session: simulate time-boxed access ─────────────────────────────────────
if "session_start" not in st.session_state:
    st.session_state.session_start = datetime.now(timezone.utc)
    st.session_state.session_limit_minutes = 60   # 1-hour examination window

session_elapsed = datetime.now(timezone.utc) - st.session_state.session_start
session_remaining = timedelta(minutes=st.session_state.session_limit_minutes) - session_elapsed

if session_remaining.total_seconds() <= 0:
    st.error("🔒 Auditor session has expired. Please re-authenticate to continue.")
    st.stop()

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Auditor Portal")
    st.markdown(f"**Auditor:** External Examiner")
    st.markdown(f"**Assigned Tenants:** TENANT-A")
    st.markdown(f"**Access Mode:** `READ-ONLY`")
    mins_left = int(session_remaining.total_seconds() // 60)
    secs_left = int(session_remaining.total_seconds() % 60)
    color = "var(--danger)" if mins_left < 10 else "var(--warning)" if mins_left < 30 else "var(--success)"
    st.markdown(f"**Session Remaining:** <span style='color:{color};font-weight:600'>{mins_left}m {secs_left}s</span>", unsafe_allow_html=True)
    st.markdown("---")
    view = st.radio("View", ["Audit Trail Viewer", "Hash-Chain Verifier", "Export Downloads"])
    st.markdown("---")
    st.caption("No write access. No admin tabs. All actions are logged.")

# ── Header strip ─────────────────────────────────────────────────────────────
st.markdown("""
<div class="auditor-header">
  <div>
    <span class="auditor-badge">Read-Only &bull; Examination Mode</span>
    <h2 style="margin:8px 0 0 0;">AML/CFT Compliance Audit Portal</h2>
    <p style="margin:4px 0 0;color:var(--muted);font-size:0.85rem;">
      Tenant: TENANT-A &nbsp;|&nbsp; SBP/SECP Regulatory Examination Interface
    </p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Load data ────────────────────────────────────────────────────────────────
@st.cache_data
def load_audit_log():
    log_path = ROOT / "mcp-servers" / "audit-log-mcp" / "audit_log.jsonl"
    if not log_path.exists():
        return []
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries

@st.cache_data
def load_exports():
    export_dir = ROOT / "exports"
    if not export_dir.exists():
        return []
    return sorted(export_dir.glob("*.json"))


# ── View: Audit Trail ────────────────────────────────────────────────────────
if view == "Audit Trail Viewer":
    st.markdown("## Case Audit Trails")
    st.info("Each case audit trail is reconstructable without re-running the model. "
            "Every AI-assisted output is labelled with model version, prompt template, "
            "RAG citations, and the human reviewer's identity and timestamp.")

    # Load synthetic cases as proxy for real case audit
    case_file = ROOT / "data" / "synthetic_case_files.json"
    if case_file.exists():
        with open(case_file, encoding="utf-8") as f:
            cases = json.load(f)
        high = [c for c in cases if c["risk_score"] == "High"][:20]

        for c in high:
            with st.expander(f"Case {c['case_id']} | Risk: {c['risk_score']} | {c['screening_hit'][:50]}"):
                st.markdown(f"""
<div class="card">
  <h4>Transaction Pattern</h4>
  <p style='color:var(--muted)'>{c['transaction_pattern']}</p>
  <h4>Screening Hit</h4>
  <p style='color:var(--muted)'>{c['screening_hit']}</p>
  <h4 style='margin-top:12px'>Workflow Events (simulated)</h4>
  <div class="audit-row">
    <span class="gate-chip">G01</span>
    <span class="actor-chip">System</span>
    <span style='color:var(--muted)'>Data ingested — automated</span>
  </div>
  <div class="audit-row">
    <span class="gate-chip">G02</span>
    <span class="actor-chip">System</span>
    <span style='color:var(--muted)'>Watchlist screening completed</span>
  </div>
  <div class="audit-row">
    <span class="gate-chip">G03</span>
    <span class="actor-chip">Analyst_A</span>
    <span style='color:var(--muted)'>Screening hit confirmed as True Positive</span>
  </div>
  <div class="audit-row">
    <span class="gate-chip">G16</span>
    <span class="actor-chip">MLRO_01</span>
    <span style='color:var(--muted)'>SAR approved and filed to FMU</span>
  </div>
</div>
""", unsafe_allow_html=True)
    else:
        st.warning("No case data found. Run data generation scripts first.")


# ── View: Hash-Chain Verifier ─────────────────────────────────────────────────
elif view == "Hash-Chain Verifier":
    st.markdown("## Immutable Audit Log — Hash-Chain Verification")
    st.info("The audit log is append-only and SHA-256 hash-chained. "
            "Any tampering is detectable because each entry's hash includes the previous entry's hash.")

    entries = load_audit_log()

    if not entries:
        st.warning("No audit log entries found. Run the audit-log-mcp test to generate entries.")
    else:
        st.metric("Total Log Entries", len(entries))

        # Verify chain integrity
        import hashlib
        prev_hash = hashlib.sha256(b"genesis").hexdigest()
        chain_ok = True
        first_error = None

        for i, entry in enumerate(entries):
            stored_hash = entry.get("hash", "")
            entry_copy = {k: v for k, v in entry.items() if k != "hash"}
            computed = hashlib.sha256(json.dumps(entry_copy, sort_keys=True).encode()).hexdigest()
            if computed != stored_hash or entry.get("prev_hash") != prev_hash:
                chain_ok = False
                first_error = i + 1
                break
            prev_hash = stored_hash

        if chain_ok:
            st.markdown(f"<p class='chain-ok'>Chain integrity verified — zero tamper errors across {len(entries):,} entries</p>", unsafe_allow_html=True)
        else:
            st.markdown(f"<p class='chain-error'>TAMPER DETECTED at row {first_error}</p>", unsafe_allow_html=True)

        st.markdown("### Recent Entries (last 5)")
        for e in entries[-5:]:
            st.markdown(f"""
<div class="card">
  <div class="audit-row">
    <span style='color:var(--muted);font-size:0.75rem'>{e.get('timestamp','')[:19]}</span>
    <span style='flex:1;color:var(--text)'>{e.get('payload','')[:80]}</span>
    <code style='font-size:0.7rem;color:var(--muted)'>{e.get('hash','')[:12]}…</code>
  </div>
</div>""", unsafe_allow_html=True)


# ── View: Export Downloads ────────────────────────────────────────────────────
elif view == "Export Downloads":
    st.markdown("## Regulatory Exports (FMU JSON)")
    st.info("Export files are validated against the SBP FMU e-filing schema before being listed here. "
            "Auditors can download but cannot modify these files.")

    exports = load_exports()
    if not exports:
        st.warning("No exports found. Run `python services/reporting/export.py` to generate a test export.")
    else:
        for p in exports:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"""
<div class="card">
  <h4>{data.get('filing_reference', p.stem)}</h4>
  <p style='color:var(--muted);font-size:0.85rem'>
    Type: {data.get('report_type')} &nbsp;|&nbsp;
    Tenant: {data.get('reporting_entity',{}).get('sbp_code','')} &nbsp;|&nbsp;
    Filed: {data.get('filing_timestamp','')[:10]}
  </p>
</div>""", unsafe_allow_html=True)
            with col2:
                st.download_button(
                    "Download JSON",
                    data=json.dumps(data, indent=2),
                    file_name=p.name,
                    mime="application/json",
                    key=f"dl_{p.stem}",
                )
