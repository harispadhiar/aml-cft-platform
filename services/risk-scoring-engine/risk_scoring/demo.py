"""
Run this directly to sanity-check the engine end-to-end:
    python3 -m risk_scoring.demo
"""
from risk_scoring.models import (
    RiskScoringInput,
    ScreeningSignal,
    CustomerProfileSignal,
    KYCCompletenessSignal,
    TransactionBehaviorSignal,
)
from risk_scoring.engine import score
from risk_scoring.weights import PLATFORM_FLOOR, WeightConfig, validate_tenant_config_against_floor


def print_result(label, result):
    print(f"\n--- {label} ---")
    print(f"entity_id: {result.entity_id}")
    print(f"score: {result.score}  tier: {result.tier.value}  weights_version: {result.weights_version}")
    if result.hard_override_reason:
        print(f"hard_override_reason: {result.hard_override_reason}")
    for f in result.factor_breakdown:
        print(f"  {f.factor_name:22s} raw={f.raw_signal_value:.2f}  weight={f.weight:.2f}  contrib={f.weighted_contribution:.2f}")


# Case 1: clean low-risk onboarding
clean = RiskScoringInput(
    entity_id="CUST-0001",
    screening=ScreeningSignal(highest_match_confidence=0.05),
    customer_profile=CustomerProfileSignal(jurisdiction_risk=0.1, business_type_risk=0.1),
    kyc=KYCCompletenessSignal(required_docs_missing_pct=0.0),
    transaction=TransactionBehaviorSignal(),
)
print_result("Clean onboarding", score(clean))

# Case 2: PEP with weak KYC — should land medium/high, not auto-critical
pep_weak_kyc = RiskScoringInput(
    entity_id="CUST-0002",
    screening=ScreeningSignal(highest_match_confidence=0.3, is_pep=True),
    customer_profile=CustomerProfileSignal(jurisdiction_risk=0.6, business_type_risk=0.2),
    kyc=KYCCompletenessSignal(required_docs_missing_pct=0.4),
    transaction=TransactionBehaviorSignal(),
)
print_result("PEP + weak KYC", score(pep_weak_kyc))

# Case 3: confirmed sanctions hit — must hard-override to CRITICAL regardless
# of everything else looking clean, and must NOT be averaged down.
sanctions_hit = RiskScoringInput(
    entity_id="CUST-0003",
    screening=ScreeningSignal(highest_match_confidence=0.98, is_sanctioned_list_hit=True),
    customer_profile=CustomerProfileSignal(jurisdiction_risk=0.05),
    kyc=KYCCompletenessSignal(required_docs_missing_pct=0.0),
    transaction=TransactionBehaviorSignal(),
)
result3 = score(sanctions_hit)
print_result("Confirmed sanctions hit", result3)
assert result3.score == 100.0 and result3.tier.value == "critical", "hard override failed"

# Case 4: transaction re-screen with structuring flag
structuring = RiskScoringInput(
    entity_id="CUST-0004",
    screening=ScreeningSignal(highest_match_confidence=0.0),
    customer_profile=CustomerProfileSignal(jurisdiction_risk=0.2),
    kyc=KYCCompletenessSignal(),
    transaction=TransactionBehaviorSignal(velocity_anomaly_score=0.4, structuring_flag=True),
)
print_result("Structuring flag on re-screen", score(structuring))

# Case 5: same clean input, run twice — must be deterministic (bit-for-bit)
r1 = score(clean)
r2 = score(clean)
assert r1.score == r2.score and r1.tier == r2.tier, "engine is not deterministic!"
print("\nDeterminism check passed: identical inputs produced identical outputs.")

# Case 6: tenant config validation — a tenant trying to loosen the critical
# threshold above the platform floor must be rejected.
try:
    lax_tenant = WeightConfig(
        version="tenant-acme-v1",
        screening_weight=0.35,
        customer_profile_weight=0.25,
        kyc_completeness_weight=0.15,
        transaction_behavior_weight=0.25,
        tier_thresholds={"medium": 25, "high": 50, "critical": 90},  # looser than floor's 75
    )
    validate_tenant_config_against_floor(lax_tenant)
    raise AssertionError("expected ValueError for looser-than-floor tenant config")
except ValueError as e:
    print(f"\nTenant floor enforcement works as expected: {e}")

print("\nAll checks passed.")
