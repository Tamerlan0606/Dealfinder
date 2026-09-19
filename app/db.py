import sqlite3
SCHEMA='''
CREATE TABLE IF NOT EXISTS buyers(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,external_id TEXT,title TEXT,description TEXT,url TEXT,contact TEXT,budget_rub REAL,city TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(source,external_id));
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,website TEXT,email TEXT,phone TEXT,categories TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_id INTEGER,supplier_id INTEGER,buy_rub REAL,sell_rub REAL,margin_rub REAL,margin_pct REAL,status TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(buyer_id,supplier_id));
'''
def connect(path='deals.db'):
 c=sqlite3.connect(path); c.row_factory=sqlite3.Row; c.executescript(SCHEMA); return c
