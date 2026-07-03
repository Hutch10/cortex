-- HUTCHSOLVES CORTEX: PRODUCTION CLOUD SCHEMA (v14.2.0)
-- 1. Tenant Registry
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_name TEXT NOT NULL,
    home_base_icao TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 2. Asset Health (The Iron Oracle)
CREATE TABLE asset_health (
    id SERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    tail_number TEXT NOT NULL,
    iron_ppm REAL,
    flight_hours REAL,
    report_date DATE,
    status TEXT -- STABLE, CAUTION, CRITICAL
);

-- 3. The Sentinel View (Automated Wear Rate Calculation)
CREATE VIEW sentinel_diagnostics AS
SELECT 
    tenant_id,
    tail_number,
    iron_ppm,
    flight_hours,
    report_date,
    (iron_ppm - LAG(iron_ppm) OVER (PARTITION BY tail_number ORDER BY flight_hours)) / 
    NULLIF((flight_hours - LAG(flight_hours) OVER (PARTITION BY tail_number ORDER BY flight_hours)), 0) as wear_rate
FROM asset_health;
