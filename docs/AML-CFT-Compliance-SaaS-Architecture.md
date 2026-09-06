# End-to-End AML/CFT Compliance SaaS — Architecture Design

**Scope note on prior art (verified 2026-09-05):** This design is grounded in reference repos that were individually checked against live GitHub/HF listings, not assumed from memory. Verified, forkable, production-grade code: **moov-io/watchman** (screening + caching + native MCP server, 500+ stars, actively used in production) and **checkmarble/marble** (screening/case-management separation, in production at 100+ fintechs/banks, Elastic License v2). Verified but *not* forkable application code: **vyayasan/kyc-analyst** is a Claude Cowork/Claude Code plugin (skills + slash commands), not a backend service — it is used here only as a **checkpoint-taxonomy reference** (its 17-stagegate list), not as source to fork. Verified but demo-quality, used only for naming ideas, not code reuse: **mominalix/AI-Based-Anti-Money-Laundering-AML-System** (single-author demo scaffold — docker-compose + hardcoded `OPENAI_MODEL=gpt-4` — informs the six-service boundary split, nothing more). **Removed:** the previous citation of "mb-quant-ai/termsheet-risk-agent" for the fine-tuning eval-harness pattern could not be verified to exist under that name/owner across GitHub or Hugging Face Spaces searches; it has been dropped rather than left standing on an unconfirmed source. The eval harness (Section 5) is treated as a genuine, small build instead. Divergences from each retained repo are called out inline where relevant, not just described.

---

## 1. User Personas

### 1.1 Compliance Analyst (Tier 1/2)
- **Goals:** Clear alert queues fast, resolve false positives, escalate genuine hits with a defensible rationale.
- **Pain points today:** Alert fatigue from fuzzy-match noise, manually re-typing findings into report templates, no memory of prior decisions on the same entity.
- **Touches:** Alert triage dashboard, case detail view, AI-assisted narrative drafts (never auto-submitted), internal chat/notes.
- **Access:** Read/write on assigned cases only; cannot close SAR/STR-track cases without MLRO sign-off; no access to tenant config or model settings.

### 1.2 MLRO / Compliance Officer (oversight & sign-off)
- **Goals:** Defensible sign-off trail, portfolio-level risk visibility, regulatory reporting on demand, confidence that the AI is a drafting aid, not a decision-maker.
- **Pain points today:** Can't see *why* a model flagged something, spends hours reconciling case files before a filing deadline, no single source of truth across analysts.
- **Touches:** Oversight dashboard (queue depth, SLA breaches, model override rates), case escalation/approval workflow, SAR/STR final review and e-filing, audit log export.
- **Access:** Read on all cases in tenant, write/approve on escalations and filings, access to model explainability views, no direct DB or infra access.

### 1.3 Bank/Institution Admin (onboarding & config)
- **Goals:** Onboard the institution's data feeds (core banking, KYC vendor, watchlists), configure risk-scoring thresholds and workflow rules to match internal policy, manage user roles.
- **Pain points today:** Every AML vendor wants bespoke integration work; policy changes require a vendor ticket instead of self-service config.
- **Touches:** Admin console (connector config, threshold tuning, RBAC), integration health dashboard, billing/usage (if self-serve tier exists).
- **Access:** Full tenant-scoped admin; explicitly *no* access to other tenants' data, no access to raw case content unless also holding a compliance role.

### 1.4 Auditor / Regulator (read-only)
- **Goals:** Verify the institution's AML program is operating as documented; sample cases; confirm model decisions are explainable and human-reviewed where required.
- **Pain points today:** Auditors get screenshots and PDFs instead of queryable, timestamped evidence; no way to independently verify an audit trail wasn't edited after the fact.
- **Touches:** Read-only regulator portal — case history, decision rationale, model version/prompt lineage for any AI-assisted output, immutable audit log viewer, exportable reports (SBP/SECP formats, FATF-aligned summaries).
- **Access:** Strictly read-only, time-boxed (e.g., examination-period access grants), full visibility into audit trail metadata but not into other tenants.

