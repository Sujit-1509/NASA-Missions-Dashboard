-- NASA Missions schema
-- Drops and recreates `missions` with types aligned to provided CSV columns.

DROP TABLE IF EXISTS missions;

CREATE TABLE IF NOT EXISTS missions (
  mission_id TEXT PRIMARY KEY,
  mission_name TEXT,
  launch_date TEXT, -- stored as ISO date string (YYYY-MM-DD)
  launch_year INTEGER,
  target_type TEXT,
  target_name TEXT,
  mission_type TEXT,
  distance_ly REAL,
  duration_years REAL,
  cost_billion_usd REAL,
  scientific_yield REAL,
  crew_size INTEGER,
  success_pct REAL,
  fuel_consumption_tons REAL,
  payload_weight_tons REAL,
  launch_vehicle TEXT
);

CREATE INDEX IF NOT EXISTS idx_missions_year ON missions (launch_year);
CREATE INDEX IF NOT EXISTS idx_missions_type ON missions (mission_type);
CREATE INDEX IF NOT EXISTS idx_missions_target ON missions (target_type);
CREATE INDEX IF NOT EXISTS idx_missions_vehicle ON missions (launch_vehicle);
