import json
import csv
import random
import os
from faker import Faker
from datetime import datetime, timedelta

def main():
    fake = Faker('en_PK')
    Faker.seed(42)
    random.seed(42)

    num_customers = 10000
    num_transactions = 100000

    cities = ['Karachi', 'Lahore', 'Islamabad', 'Quetta', 'Peshawar']
    
    customers = []
    customer_ids = []
    
    print(f"Generating {num_customers} customers...")
    for i in range(1, num_customers + 1):
        customer_id = f"CUST-{i:06d}"
        
        # CNIC format: XXXXX-XXXXXXX-X
        cnic = f"{random.randint(10000, 99999)}-{random.randint(1000000, 9999999)}-{random.randint(0, 9)}"
        
        # Address
        street = fake.street_address()
        city = random.choice(cities)
        
        customer = {
            "customer_id": customer_id,
            "name": fake.name(),
            "cnic": cnic,
            "address": f"{street}, {city}",
            "city": city,
            "risk_tier": "Low" # Default, will be updated based on red flags
        }
        customers.append(customer)
        customer_ids.append(customer_id)

    print("Generating transactions...")
    transactions = []
    
    # 90% normal transactions, 10% anomalous
    anomalous_customers = random.sample(customer_ids, int(num_customers * 0.1))
    
    current_date = datetime.now() - timedelta(days=365)
    
    # Normal transactions
    num_normal_tx = int(num_transactions * 0.9)
    for i in range(1, num_normal_tx + 1):
        tx_id = f"TXN-{i:08d}"
        cust_id = random.choice(customer_ids)
        amount = round(random.uniform(1000, 50000), 2)
        date = current_date + timedelta(days=random.randint(0, 365), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        
        transactions.append({
            "transaction_id": tx_id,
            "customer_id": cust_id,
            "amount": amount,
            "type": random.choice(["DEPOSIT", "WITHDRAWAL", "TRANSFER"]),
            "timestamp": date.isoformat(),
            "destination_country": "PK",
            "notes": "Normal transaction"
        })

    # Anomalous transactions (10,000 txs)
    # 1. Structuring/Smurfing (cash deposits below 1,000,000 PKR reporting threshold)
    # 2. Wire transfers to high-risk corridors
    # 3. Sudden spikes in velocity
    
    tx_counter = num_normal_tx + 1
    high_risk_corridors = ['Iran', 'Syria', 'North Korea', 'Yemen', 'Myanmar']
    
    for cust_id in anomalous_customers:
        anomaly_type = random.choice(["structuring", "high_risk_wire", "velocity_spike"])
        
        if anomaly_type == "structuring":
            # 5-10 deposits just below 1,000,000
            num_deposits = random.randint(5, 10)
            base_date = current_date + timedelta(days=random.randint(0, 350))
            for _ in range(num_deposits):
                tx_id = f"TXN-{tx_counter:08d}"
                amount = round(random.uniform(900000, 999999), 2)
                base_date += timedelta(hours=random.randint(1, 12))
                transactions.append({
                    "transaction_id": tx_id,
                    "customer_id": cust_id,
                    "amount": amount,
                    "type": "CASH_DEPOSIT",
                    "timestamp": base_date.isoformat(),
                    "destination_country": "PK",
                    "notes": "Structuring risk"
                })
                tx_counter += 1
                
        elif anomaly_type == "high_risk_wire":
            tx_id = f"TXN-{tx_counter:08d}"
            amount = round(random.uniform(100000, 5000000), 2)
            date = current_date + timedelta(days=random.randint(0, 365))
            transactions.append({
                "transaction_id": tx_id,
                "customer_id": cust_id,
                "amount": amount,
                "type": "WIRE_TRANSFER",
                "timestamp": date.isoformat(),
                "destination_country": random.choice(high_risk_corridors),
                "notes": "High risk corridor"
            })
            tx_counter += 1
            
        elif anomaly_type == "velocity_spike":
            # 20-50 small/medium transactions in a single day
            num_spikes = random.randint(20, 50)
            base_date = current_date + timedelta(days=random.randint(0, 350))
            for _ in range(num_spikes):
                tx_id = f"TXN-{tx_counter:08d}"
                amount = round(random.uniform(50000, 200000), 2)
                base_date += timedelta(minutes=random.randint(5, 30))
                transactions.append({
                    "transaction_id": tx_id,
                    "customer_id": cust_id,
                    "amount": amount,
                    "type": random.choice(["TRANSFER", "DEPOSIT"]),
                    "timestamp": base_date.isoformat(),
                    "destination_country": "PK",
                    "notes": "Velocity spike"
                })
                tx_counter += 1

    # Update risk tier for anomalous customers
    anomalous_set = set(anomalous_customers)
    for c in customers:
        if c['customer_id'] in anomalous_set:
            c['risk_tier'] = "High"

    print("Saving customers to synthetic_customers.json...")
    os.makedirs('data', exist_ok=True)
    with open('data/synthetic_customers.json', 'w') as f:
        json.dump(customers, f, indent=2)
        
    print("Saving transactions to synthetic_transactions.csv...")
    # Sort transactions by timestamp
    transactions.sort(key=lambda x: x['timestamp'])
    
    with open('data/synthetic_transactions.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["transaction_id", "customer_id", "amount", "type", "timestamp", "destination_country", "notes"])
        writer.writeheader()
        writer.writerows(transactions)
        
    print("Data generation complete.")

if __name__ == "__main__":
    main()
