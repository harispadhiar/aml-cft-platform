import os
import json
from server import append_log, verify_chain

LOG_FILE = "audit_log.jsonl"

def main():
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
        
    print("Writing 1,000 log entries...")
    for i in range(1000):
        append_log(f"Test action {i}", "tenant_A", f"user_{i%10}")
        
    print("Running validation script...")
    status = verify_chain()
    print(f"Validation Result: {status}")
    
    # Tamper with row 500
    print("\nTampering with row 500...")
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
        
    entry = json.loads(lines[500])
    entry["payload"] = "Tampered action 500"
    lines[500] = json.dumps(entry) + "\n"
    
    with open(LOG_FILE, "w") as f:
        f.writelines(lines)
        
    print("Running validation script again...")
    status = verify_chain()
    print(f"Validation Result: {status}")

if __name__ == "__main__":
    main()
