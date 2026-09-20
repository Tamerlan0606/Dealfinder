import os
import sqlite3

SCHEMA='''
CREATE TABLE IF NOT EXISTS buyers(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source TEXT, external_id TEXT, title TEXT, description TEXT, url TEXT, contact TEXT,
 budget_rub REAL, city TEXT, advance_pct REAL, advance_rub REAL, deadline TEXT,
 procurement_type TEXT, sro_required TEXT, experience_required TEXT, security_rub REAL, document_links TEXT, document_text TEXT, economics_json TEXT,
 fit_status TEXT DEFAULT 'ЗАХОДИМ', fit_reasons TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source,external_id)
);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,website TEXT,email TEXT,phone TEXT,categories TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_id INTEGER,supplier_id INTEGER,buy_rub REAL,sell_rub REAL,margin_rub REAL,margin_pct REAL,status TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(buyer_id,supplier_id));
'''

def connect(path=None):
 if path is None:
  path=os.getenv("DB_PATH") or ("/data/deals.db" if os.path.isdir("/data") else "deals.db"):
 c=sqlite3.connect(path); c.row_factory=sqlite3.Row; c.executescript(SCHEMA)
 cols={r[1] for r in c.execute("PRAGMA table_info(buyers)").fetchall()}
 migrations={
  "advance_pct":"ALTER TABLE buyers ADD COLUMN advance_pct REAL",
  "advance_rub":"ALTER TABLE buyers ADD COLUMN advance_rub REAL",
  "deadline":"ALTER TABLE buyers ADD COLUMN deadline TEXT",
  "procurement_type":"ALTER TABLE buyers ADD COLUMN procurement_type TEXT",
  "sro_required":"ALTER TABLE buyers ADD COLUMN sro_required TEXT",
  "experience_required":"ALTER TABLE buyers ADD COLUMN experience_required TEXT",
  "fit_status":"ALTER TABLE buyers ADD COLUMN fit_status TEXT DEFAULT 'ЗАХОДИМ'",
  "fit_reasons":"ALTER TABLE buyers ADD COLUMN fit_reasons TEXT",
  "review_status":"ALTER TABLE buyers ADD COLUMN review_status TEXT DEFAULT 'new'",
  "reviewed_at":"ALTER TABLE buyers ADD COLUMN reviewed_at TEXT",
  "security_rub":"ALTER TABLE buyers ADD COLUMN security_rub REAL",
  "document_links":"ALTER TABLE buyers ADD COLUMN document_links TEXT",
  "document_text":"ALTER TABLE buyers ADD COLUMN document_text TEXT",
  "economics_json":"ALTER TABLE buyers ADD COLUMN economics_json TEXT"
 }
 for col,sql in migrations.items():
  if col not in cols: c.execute(sql)
 return c
