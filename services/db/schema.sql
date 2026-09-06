-- 1. Create pgvector extension if not exists
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Tenant Configuration Table (Shared Schema with RLS)
CREATE TABLE IF NOT EXISTS public.tenant_config (
    tenant_id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    risk_thresholds JSONB NOT NULL DEFAULT '{"high": 80, "medium": 50}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Enable Row-Level Security on tenant_config
ALTER TABLE public.tenant_config ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own tenant's config
-- Assumes the current user's tenant ID is set in the session variable 'app.current_tenant_id'
CREATE POLICY tenant_isolation_policy ON public.tenant_config
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- 3. Isolated Per-Tenant DB Schemas for Cases
-- Note: In a real multi-tenant system, this script would be executed dynamically 
-- when a new tenant is provisioned. For this POC, we'll create schemas for Tenant A and Tenant B.

-- Create schemas
CREATE SCHEMA IF NOT EXISTS tenant_a;
CREATE SCHEMA IF NOT EXISTS tenant_b;

-- Define Case Table for Tenant A
CREATE TABLE IF NOT EXISTS tenant_a.cases (
    case_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    transaction_pattern TEXT,
    screening_hit TEXT,
    risk_score VARCHAR(20),
    status VARCHAR(50) DEFAULT 'OPEN',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Define Case Table for Tenant B
CREATE TABLE IF NOT EXISTS tenant_b.cases (
    case_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    transaction_pattern TEXT,
    screening_hit TEXT,
    risk_score VARCHAR(20),
    status VARCHAR(50) DEFAULT 'OPEN',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Regulatory Corpus Table (Vector Store)
-- This is shared across tenants since regulatory text is public/shared
CREATE TABLE IF NOT EXISTS public.regulatory_corpus (
    id SERIAL PRIMARY KEY,
    jurisdiction VARCHAR(50) NOT NULL,
    issuing_body VARCHAR(100) NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    effective_date DATE,
    content TEXT NOT NULL,
    embedding vector(1536) -- Assuming OpenAI ada-002 dimensions or similar
);

-- Index for vector similarity search
CREATE INDEX ON public.regulatory_corpus USING hnsw (embedding vector_l2_ops);

-- Grant usage appropriately
GRANT USAGE ON SCHEMA tenant_a TO CURRENT_USER;
GRANT USAGE ON SCHEMA tenant_b TO CURRENT_USER;
