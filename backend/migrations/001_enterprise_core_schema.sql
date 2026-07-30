-- MatrixShip Enterprise Core Schema baseline
-- P3.0 migration preparation. This file is intentionally additive and does not switch runtime storage yet.

CREATE TABLE IF NOT EXISTS organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  plan_code TEXT NOT NULL DEFAULT 'standard',
  status TEXT NOT NULL DEFAULT 'active',
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT,
  phone TEXT,
  email TEXT,
  password_hash TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memberships (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'member',
  status TEXT NOT NULL DEFAULT 'active',
  created_at REAL,
  updated_at REAL,
  UNIQUE(org_id, user_id)
);

CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  name TEXT,
  host TEXT,
  online INTEGER NOT NULL DEFAULT 0,
  capacity_json TEXT NOT NULL DEFAULT '{}',
  last_seen REAL,
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  platform TEXT NOT NULL DEFAULT 'douyin',
  node_id TEXT REFERENCES nodes(id),
  name TEXT,
  handle TEXT,
  cookie_ready INTEGER NOT NULL DEFAULT 0,
  usable INTEGER NOT NULL DEFAULT 0,
  online INTEGER NOT NULL DEFAULT 0,
  authorized_at REAL,
  cookie_updated_at REAL,
  last_seen REAL,
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  title TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'video',
  file_count INTEGER NOT NULL DEFAULT 0,
  files_json TEXT NOT NULL DEFAULT '[]',
  urls_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS publish_queue_items (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  account_id TEXT REFERENCES accounts(id),
  material_id TEXT REFERENCES materials(id),
  status TEXT NOT NULL DEFAULT 'pending',
  receipt_id TEXT,
  task_id TEXT,
  last_error TEXT,
  preflight_json TEXT NOT NULL DEFAULT '{}',
  events_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS central_tasks (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  type TEXT,
  path TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  queue_id TEXT REFERENCES publish_queue_items(id),
  account_id TEXT REFERENCES accounts(id),
  node_id TEXT REFERENCES nodes(id),
  payload_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at REAL,
  started_at REAL,
  finished_at REAL,
  updated_at REAL
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  actor_id TEXT,
  action TEXT NOT NULL,
  resource_type TEXT,
  resource_id TEXT,
  summary TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS support_links (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  kind TEXT,
  severity TEXT,
  title TEXT,
  description TEXT,
  resource_json TEXT NOT NULL DEFAULT '{}',
  archived INTEGER NOT NULL DEFAULT 0,
  created_at REAL,
  updated_at REAL
);

CREATE TABLE IF NOT EXISTS finder_leads (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  keyword TEXT,
  source_url TEXT,
  author TEXT,
  comment TEXT,
  intent TEXT,
  score REAL,
  status TEXT NOT NULL DEFAULT 'new',
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS kb_docs (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  title TEXT,
  type TEXT,
  chunks INTEGER NOT NULL DEFAULT 0,
  text_hash TEXT,
  created_at REAL,
  updated_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cloud_login_sessions (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  account_id TEXT,
  node_id TEXT,
  status TEXT,
  phase TEXT,
  progress_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL,
  updated_at REAL,
  closed_at REAL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_accounts_org ON accounts(org_id);
CREATE INDEX IF NOT EXISTS idx_materials_org ON materials(org_id);
CREATE INDEX IF NOT EXISTS idx_queue_org_status ON publish_queue_items(org_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_org_status ON central_tasks(org_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_org_created ON audit_logs(org_id, created_at);
CREATE INDEX IF NOT EXISTS idx_support_org_archived ON support_links(org_id, archived);
CREATE INDEX IF NOT EXISTS idx_finder_org_status ON finder_leads(org_id, status);


CREATE TABLE IF NOT EXISTS persistence_meta (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at REAL
);