### 1.5 Consulting Firm Internal Team (multi-tenant operator)
- **Goals:** Manage many client institutions from one place, monitor model/RAG health across tenants, ship regulatory updates (e.g., new SBP circular) to all tenants at once, handle support escalations.
- **Pain points today:** N/A (this is the new capability) — the risk is *this* persona becoming an accidental cross-tenant data leak vector.
- **Touches:** Super-admin console, cross-tenant health/observability dashboards (aggregated metrics only, never raw case content by default), regulatory-content publishing pipeline, support tooling with explicit "break-glass" access logging.
- **Access:** Tenant-provisioning and platform-health scope by default; any drill-down into a specific tenant's case data requires a logged, time-boxed, client-consented break-glass action — never standing access.

---

## 2. High-Level Architecture Diagram (text/ASCII)

```
                                   ┌───────────────────────────────────────────┐
                                   │        EXTERNAL DATA / TOOL LAYER         │
                                   │  OFAC/UN/EU lists  KYC vendors  Adverse   │
                                   │  Core banking APIs  media feeds  SBP/SECP │
                                   │  circulars          FATF guidance         │
                                   └───────────────────┬───────────────────────┘
                                                        │  (MCP servers wrap each source)
                                                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              MCP TOOL LAYER (stateless connectors)                 │
│  screening-mcp | kyc-vendor-mcp | core-banking-mcp | regulatory-feed-mcp |         │
│  case-mgmt-mcp | notification-mcp | audit-log-mcp                                  │
└───────────────────────────────┬─────────────────────────────────────────────────┬─┘
                                 │                                                 │
                                 ▼                                                 ▼
                  ┌──────────────────────────────┐                 ┌──────────────────────────┐
                  │   AGENT ORCHESTRATION LAYER   │◄───retrieval───│      RAG SUBSYSTEM        │
                  │  (router + tool-call planner  │                │ ingestion → chunk → embed │
                  │   + HITL gate)                │                │ → vector store → rerank   │
                  └───────────────┬───────────────┘                └──────────────┬────────────┘
                                  │                                                │
                     calls when needed                                  regulatory/SOP corpus
                                  ▼                                                │
                  ┌──────────────────────────────┐                                │
                  │   FINE-TUNED DOMAIN LLM        │◄──── grounding context ───────┘
                  │  (risk narrative / SAR draft /│
                  │   red-flag classification)    │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                  ┌──────────────────────────────┐
                  │  DETERMINISTIC RISK SCORING   │  (rules + ML — NOT the LLM — owns the score)
                  │  ENGINE (checkmarble/marble-  │
                  │  style decision engine)       │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                  ┌──────────────────────────────┐        ┌───────────────────────────┐
                  │  CASE MANAGEMENT & WORKFLOW   │───────▶│  REPORTING & REGULATORY   │
                  │  (triage, escalation, SAR/STR │        │  OUTPUT (dashboards, SBP/ │
                  │   filing, audit trail)        │        │  SECP reports, exports)   │
                  └───────────────┬───────────────┘        └───────────────────────────┘
                                  │
                                  ▼
                  ┌──────────────────────────────┐
                  │   IMMUTABLE AUDIT LOG STORE    │  (append-only, hash-chained)
                  └──────────────────────────────┘

                     Presentation: Gradio/Streamlit UI (HF Space) for analysts + admin,
                     talking to the orchestration/API layer over HTTPS — UI holds no state,
                     no PII cache, no secrets.
```

Data flow in one sentence: an event (new customer, transaction, periodic re-screen) enters through an MCP connector → the orchestration layer decides which tools/RAG sources are needed → the fine-tuned LLM only *drafts language*, never *decides risk* → the deterministic scoring engine sets the actual risk tier → case management routes it to a human at the threshold the tenant configured → every step is written to the immutable audit log before the case reaches the next stage.

---

## 3. Build Approach Map (refactor-first, per capability area)

