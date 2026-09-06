import os
import json
import hashlib
from datetime import datetime
from mcp.server.mcpserver import MCPServer

# Initialize MCP server
mcp = MCPServer("audit-log-mcp")

LOG_FILE = "audit_log.jsonl"

def get_last_hash() -> str:
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        # Genesis hash
        return hashlib.sha256(b"genesis").hexdigest()
    
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
        if not lines:
            return hashlib.sha256(b"genesis").hexdigest()
        last_entry = json.loads(lines[-1].strip())
        return last_entry.get("hash", "")

@mcp.tool()
def append_log(payload: str, tenant_id: str, user_id: str) -> str:
    """
    Append an entry to the hash-chained audit log.
    
    Args:
        payload: JSON-encoded string describing the action.
        tenant_id: The ID of the tenant.
        user_id: The ID of the user performing the action.
    """
    last_hash = get_last_hash()
    
    timestamp = datetime.utcnow().isoformat()
    
    entry_data = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "timestamp": timestamp,
        "payload": payload,
        "prev_hash": last_hash
    }
    
    # Compute SHA256(Payload_n || H_n-1)
    # To be deterministic, we serialize the entry data (excluding the new hash)
    entry_str = json.dumps(entry_data, sort_keys=True)
    new_hash = hashlib.sha256(entry_str.encode('utf-8')).hexdigest()
    
    entry_data["hash"] = new_hash
    
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry_data) + "\n")
        
    return f"Successfully appended to audit log. Hash: {new_hash}"

@mcp.tool()
def verify_chain() -> str:
    """
    Verify the integrity of the hash chain in the audit log.
    Returns a status message.
    """
    if not os.path.exists(LOG_FILE):
        return "Log file is empty."
        
    prev_hash = hashlib.sha256(b"genesis").hexdigest()
    
    with open(LOG_FILE, "r") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            entry = json.loads(line)
            
            # Check prev_hash linkage
            if entry.get("prev_hash") != prev_hash:
                return f"Tamper error detected at row {i+1}: prev_hash mismatch. Expected {prev_hash}, got {entry.get('prev_hash')}."
            
            # Verify the current hash
            expected_hash = entry.pop("hash")
            entry_str = json.dumps(entry, sort_keys=True)
            computed_hash = hashlib.sha256(entry_str.encode('utf-8')).hexdigest()
            
            if computed_hash != expected_hash:
                return f"Tamper error detected at row {i+1}: Payload hash mismatch."
                
            prev_hash = expected_hash
            
    return "Chain verification passed. Zero tamper errors."

if __name__ == "__main__":
    # Start the server
    mcp.run(transport='stdio')
