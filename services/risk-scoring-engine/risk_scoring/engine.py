"""
Deterministic risk-scoring engine. Rules-only for Phase 0 — no ML yet
(Section 5/roadmap: ML risk scoring is added in Phase 2 as an ensemble
*alongside* this, never replacing it, so there's always an auditable
rules baseline).

Same inputs always produce the same score. No model call, no randomness.
"""
from risk_scoring.models import (
    RiskScoringInput,
    RiskScoringResult,
    FactorContribution,
    RiskTier,
)
from risk_scoring.weights import WeightConfig, PLATFORM_FLOOR


def _screening_signal_value(s) -> float:
    # sanctioned-list hit is handled as a hard override below, not blended in —
    # a true sanctions hit shouldn't be averageable away by a clean KYC file.
    if s.is_pep:
        return max(s.highest_match_confidence, 0.5)
    return s.highest_match_confidence


def _customer_profile_signal_value(c) -> float:
    base = max(c.jurisdiction_risk, c.business_type_risk)
    if c.is_high_risk_legal_structure:
        base = min(1.0, base + 0.2)
    return base


def _kyc_signal_value(k) -> float:
    base = k.required_docs_missing_pct
    if k.identity_verification_failed:
        base = min(1.0, base + 0.4)
    return base


def _transaction_signal_value(t) -> float:
    base = t.velocity_anomaly_score
    if t.structuring_flag:
        base = min(1.0, base + 0.3)
    if t.high_risk_corridor_flag:
        base = min(1.0, base + 0.2)
    return base


def _tier_for_score(score: float, thresholds: dict) -> RiskTier:
    if score >= thresholds["critical"]:
        return RiskTier.CRITICAL
    if score >= thresholds["high"]:
        return RiskTier.HIGH
    if score >= thresholds["medium"]:
        return RiskTier.MEDIUM
    return RiskTier.LOW


def score(input_: RiskScoringInput, weights: WeightConfig = PLATFORM_FLOOR) -> RiskScoringResult:
    weights.validate()

    # Hard override: a confirmed sanctions-list hit is CRITICAL regardless of
    # every other factor. This is a human-only checkpoint per Section 8
    # ("confirming a sanctions true-positive" is human-only) — the engine's
    # job here is only to make sure it's never scored *down* to something
    # a human could miss in a queue sorted by score.
    if input_.screening.is_sanctioned_list_hit:
        return RiskScoringResult(
            entity_id=input_.entity_id,
            score=100.0,
            tier=RiskTier.CRITICAL,
            weights_version=weights.version,
            factor_breakdown=[],
            hard_override_reason="sanctioned_list_hit",
        )

    raw_values = {
        "screening": _screening_signal_value(input_.screening),
        "customer_profile": _customer_profile_signal_value(input_.customer_profile),
        "kyc_completeness": _kyc_signal_value(input_.kyc),
        "transaction_behavior": _transaction_signal_value(input_.transaction),
    }
    factor_weights = {
        "screening": weights.screening_weight,
        "customer_profile": weights.customer_profile_weight,
        "kyc_completeness": weights.kyc_completeness_weight,
        "transaction_behavior": weights.transaction_behavior_weight,
    }

    breakdown = []
    total = 0.0
    for name, raw in raw_values.items():
        w = factor_weights[name]
        contribution = raw * w * 100  # scale to 0-100
        breakdown.append(FactorContribution(
            factor_name=name,
            weight=w,
            raw_signal_value=raw,
            weighted_contribution=contribution,
        ))
        total += contribution

    tier = _tier_for_score(total, weights.tier_thresholds)

    return RiskScoringResult(
        entity_id=input_.entity_id,
        score=round(total, 2),
        tier=tier,
        weights_version=weights.version,
        factor_breakdown=breakdown,
    )
