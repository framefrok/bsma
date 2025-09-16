# database.py
import sqlite3
import time
from typing import List, Optional, Dict, Tuple
import json
from datetime import datetime

DB_PATH = "bsp.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            bonus REAL DEFAULT 0,
            notify_enabled INTEGER DEFAULT 1,
            notify_interval INTEGER DEFAULT 15,
            last_reminder INTEGER DEFAULT 0,
            anchor INTEGER DEFAULT 0,
            trade_level INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS market (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource TEXT,
            buy REAL,
            sell REAL,
            quantity INTEGER,
            timestamp INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            resource TEXT,
            target_price REAL,
            direction TEXT,
            speed REAL,
            current_price REAL,
            alert_time TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            chat_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            text TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            notify_enabled INTEGER DEFAULT 1,
            notify_interval INTEGER DEFAULT 15,
            last_reminder INTEGER DEFAULT 0,
            pinned_message_id INTEGER,
            no_pin INTEGER DEFAULT 0,
            profit_settings TEXT DEFAULT '{}'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_profit_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            resource TEXT,
            threshold_price REAL,
            min_quantity INTEGER,
            active INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            resource TEXT,
            action TEXT,
            quantity INTEGER,
            price REAL,
            total_gold REAL,
            profit REAL DEFAULT 0,
            timestamp INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_users (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

# User functions
def ensure_user(user_id: int, username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def get_user(user_id: int) -> Optional[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_user_bonus(user_id: int, bonus: float):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET bonus = ? WHERE id = ?", (bonus, user_id))
    conn.commit()
    conn.close()

def update_user_field(user_id: int, field: str, value):
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, user_id))
    conn.commit()
    conn.close()

def ensure_group_user(chat_id: int, user_id: int, username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO group_users (chat_id, user_id, username) VALUES (?, ?, ?)", (chat_id, user_id, username))
    conn.commit()
    conn.close()

def get_group_users(chat_id: int) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM group_users WHERE chat_id = ?", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_alerts() -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM alerts WHERE status='active'")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_active_alerts(user_id: int) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM alerts WHERE user_id=? AND status='active'", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_alert_by_id(alert_id: int) -> Optional[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_alert_status(alert_id: int, status: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE alerts SET status=? WHERE id=?", (status, alert_id))
    conn.commit()
    conn.close()

def update_alert_fields(alert_id: int, fields: dict):
    conn = get_connection()
    c = conn.cursor()
    keys = ', '.join([f"{k}=?" for k in fields.keys()])
    values = list(fields.values())
    values.append(alert_id)
    c.execute(f"UPDATE alerts SET {keys} WHERE id=?", values)
    conn.commit()
    conn.close()

def insert_alert_record(user_id: int, resource: str, target_price: float, direction: str,
                        speed: float, current_price: float, alert_time: str, chat_id: Optional[int] = None) -> int:
    conn = get_connection()
    c = conn.cursor()
    now = time.time()
    c.execute("""
        INSERT INTO alerts (user_id, resource, target_price, direction, speed, current_price, alert_time, created_at, chat_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, resource, target_price, direction, speed, current_price, alert_time, datetime.now().isoformat(), chat_id))
    alert_id = c.lastrowid
    conn.commit()
    conn.close()
    return alert_id

def cancel_user_alerts(user_id: int) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE alerts SET status='cancelled' WHERE user_id=? AND status='active'", (user_id,))
    count = c.rowcount
    conn.commit()
    conn.close()
    return count

# Market functions
def insert_market_record(resource: str, buy: float, sell: float, quantity: int, timestamp: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO market (resource, buy, sell, quantity, timestamp) VALUES (?, ?, ?, ?, ?)", (resource, buy, sell, quantity, timestamp))
    conn.commit()
    conn.close()

def get_latest_market(resource: str) -> Optional[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM market WHERE resource=? ORDER BY timestamp DESC LIMIT 1", (resource,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_latest_market_all() -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM market ORDER BY timestamp DESC LIMIT 4")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_market(resource: str, minutes: int = 15) -> List[Dict]:
    cutoff = int(time.time()) - minutes * 60
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM market WHERE resource=? AND timestamp>=? ORDER BY timestamp ASC", (resource, cutoff))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_market_history(resource: str, hours: int = 24) -> List[Dict]:
    cutoff = int(time.time()) - hours * 3600
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM market WHERE resource=? AND timestamp>=? ORDER BY timestamp ASC", (resource, cutoff))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_market_week_range(resource: str, price_field: str, week_start: int) -> Tuple[float, float]:
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"SELECT MIN({price_field}) as minp, MAX({price_field}) as maxp FROM market WHERE resource=? AND timestamp>=?", (resource, week_start))
    row = c.fetchone()
    conn.close()
    return (row['minp'], row['maxp']) if row else (0, 0)

def get_market_week_max_price(resource: str, price_field: str, week_start: int) -> float:
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"SELECT MAX({price_field}) as maxp FROM market WHERE resource=? AND timestamp>=?", (resource, week_start))
    row = c.fetchone()
    conn.close()
    return row['maxp'] if row and row['maxp'] is not None else 0.0

def get_market_week_max_qty(resource: str, week_start: int) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT MAX(quantity) as maxq FROM market WHERE resource=? AND timestamp>=?", (resource, week_start))
    row = c.fetchone()
    conn.close()
    return row['maxq'] if row and row['maxq'] else 0

def get_global_latest_timestamp() -> Optional[int]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT MAX(timestamp) as ts FROM market")
    row = c.fetchone()
    conn.close()
    return row['ts'] if row and row['ts'] else None

# Push settings
def get_users_with_notifications_enabled() -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, notify_interval, last_reminder FROM users WHERE notify_enabled=1")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "notify_interval": r[1], "last_reminder": r[2]} for r in rows]

def set_user_last_reminder(user_id: int, ts: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET last_reminder=? WHERE id=?", (ts, user_id))
    conn.commit()
    conn.close()

def get_chats_with_notifications_enabled() -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT chat_id, notify_interval, last_reminder FROM chats WHERE notify_enabled=1")
    rows = c.fetchall()
    conn.close()
    return [{"chat_id": r[0], "notify_interval": r[1], "last_reminder": r[2]} for r in rows]

def set_chat_last_reminder(chat_id: int, ts: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE chats SET last_reminder=? WHERE chat_id=?", (ts, chat_id))
    conn.commit()
    conn.close()

def get_user_push_settings(user_id: int) -> Dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT notify_enabled as enabled, notify_interval as interval FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"enabled": bool(row[0]), "interval": row[1]}
    return {"enabled": True, "interval": 15}

def update_user_push_settings(user_id: int, enabled: bool = None, interval: int = None):
    conn = get_connection()
    c = conn.cursor()
    if enabled is not None:
        c.execute("UPDATE users SET notify_enabled=? WHERE id=?", (1 if enabled else 0, user_id))
    if interval is not None:
        c.execute("UPDATE users SET notify_interval=? WHERE id=?", (interval, user_id))
    conn.commit()
    conn.close()

def get_chat_settings(chat_id: int) -> Dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    if row:
        d = dict(row)
        d['notify_enabled'] = bool(d['notify_enabled'])
        d['profit_settings'] = json.loads(d['profit_settings'])
        return d
    return {"notify_enabled": True, "notify_interval": 15, "pinned_message_id": None, "no_pin": False, "profit_settings": {}}

def upsert_chat_settings(chat_id: int, notify_enabled: bool, interval: int, pinned_message_id: int = None, no_pin: bool = None, profit_settings: dict = None):
    conn = get_connection()
    c = conn.cursor()
    current = get_chat_settings(chat_id)
    new_ps = json.dumps(current['profit_settings'] | (profit_settings or {}))
    c.execute("""
        INSERT INTO chats (chat_id, notify_enabled, notify_interval, pinned_message_id, no_pin, profit_settings) 
        VALUES (?, ?, ?, ?, ?, ?) 
        ON CONFLICT(chat_id) DO UPDATE SET 
        notify_enabled=excluded.notify_enabled, 
        notify_interval=excluded.notify_interval, 
        pinned_message_id=excluded.pinned_message_id,
        no_pin=excluded.no_pin,
        profit_settings=excluded.profit_settings
    """, (chat_id, 1 if notify_enabled else 0, interval, pinned_message_id, 1 if no_pin else 0, new_ps))
    conn.commit()
    conn.close()

def set_chat_no_pin(chat_id: int, no_pin: bool):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE chats SET no_pin=? WHERE chat_id=?", (1 if no_pin else 0, chat_id))
    conn.commit()
    conn.close()

def unpin_all_messages(chat_id: int):
    # Placeholder: in real, use bot.unpin_chat_message
    pass

def get_chats_with_profit_alerts() -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT chat_id FROM chat_profit_alerts WHERE active=1")
    rows = c.fetchall()
    conn.close()
    return [{"chat_id": r[0]} for r in rows]

def get_chat_profit_alerts(chat_id: int) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM chat_profit_alerts WHERE chat_id=? AND active=1", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def deactivate_profit_alert(chat_id: int, resource: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE chat_profit_alerts SET active=0 WHERE chat_id=? AND resource=?", (chat_id, resource))
    conn.commit()
    conn.close()

def clear_all_profit_alerts(chat_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE chat_profit_alerts SET active=0 WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

# Transactions
def insert_transaction(user_id: int, resource: str, action: str, quantity: int, price: float, total_gold: float, profit: float = 0, timestamp: Optional[int] = None):
    ts = timestamp or int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO transactions (user_id, resource, action, quantity, price, total_gold, profit, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, resource, action, quantity, price, total_gold, profit, ts))
    conn.commit()
    conn.close()

def get_user_transactions(user_id: int, days: int = 1) -> List[Dict]:
    cutoff = int(time.time()) - days * 24 * 3600
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM transactions WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp DESC
    """, (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_daily_profits() -> List[Dict]:
    today_start = int(time.time()) - 24 * 3600
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, SUM(CASE WHEN action = 'sell' THEN total_gold ELSE -total_gold END) as net_gold,
               COUNT(*) as tx_count
        FROM transactions WHERE timestamp >= ? GROUP BY user_id ORDER BY net_gold DESC LIMIT 10
    """, (today_start,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_rank(user_id: int) -> int:
    today_start = int(time.time()) - 24 * 3600
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) + 1 as rank FROM (
            SELECT SUM(CASE WHEN action = 'sell' THEN total_gold ELSE -total_gold END) as net_gold
            FROM transactions WHERE timestamp >= ? GROUP BY user_id HAVING net_gold > (
                SELECT COALESCE(SUM(CASE WHEN action = 'sell' THEN total_gold ELSE -total_gold END), 0)
                FROM transactions WHERE user_id = ? AND timestamp >= ?
            )
        )
    """, (today_start, user_id, today_start))
    row = c.fetchone()
    conn.close()
    return row['rank'] if row else 1

# Other
def get_bot_stats() -> Dict:
    # Legacy, but keep for compatibility
    conn = get_connection()
    c = conn.cursor()
    stats = {}
    c.execute("SELECT COUNT(*) as cnt FROM users")
    stats['users'] = c.fetchone()['cnt']
    c.execute("SELECT COUNT(DISTINCT resource) as cnt FROM market")
    stats['resources'] = c.fetchone()['cnt']
    conn.close()
    return stats

def get_bot_history(limit: int = 20) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM history ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

init_db()
