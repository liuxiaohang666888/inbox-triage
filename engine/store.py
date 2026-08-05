"""
SQLite 本地存储：记录已处理过的邮件，避免重复烧 API 额度。
"""
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "triage.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS processed (
        account TEXT, uid TEXT, subject TEXT, category TEXT,
        payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (account, uid))""")
    return c


def seen_uids(account: str) -> set:
    c = _conn()
    rows = c.execute("SELECT uid FROM processed WHERE account=?", (account,)).fetchall()
    c.close()
    return {r[0] for r in rows}


def save(account: str, mail: dict, ai: dict):
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO processed (account,uid,subject,category,payload) VALUES (?,?,?,?,?)",
        (account, mail["uid"], mail["subject"], ai.get("category", ""),
         json.dumps({"mail": mail, "ai": ai}, ensure_ascii=False)),
    )
    c.commit()
    c.close()
