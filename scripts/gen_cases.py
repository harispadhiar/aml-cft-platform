import json
import random
import os

def main():
    print("Loading synthetic customers and transactions...")
    try:
        with open('data/synthetic_customers.json', 'r') as f:
            customers = json.load(f)
    except FileNotFoundError:
        print("Error: data/synthetic_customers.json not found. Run gen_entities.py first.")
        return

    high_risk_customers = [c for c in customers if c.get('risk_tier') == 'High']
    low_risk_customers = [c for c in customers if c.get('risk_tier') != 'High']

    num_cases = 500
    cases = []

    print(f"Generating {num_cases} synthetic case files...")
    for i in range(1, num_cases + 1):
        case_id = f"CASE-{i:05d}"
        
        # 80% of cases are from high risk, 20% are false positives from low risk
        if random.random() < 0.8 and high_risk_customers:
            customer = random.choice(high_risk_customers)
            risk_score = "High"
            
            # Determine pattern
            pattern_type = random.choice(["structuring", "high_risk_wire", "velocity_spike", "nacta_match"])
            
            if pattern_type == "structuring":
                transaction_pattern = f"{random.randint(5, 10)} cash deposits of ~PKR 950,000 within 48 hours."
                screening_hit = "None"
            elif pattern_type == "high_risk_wire":
                transaction_pattern = f"Wire transfer of ~PKR {random.randint(1, 5)} million to high-risk jurisdiction."
                screening_hit = "None"
            elif pattern_type == "velocity_spike":
                transaction_pattern = f"{random.randint(20, 50)} small/medium transactions in a single day."
                screening_hit = "None"
            elif pattern_type == "nacta_match":
                transaction_pattern = "Normal transaction activity."
                screening_hit = "True Positive NACTA match on entity name."
                
        else:
            customer = random.choice(low_risk_customers)
            risk_score = random.choice(["Low", "Medium"])
            
            transaction_pattern = "Occasional large deposits consistent with business profile."
            screening_hit = "False Positive on similar name (UN Sanctions)."
            
        case = {
            "case_id": case_id,
            "customer_id": customer["customer_id"],
            "transaction_pattern": transaction_pattern,
            "screening_hit": screening_hit,
            "risk_score": risk_score,
            "status": "OPEN"
        }
        cases.append(case)

    print("Saving cases to synthetic_case_files.json...")
    os.makedirs('data', exist_ok=True)
    with open('data/synthetic_case_files.json', 'w') as f:
        json.dump(cases, f, indent=2)

    print("Data generation complete.")

if __name__ == "__main__":
    main()
