import json
import random
import os
from datetime import datetime

def generate_narrative(case, customer):
    date = datetime.now().strftime("%Y-%m-%d")
    name = customer.get("name", "Unknown")
    cnic = customer.get("cnic", "Unknown")
    address = customer.get("address", "Unknown")
    
    pattern = case.get("transaction_pattern", "")
    hit = case.get("screening_hit", "")
    
    narrative = (
        f"Suspicious Activity Report (SAR) / Suspicious Transaction Report (STR)\n"
        f"Date: {date}\n\n"
        f"Who: The subject of this report is {name}, holding CNIC {cnic}, residing at {address}. "
        f"The customer profile was reviewed in accordance with SBP AML/CFT Regulations 2020.\n\n"
        f"What & When: Anomaly detected during routine transaction monitoring. "
        f"The subject exhibited the following pattern: {pattern}\n\n"
        f"Where: Transactions occurred within the jurisdiction of Pakistan, utilizing local branch and digital channels.\n\n"
        f"Why: The activity is considered suspicious as it deviates significantly from the established customer profile. "
    )
    
    if "structuring" in pattern.lower() or "deposits" in pattern.lower():
        narrative += "The behavior is indicative of potential structuring (smurfing) designed to evade cash transaction reporting (CTR) thresholds as outlined in FATF Typologies and SBP Circulars."
    elif "wire" in pattern.lower() or "jurisdiction" in pattern.lower():
        narrative += "Funds were remitted to high-risk corridors, raising concerns of illicit financial flows."
    elif "velocity" in pattern.lower():
        narrative += "The high velocity of transactions suggests pass-through activity atypical for retail banking profiles."
    elif "NACTA" in hit:
        narrative += f"Furthermore, a screening match was identified: {hit}. This triggers mandatory reporting obligations under the ATA."
    else:
        narrative += f"Additional screening context: {hit}."

    narrative += "\n\nHow: Funds were received via cash and internal transfers, followed by rapid dissipation. We are submitting this STR to the FMU for further investigation."
    
    return narrative

def main():
    print("Loading synthetic cases and customers...")
    try:
        with open('data/synthetic_case_files.json', 'r') as f:
            cases = json.load(f)
        with open('data/synthetic_customers.json', 'r') as f:
            customers = json.load(f)
            
        cust_map = {c['customer_id']: c for c in customers}
    except FileNotFoundError:
        print("Error: data files not found. Run gen_entities.py and gen_cases.py first.")
        return

    high_risk_cases = [c for c in cases if c.get('risk_score') == 'High']

    print(f"Generating SAR narratives for {len(high_risk_cases)} high-risk cases...")
    
    dataset = []
    
    for case in high_risk_cases:
        cust = cust_map.get(case['customer_id'], {})
        narrative = generate_narrative(case, cust)
        
        record = {
            "case_id": case['case_id'],
            "customer_id": case['customer_id'],
            "cnic": cust.get("cnic"),
            "narrative": narrative
        }
        dataset.append(record)

    print("Saving to synthetic_sar_gold_dataset.jsonl...")
    os.makedirs('data', exist_ok=True)
    with open('data/synthetic_sar_gold_dataset.jsonl', 'w') as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")

    print("Data generation complete.")

if __name__ == "__main__":
    main()
