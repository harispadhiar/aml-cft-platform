import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("risk-scoring")

# Deterministic risk scoring engine (rule-based weights only)
class RiskScoringEngine:
    def __init__(self):
        self.rules = {
            "nacta_match": 100,      # Exact match on NACTA lists is instantly HIGH
            "un_sanctions_match": 100,
            "structuring": 75,       # Structuring/smurfing pattern
            "high_risk_jurisdiction": 60, # Wire transfer to high-risk jurisdiction
            "velocity_spike": 50,    # Sudden spike in transaction velocity
            "adverse_media": 40
        }
        
    def score_case(self, case_data: dict | list) -> dict:
        """
        Takes case data (dict or list of rule names) and returns a risk score based on deterministic rules.
        """
        score = 0
        triggered_rules = []

        if isinstance(case_data, (list, set, tuple)):
            for r in case_data:
                if r in self.rules and r not in triggered_rules:
                    score += self.rules[r]
                    triggered_rules.append(r)
            clamped = min(score, 100)
            tier = "High" if clamped >= 80 or "nacta_match" in triggered_rules or "un_sanctions_match" in triggered_rules else "Medium" if clamped >= 40 else "Low"
            return {
                "case_id": "N/A",
                "risk_score": clamped,
                "risk_tier": tier,
                "triggered_rules": triggered_rules
            }

        case_id = case_data.get("case_id", "UNKNOWN")
        pattern = str(case_data.get("transaction_pattern", "")).lower()
        hit = str(case_data.get("screening_hit", "")).lower()

        # If explicit rules list was provided in dict
        explicit_rules = case_data.get("rules_triggered", [])
        for r in explicit_rules:
            if r in self.rules and r not in triggered_rules:
                score += self.rules[r]
                triggered_rules.append(r)
        
        # Screening rules
        if "nacta" in hit and "true positive" in hit:
            score += self.rules["nacta_match"]
            triggered_rules.append("nacta_match")
            
        if "un sanctions" in hit and "true positive" in hit:
            score += self.rules["un_sanctions_match"]
            triggered_rules.append("un_sanctions_match")
            
        # Transaction rules
        if "structuring" in pattern or "deposits" in pattern:
            score += self.rules["structuring"]
            triggered_rules.append("structuring")
            
        if "wire" in pattern and "high-risk" in pattern:
            score += self.rules["high_risk_jurisdiction"]
            triggered_rules.append("high_risk_jurisdiction")
            
        if "velocity" in pattern or "spike" in pattern:
            score += self.rules["velocity_spike"]
            triggered_rules.append("velocity_spike")
            
        # Determine tier
        if score >= 80:
            tier = "High"
        elif score >= 40:
            tier = "Medium"
        else:
            tier = "Low"
            
        result = {
            "case_id": case_data.get("case_id"),
            "risk_score": score,
            "risk_tier": tier,
            "triggered_rules": triggered_rules
        }
        
        logger.info(f"Case {case_data.get('case_id')} scored as {tier} ({score}). Rules: {triggered_rules}")
        return result

if __name__ == "__main__":
    # Test the engine
    engine = RiskScoringEngine()
    
    mock_case = {
        "case_id": "CASE-0001",
        "transaction_pattern": "Normal transaction activity.",
        "screening_hit": "True Positive NACTA match on entity name."
    }
    
    print(json.dumps(engine.score_case(mock_case), indent=2))
