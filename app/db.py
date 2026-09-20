import sqlite3

SCHEMA='''
CREATE TABLE IF NOT EXISTS buyers(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source TEXT, external_id TEXT, title TEXT, description TEXT, url TEXT, contact TEXT,
 budget_rub REAL, city TEXT, advance_pct REAL, advance_rub REAL, deadline TEXT,
 procurement_type TEXT, sro_required TEXT, experience_required TEXT,
 fit_status TEXT DEFAULT 'ЗАХОДИМ', fit_reasons TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source,external_id)
);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,website TEXT,email TEXT,phone TEXT,categories TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_id INTEGER,supplier_id INTEGER,buy_rub REAL,sell_rub REAL,margin_rub REAL,margin_pct REAL,status TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(buyer_id,supplier_id));
'''

def connect(path='deals.db'):
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
  "fit_reasons":"ALTER TABLE buyers ADD COLUMN fit_reasons TEXT"
 }
 for col,sql in migrations.items():
  if col not in cols: c.execute(sql)
 return c