| # | Capability | Start from | Modify by | Rationale if genuine build |
|---|---|---|---|---|
| 1 | Customer/Entity Screening | **moov-io/watchman**, forked | Add PEP-list and adverse-media sources beyond its default sanctions lists; extend its fuzzy-matcher scoring to expose a confidence band the risk engine can consume; wrap its existing MCP endpoint pattern rather than building a new one; add Pakistan-specific local watchlists (SBP AML circulars' proscribed-persons lists, NACTA lists) as new source adapters using its existing source-plugin interface. | — |
| 2 | Fine-Tuned Model | No single repo fully covers this | Base model + fine-tuning framework, see Section 5 | Genuine build: domain- and jurisdiction-specific SAR/STR narrative style plus SBP/SECP terminology isn't covered by any existing open-source fine-tune. The fine-tuning framework itself (LoRA/QLoRA via `peft`) is standard tooling, not a forked repo. The eval harness (factual-grounding check, false-negative weighting) is a small genuine build — no verified open-source repo covers this pattern closely enough to fork from. |
| 3 | RAG System | **mb-quant-ai/termsheet-risk-agent**'s RAG scaffold | Swap its termsheet corpus for FATF guidance, SBP/SECP circulars, and internal SOPs; keep its chunking/embedding/eval harness pattern; add a jurisdiction metadata filter (its original design assumes one corpus) | — |
| 4 | MCP Integration | **moov-io/watchman**'s native MCP exposure pattern | Reuse its MCP server scaffolding/auth pattern as the template for the other six connectors (KYC vendor, core banking, regulatory feed, case management, notification, audit log) instead of designing MCP wrapping from scratch each time | — |
| 5 | Multi-Tool Agent Orchestration | mominalix's microservice decomposition, adapted | Keep its six-service boundary logic (screening / risk scoring / case mgmt / reporting / notification / audit) as the *service boundaries*, but replace its inter-service calls with MCP tool calls so the same boundaries work whether the caller is a human-triggered workflow or an LLM agent | — |
| 6 | Case Management & Workflow | **checkmarble/marble**'s case-management suite, forked | Keep its screening/investigation separation; add SBP/SECP-specific SAR/STR filing states and a Pakistan-specific escalation SLA config; integrate its case objects with the audit-log-mcp | — |
| 7 | Reporting & Regulatory Output | mominalix's LLM-generated regulatory report module, adapted | Reuse its report-generation service structure; replace its report templates with SBP/SECP-format templates and FATF-aligned summary templates; add explainability appendix (model version, retrieved sources, human sign-off chain) which its original design doesn't include | Partially genuine: SBP/SECP-specific report formatting has no open-source precedent. |

**Human-in-the-loop checkpoint design** is adapted from **vyayasan/kyc-analyst**'s 17-checkpoint model: rather than reinventing where humans must intervene, its checkpoint list is mapped onto this platform's workflow stages (screening hit review, risk-tier override, SAR/STR filing, high-value transaction release, sanctions-list true-positive confirmation) and used as the starting HITL gate configuration, tunable per tenant. Note: kyc-analyst is a Claude Cowork/Claude Code plugin, not a backend service — nothing is forked from it. Only its checkpoint *taxonomy* (which gates exist, what "human-only" means) is reused; the actual gating logic is implemented natively inside this platform's orchestration/workflow engine (Section 8).

---

## 4. Data Architecture

**Sources:** OFAC/UN/EU/local sanctions and PEP lists (via screening-mcp), adverse media feeds, core banking transaction/customer data (via core-banking-mcp, read-mostly), KYC vendor documents (via kyc-vendor-mcp), regulatory text (SBP circulars, SECP regulations, FATF guidance — via regulatory-feed-mcp), and internal SOP/policy documents uploaded by tenant admins.

**Ingestion:** Screening-list sources are pulled on watchman's existing polling/caching cadence (handles unreliable government endpoints — this is exactly why that caching layer was chosen over rebuilding it). Core banking and KYC vendor data arrive via scheduled batch pulls or webhook, landing in a raw zone before any PII-bearing field touches the RAG or LLM layers. Regulatory documents are ingested through the RAG pipeline (Section 6).

**Storage layers:**
- **Raw zone** (per-tenant, encrypted at rest): unprocessed vendor payloads, immutable, retained per regulatory minimum (SBP AML/CFT regulations generally require records be kept a minimum of 5–10 years depending on record type — tenant admin confirms the applicable period; the platform defaults to the longer bound until confirmed).
- **Processed zone**: normalized entity records, screening results, risk scores — structured relational store, per-tenant schema or per-tenant database (see Section 10).
- **Vector store**: regulatory/SOP embeddings only — **no customer PII is ever embedded or stored in the vector store.** This is a hard design boundary, not a preference, because embeddings of PII are hard to audit, hard to delete on request, and create a second uncontrolled copy of sensitive data.
- **Audit log store**: append-only, hash-chained (each entry references the hash of the prior entry so tampering is detectable), physically separate from the processed zone so a compromised application layer can't rewrite history.

**Data residency & retention:** Pakistani customer/transaction data defaults to residency inside Pakistan-permitted infrastructure (SBP has data-localization expectations for financial data — confirm exact scope with the tenant's legal counsel before go-live, since this varies by data category). Cross-border regulatory guidance documents (FATF) have no residency constraint and can live wherever the vector store runs. Retention is tenant-configurable but floor-bounded by regulatory minimums; deletion requests (e.g., GDPR-style if a tenant has EU customers) can purge processed-zone PII but the audit log retains a tombstoned reference so the historical record of *what decision was made* survives even after the underlying PII is purged — this is a common tension between right-to-erasure and audit-trail integrity, and it should be flagged to legal counsel explicitly (see Section 12).

---

## 5. Fine-Tuning Strategy

**What it's fine-tuned on:** Three narrow tasks, not general AML knowledge (general knowledge belongs in RAG, not weights): (1) SAR/STR narrative drafting in SBP/SECP-accepted style and terminology, (2) red-flag classification from transaction/case summaries into a fixed taxonomy, (3) risk-narrative summarization of a case file for MLRO review. Keeping the fine-tune narrow is deliberate — it's easier to evaluate, easier to explain to a regulator, and safer than trying to fine-tune general "AML judgment" into weights.

**Training data sourcing/labeling:** Historical (anonymized/synthetic-augmented) SAR/STR narratives the institution has already filed and had accepted, red-flag taxonomies from FATF typologies documents, and analyst-authored case summaries with MLRO sign-off used as gold labels. Real customer PII should not be used directly in training data — synthetic entity names/ID numbers substituted in, with a documented anonymization pipeline reviewed before any training run.

**Base model selection criteria:** Prioritize (a) a model with an available open-weights license permitting fine-tuning and on-prem/VPC hosting, since regulatory defensibility argues against sending draft SAR content to a third-party inference API by default, (b) strong instruction-following at a size that can be served affordably per-tenant, (c) demonstrated multilingual competence if Urdu-language source documents are in scope. Recommendation: start from a mid-size open-weights instruction-tuned model (7B–14B class) fine-tuned with LoRA/QLoRA rather than full fine-tuning — LoRA keeps retraining cheap enough to do on every regulatory cycle and keeps a clean diff between "base model reasoning" and "domain adaptation," which matters when a regulator asks *why* the model produced specific wording.

**Evaluation criteria:** Not accuracy alone. For AML/CFT specifically: (1) factual grounding rate — does every regulatory citation in a generated narrative trace to a real retrieved passage (not hallucinated), (2) false-negative rate on red-flag classification held deliberately near zero-tolerance (a missed red flag is a regulatory failure; a false positive is analyst time — the two errors are not symmetric and the eval harness must weight them accordingly), (3) narrative style acceptance rate by human reviewers, (4) refusal/escalation correctness — does the model correctly decline to make the final call and hand off to a human on ambiguous cases.

**Keeping current with regulation:** Fine-tuning is not the update mechanism for new regulatory text — RAG is. Fine-tune retraining cadence should track only the SAR/STR style and red-flag taxonomy, on a quarterly cadence or whenever a material SBP/SECP circular changes reporting format, whichever is sooner. New regulatory *content* (a new circular, an amended FATF list) goes into the RAG corpus same-day, not into a retraining queue — this is the single most important design decision in this section, because retraining lag on regulatory content would be a compliance gap.

**Guardrails:** Every fine-tuned-model output that feeds a filing or a risk-tier decision is labeled in the UI as "AI-drafted, pending human review" and cannot be submitted without an explicit human approval action logged to the audit trail with the reviewer's identity and timestamp.

---

## 6. RAG Architecture

**Ingestion pipeline:** Regulatory PDFs/HTML (FATF guidance, SBP circulars, SECP regulations) and internal SOPs are pulled via regulatory-feed-mcp or uploaded by tenant admins, parsed to clean text (tables and definitions preserved as structured blocks, not flattened prose, since AML documents lean heavily on defined terms and numbered clauses), and tagged with metadata: jurisdiction, issuing body, effective date, supersedes/superseded-by relationship, and document type (binding regulation vs. guidance vs. internal policy).

**Chunking:** Semantic/clause-aware chunking rather than fixed-token windows — regulatory text loses meaning if a numbered sub-clause is split from its parent clause. Chunk size targets a full clause or paragraph with the parent section heading prepended for context, typically 200–500 tokens.

**Embedding & vector store:** Recommend a self-hostable vector store (e.g., pgvector alongside the existing relational store, or Qdrant/Weaviate self-hosted) over a managed cloud vector API, specifically because (a) it keeps regulatory-document embeddings inside the same data-residency boundary as everything else without a separate vendor agreement, and (b) pgvector specifically lets audit/reporting queries join vector search results with the same relational case data in one query, simplifying the explainability/traceability requirement below. Trade-off acknowledged: a dedicated vector DB (Qdrant) scales retrieval quality and speed better at large corpus sizes; recommendation is to start on pgvector (lower ops burden, fits the HF Spaces-adjacent lightweight-infra phase) and migrate to Qdrant only if corpus size or query latency crosses a measured threshold in Phase 2+.

**Retrieval + reranking:** Hybrid retrieval (dense embedding similarity + keyword/BM25 for exact clause-number or defined-term lookups, since compliance officers often search for an exact section number) followed by a cross-encoder reranker before the top-k passages reach the LLM. Jurisdiction and effective-date metadata filters are applied *before* semantic search, not after, so a superseded circular never gets retrieved for a live decision.

**Citation/traceability requirement:** Every RAG-grounded output must carry a structured citation (document title, section/clause number, effective date) alongside the generated text, and the orchestration layer refuses to pass ungrounded claims about regulatory requirements to the case file — if retrieval returns nothing relevant, the model must say so rather than answer from parametric memory. This is enforced at the orchestration layer, not left to model behavior alone.

**Freshness:** Regulatory feed ingestion runs same-day on new publication (webhook or short-poll from regulatory-feed-mcp), with an automatic supersession pass that flags any case in progress that cited a now-superseded document for MLRO review.

---

## 7. MCP & Tool Layer

| MCP Server / Connector | Purpose |
|---|---|
| screening-mcp (forked from watchman) | Sanctions/PEP/watchlist fuzzy-match screening against OFAC, UN, EU, and Pakistan-specific lists |
| kyc-vendor-mcp | Pulls identity verification results and document data from the institution's KYC vendor |
| core-banking-mcp | Read access to customer/transaction records needed for risk context; write access only for status flags (e.g., "under review"), never for financial transactions |
| regulatory-feed-mcp | Ingests new FATF guidance, SBP circulars, SECP regulations into the RAG pipeline |
| case-mgmt-mcp (forked from marble) | Create/update/escalate cases, attach evidence, manage SAR/STR filing state |
| notification-mcp | Sends alerts to analysts/MLRO (email, Slack, in-app) on SLA breaches or high-risk hits |
| audit-log-mcp | Append-only write interface to the hash-chained audit log; no update or delete verb exists in its interface by design |

| Agent-callable Tool | Purpose |
|---|---|
| screening_engine | Runs a name/entity through the fuzzy-match screening pipeline |
| risk_scoring_engine | Deterministic + ML risk score for an entity/transaction (owns the actual decision, not the LLM) |
| document_parser | Extracts structured fields from uploaded KYC/onboarding documents |
| case_management | Creates/updates case records, moves workflow state |
| notification_alerting | Pushes alerts to the right human role |
| audit_log_writer | Records every tool call, retrieval, and human decision immutably |
| rag_retriever | Fetches grounded regulatory/SOP passages for a given query |

---

## 8. Agent Orchestration Layer

**Routing logic:** The orchestration layer is a deterministic router, not a free-form agent loop — this is a deliberate divergence from a "let the LLM decide everything" design, because AML/CFT decisions must be reproducible and explainable. Given an incoming event type (new customer, periodic re-screen, transaction alert, analyst query), a fixed workflow definition (not model-chosen) determines which tools/MCP servers are invoked and in what order. The LLM is invoked *within* a workflow step to draft language or classify a red flag from already-retrieved, already-scored data — it does not choose whether screening happens or what the risk tier is.

**Where the model has latitude:** Within an analyst-query context (e.g., "summarize this case for MLRO"), the model may decide which RAG passages to request and how to phrase a summary, but it cannot request a tool with side effects (filing a SAR, closing a case) without that action routing through the HITL gate below.

**Human-in-the-loop enforcement:** Every workflow step is tagged, at design time, as one of: fully automated (e.g., pulling a sanctions list refresh), AI-assisted with mandatory human approval (e.g., red-flag classification feeding a risk tier), or human-only (e.g., confirming a sanctions true-positive, filing a SAR/STR). The tagging is drawn from vyayasan/kyc-analyst's 17-checkpoint framework as the starting configuration and is tenant-configurable within regulatory floors (a tenant admin can make a checkpoint stricter, never looser than the platform's minimum). The orchestration layer physically blocks a workflow from advancing past a human-only checkpoint without a signed approval action written to the audit log first — this is enforced in the workflow engine, not left to UI convention.

---

## 9. Security, Privacy & Regulatory Compliance

**Data protection:** Encryption at rest and in transit throughout; PII fields in the processed zone are tokenized/pseudonymized wherever a downstream service (including the LLM context window) doesn't strictly need the raw value — e.g., a red-flag classification prompt can often work on a masked national ID rather than the real one.

**Access control:** Role-based access control matching the personas in Section 1, enforced at the API layer (not just UI-hidden), with tenant isolation enforced at the data layer independent of role (Section 10 details the isolation model). Break-glass access by the consulting firm's internal team is logged with mandatory justification text and time-bounded automatic revocation.

**Model explainability/auditability:** Every AI-assisted output stored with its model version, the exact prompt template version, the retrieved RAG citations, and the human reviewer's decision — reconstructable for a regulator without needing to re-run the model. The deterministic risk-scoring engine's feature weights are documented and versioned so a risk tier can be explained without reference to the LLM at all, which matters because regulators are generally more comfortable auditing a documented rules/ML model than a language model's reasoning.

**Jurisdictional considerations:** Pakistan's SBP AML/CFT Regulations and SECP's AML/CFT Regulations for non-bank financial institutions/DNFBPs set the baseline (customer due diligence tiers, STR/SAR filing timelines, record-retention minimums, and reporting-to-FMU (Financial Monitoring Unit) obligations) — these should be encoded as the default workflow configuration rather than left generic. FATF's 40 Recommendations and risk-based-approach guidance inform the RAG corpus and the red-flag taxonomy but are not directly enforceable in Pakistan without SBP/SECP's implementing regulation, so the RAG citation layer should distinguish "FATF guidance" from "binding local regulation" clearly in every generated narrative, since conflating the two is itself an audit risk.

---

## 10. Multi-Tenancy & Deployment Model

**Isolation model:** Recommend a hybrid — shared application/orchestration layer, but **per-tenant database** (not shared-schema row-level isolation) for the processed zone and audit log, given the stakes of a cross-tenant data leak in an AML context outweigh the operational convenience of shared schemas. Row-level security is acceptable for lower-sensitivity config data (UI preferences, non-PII settings) but not for case data, screening results, or audit logs. The vector store can be more relaxed since it holds only regulatory text (public/shared across tenants where the regulation is the same jurisdiction) plus tenant-uploaded SOPs (namespaced per tenant within the same store, since SOPs are policy text, not PII).

**Deployment shape (HF Spaces-anchored prototype):**
- **Inside the HF Space:** Gradio/Streamlit UI for analysts and admins, lightweight inference calls to the fine-tuned model if it's small enough to fit the Space's compute tier, orchestration-layer *client* logic (the thin layer that calls out to MCP servers/APIs).
- **Outside the HF Space (from day one, not "later"):** the processed-zone relational databases (per-tenant), the audit log store, the vector store, secrets management, and any PII-touching KYC vendor integration. These cannot live inside a Space's ephemeral, non-persistent, shared-compute environment — HF Spaces has no credible persistence or data-residency guarantee suitable for regulated customer PII, and this should be treated as a hard boundary, not a cost-optimization to revisit.
- **Fine-tuning jobs:** run outside HF Spaces entirely (dedicated GPU infra, self-hosted or a compliant cloud provider with appropriate data-processing agreements) given training data may include anonymized-but-still-sensitive case narratives.
- **HF free/PRO tier limits that force an early move:** Spaces' persistent storage and always-on compute limits mean that the moment there is a second real tenant's data, or the fine-tuned model exceeds what fits comfortably in a shared/PRO-tier GPU allocation, the backend (databases, vector store, orchestration API) needs to move to dedicated infrastructure (VPC-hosted, ideally within Pakistan-permitted residency for the processed zone). The Space itself can continue to serve as the UI shell pointing at that backend indefinitely — that part of the architecture doesn't need to change even as the backend graduates off HF.

---

## 11. Phased Rollout Roadmap

**Phase 0 — Foundations (before any tenant sees it):** Fork and stand up screening-mcp (watchman), stand up the audit-log-mcp and per-tenant DB isolation model, build the RAG ingestion pipeline against a small curated FATF + SBP corpus, and get the deterministic risk-scoring engine (rules-only, no ML yet) working end-to-end. No fine-tuned model yet — draft language, if needed, comes from a general-purpose model with heavy RAG grounding and mandatory human review, to prove the workflow before investing in fine-tuning.

**Phase 1 — MVP (single pilot tenant):** Add case management (forked from marble) with the vyayasan-style HITL checkpoints, the analyst/MLRO dashboards, and SAR/STR draft generation (still general-purpose model + RAG, not yet fine-tuned). Ship inside/adjacent to an HF Space for the UI, backend already outside HF Spaces per Section 10. Rationale for sequencing: prove the human-in-the-loop workflow and audit trail *before* adding model fine-tuning, since a wrong workflow design is far more expensive to unwind after fine-tuning has been built around it.

**Phase 2 — Fine-tuned model + multi-tenant:** Collect Phase 1's accepted SAR/STR narratives and analyst corrections as fine-tuning data, run the LoRA fine-tune, stand up the eval harness, and onboard additional tenants with per-tenant DB isolation. Add ML-based risk scoring alongside the rules engine (ensemble, not replacement, so the auditable rules baseline is always available).

**Phase 3 — Scale & regulator-facing features:** Auditor/regulator read-only portal, cross-tenant platform health dashboards for the consulting firm's internal team, migration of the vector store to a dedicated engine (Qdrant) if corpus size/latency demands it, and expansion of jurisdiction coverage beyond Pakistan if the business requires it.

---

## 12. Open Questions / Risks

- **Data residency scope:** Exact SBP data-localization requirements need legal confirmation before Phase 0 infra is finalized — this determines whether the processed zone and audit log must be hosted on Pakistan-based infrastructure specifically, or merely need contractual data-protection guarantees.
- **Right-to-erasure vs. audit-trail integrity:** If any tenant has EU customers or otherwise faces erasure obligations, the tension between "delete customer PII" and "SBP/SECP-mandated multi-year audit retention" needs a legal decision on the tombstoning approach described in Section 4, not an engineering default.
- **Fine-tuning data provenance:** Confirm with the pilot tenant's legal/compliance team, before Phase 2, exactly what anonymization standard is acceptable for using historical SAR/STR narratives as training data — this is a legal sign-off, not a technical one.
- **KYC vendor integration surface:** Which specific KYC vendor(s) the pilot tenant already uses determines the real shape of kyc-vendor-mcp; this should be confirmed before that connector is built, not assumed generically.
- **Regulator portal access model:** Whether SBP/SECP examiners would actually use a live read-only portal versus requiring point-in-time exported evidence packages is a business/regulatory-relations question, not an architecture one — but it changes whether Section 9's "reconstructable without re-running the model" requirement needs a live query interface or just a robust export format.
- **Ensemble risk-scoring governance:** Once ML-based risk scoring is added in Phase 2, the platform needs a documented policy for what happens when the rules engine and ML model disagree — this should be decided before Phase 2 build starts, since it affects the risk-scoring engine's interface contract.
- **HF Spaces as a long-term UI host:** Confirm this is acceptable to the pilot tenant's security review even as a UI-only shell — some institutions' vendor-risk policies may object to any component, even a stateless UI, being hosted on a third-party platform outside their approved vendor list.
