"""
Versioned weight configs. Every RiskScoringResult carries a weights_version
string so a regulator can be shown exactly which config produced a score,
per Section 9 of the architecture doc ("feature weights are documented and
versioned so a risk tier can be explained without reference to the LLM at all").

# vibe: weights live in a plain dict, not a DB row or YAML file — Phase 0 has
# one config. Move this to a per-tenant DB table in Phase 2 when there's an
# actual second tenant to diverge from the platform default.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class WeightConfig:
    version: str
    screening_weight: float
    customer_profile_weight: float
    kyc_completeness_weight: float
    transaction_behavior_weight: float
    tier_thresholds: dict  # {"medium": 25, "high": 50, "critical": 75}

    def validate(self) -> None:
        total = (
            self.screening_weight
            + self.customer_profile_weight
            + self.kyc_completeness_weight
            + self.transaction_behavior_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {total}")


# Platform floor: the strictest a tenant is allowed to loosen away from.
# A tenant config's thresholds must be <= these (stricter/lower is fine,
# looser/higher is not) — enforces Section 8/9's "tenant can make a
# checkpoint stricter, never looser than the platform's minimum."
PLATFORM_FLOOR = WeightConfig(
    version="platform-floor-v1",
    screening_weight=0.35,
    customer_profile_weight=0.25,
    kyc_completeness_weight=0.15,
    transaction_behavior_weight=0.25,
    tier_thresholds={"medium": 25, "high": 50, "critical": 75},
)


def validate_tenant_config_against_floor(tenant_cfg: WeightConfig, floor: WeightConfig = PLATFORM_FLOOR) -> None:
    """Raises if a tenant config would let cases reach a HIGHER score before
    escalating than the platform floor allows (i.e. would be laxer)."""
    tenant_cfg.validate()
    for tier in ("medium", "high", "critical"):
        if tenant_cfg.tier_thresholds[tier] > floor.tier_thresholds[tier]:
            raise ValueError(
                f"tenant threshold for '{tier}' ({tenant_cfg.tier_thresholds[tier]}) "
                f"is looser than platform floor ({floor.tier_thresholds[tier]})"
            )
