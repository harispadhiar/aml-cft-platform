import os
import psycopg2
from sentence_transformers import SentenceTransformer

# Note: this script assumes you have a postgres DB running with the vector extension installed
# and the schema from services/db/schema.sql applied.
DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:postgres@localhost:5432/aml_platform")

def ingest_documents():
    print("Initializing embedding model...")
    # Using a small, fast model for the PoC
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Mocked base regulatory text
    documents = [
        {
            "jurisdiction": "Pakistan",
            "issuing_body": "SBP",
            "document_type": "Regulation",
            "effective_date": "2020-09-01",
            "content": "SBP AML/CFT Regulations 2020, Clause 3: Regulated Entities must report suspicious transactions, including structured cash deposits that appear designed to evade reporting thresholds, to the FMU within 7 working days of forming suspicion."
        },
        {
            "jurisdiction": "Pakistan",
            "issuing_body": "SECP",
            "document_type": "Regulation",
            "effective_date": "2020-09-01",
            "content": "SECP AML/CFT Regulations: Financial institutions must conduct enhanced due diligence (EDD) when establishing business relationships with Politically Exposed Persons (PEPs) or entities connected to high-risk jurisdictions."
        },
        {
            "jurisdiction": "Global",
            "issuing_body": "FATF",
            "document_type": "Recommendations",
            "effective_date": "2012-02-16",
            "content": "FATF Recommendation 10: Customer Due Diligence (CDD). Financial institutions should be prohibited from keeping anonymous accounts or accounts in obviously fictitious names."
        },
        {
            "jurisdiction": "Pakistan",
            "issuing_body": "NACTA",
            "document_type": "Guidance",
            "effective_date": "2021-01-01",
            "content": "Any match against the Proscribed Persons list under the ATA 1997 requires immediate freezing of funds without prior notice and reporting to NACTA and SBP."
        }
    ]
    
    print(f"Connecting to Database {DB_DSN}...")
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        
        print("Embedding and inserting documents...")
        for doc in documents:
            # Generate embedding
            embedding = model.encode(doc["content"])
            embedding_list = embedding.tolist()
            
            # Insert into pgvector (regulatory_corpus table)
            cur.execute("""
                INSERT INTO public.regulatory_corpus 
                (jurisdiction, issuing_body, document_type, effective_date, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                doc["jurisdiction"],
                doc["issuing_body"],
                doc["document_type"],
                doc["effective_date"],
                doc["content"],
                embedding_list
            ))
            
        conn.commit()
        cur.close()
        conn.close()
        print(f"Successfully ingested {len(documents)} documents into regulatory_corpus.")
        
    except Exception as e:
        print(f"Failed to connect or insert to DB: {e}")
        print("Ensure PostgreSQL is running, pgvector is installed, and schema.sql is applied.")

if __name__ == "__main__":
    ingest_documents()
