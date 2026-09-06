"""
Input/output data shapes for the deterministic risk-scoring engine.

# vibe: stdlib dataclasses only, no pydantic — this module has no validation
# needs beyond what engine.py already does, adding a framework here would be
# scaffolding nobody asked for.
"""
from dataclasses import dataclass, field
from enum import Enum


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ScreeningSignal:
    """What came back from screening-mcp (watchman) for this entity."""
    highest_match_confidence: float = 0.0  # 0.0-1.0, from watchman's match score
    is_pep: bool = False
    is_sanctioned_list_hit: bool = False


@dataclass
class CustomerProfileSignal:
    """Static/onboarding-time risk factors."""
    jurisdiction_risk: float = 0.0        # 0.0-1.0, tenant-configured country risk table
    business_type_risk: float = 0.0       # 0.0-1.0, e.g. cash-intensive business = higher
    is_high_risk_legal_structure: bool = False  # shell-like structures, complex ownership


@dataclass
class KYCCompletenessSignal:
    """Documentation/CDD quality — missing docs raise risk, doesn't lower it."""
    required_docs_missing_pct: float = 0.0  # 0.0-1.0
    identity_verification_failed: bool = False


@dataclass
class TransactionBehaviorSignal:
    """Only populated for re-screen/transaction-alert events, not onboarding."""
    velocity_anomaly_score: float = 0.0     # 0.0-1.0, from upstream detection, not computed here
    structuring_flag: bool = False
    high_risk_corridor_flag: bool = False   # e.g. corridor known for trade-based laundering


@dataclass
class RiskScoringInput:
    entity_id: str
    screening: ScreeningSignal = field(default_factory=ScreeningSignal)
    customer_profile: CustomerProfileSignal = field(default_factory=CustomerProfileSignal)
    kyc: KYCCompletenessSignal = field(default_factory=KYCCompletenessSignal)
    transaction: TransactionBehaviorSignal = field(default_factory=TransactionBehaviorSignal)


@dataclass
class FactorContribution:
    factor_name: str
    weight: float
    raw_signal_value: float
    weighted_contribution: float


@dataclass
class RiskScoringResult:
    entity_id: str
    score: float                 # 0-100
    tier: RiskTier
    weights_version: str         # ties every score to an auditable, versioned config
    factor_breakdown: list[FactorContribution]
    hard_override_reason: str | None = None  # e.g. "sanctioned_list_hit" forces CRITICAL
