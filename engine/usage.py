"""
InboxTriage 使用统计 + 试用/订阅控制（v2）
------------------------------------------------
- 用 Gmail 地址的哈希当身份（不存明文邮箱，保护隐私）
- 记录每次运行，供 /admin 后台查看
- 试用逻辑：每个 Gmail 首次使用起 7 天免费全功能；之后必须订阅
- 订阅：在 /activate 输入邮箱标记（PayPal 付款后跳转），后续可接 Webhook 自动校验

注意：本文件用 SQLite 存本地。Render Free 的文件系统是临时的，
服务重新部署后数据会清空——早期看"有没有人用"足够；
真有稳定流量时请换 Render Postgres（免费档）做持久化。
"""
import sqlite3
import os
import time
import hashlib

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.db")

# 试用期天数
TRIAL_DAYS = 7
# 每日运行上限：免费用户 / 已订阅用户
FREE_DAILY_CAP = 5
PAID_DAILY_CAP = 200

SALT = os.environ.get("USAGE_SALT", "inboxtriage-v2-salt")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        gmail_hash TEXT PRIMARY KEY,
        first_seen INTEGER,
        subscribed INTEGER DEFAULT 0,
        sub_id TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gmail_hash TEXT,
        ts INTEGER,
        emails INTEGER
    )""")
    return c


def hash_gmail(gmail: str) -> str:
    return hashlib.sha256((SALT + (gmail or "").lower().strip()).encode()).hexdigest()


def get_or_create_user(gmail_hash: str, now: int = None):
    now = now or int(time.time())
    c = _conn()
    row = c.execute("SELECT first_seen, subscribed, sub_id FROM users WHERE gmail_hash=?",
                    (gmail_hash,)).fetchone()
    if not row:
        c.execute("INSERT INTO users (gmail_hash, first_seen, subscribed, sub_id) VALUES (?,?,0,'')",
                  (gmail_hash, now))
        c.commit()
        first_seen, subscribed, sub_id = now, 0, ""
    else:
        first_seen, subscribed, sub_id = row
    c.close()
    return {"first_seen": first_seen, "subscribed": bool(subscribed), "sub_id": sub_id or ""}


def mark_subscribed(gmail_hash: str, sub_id: str = "", now: int = None):
    now = now or int(time.time())
    c = _conn()
    c.execute("INSERT OR REPLACE INTO users (gmail_hash, first_seen, subscribed, sub_id) "
              "VALUES (?, COALESCE((SELECT first_seen FROM users WHERE gmail_hash=?),?), 1, ?)",
              (gmail_hash, gmail_hash, now, sub_id or ""))
    c.commit()
    c.close()


def user_state(gmail_hash: str, now: int = None):
    """返回该用户的试用/订阅状态，供 /run 网关判断。"""
    now = now or int(time.time())
    u = get_or_create_user(gmail_hash, now)
    age_days = (now - u["first_seen"]) / 86400.0
    trial_active = (age_days < TRIAL_DAYS)
    if u["subscribed"]:
        status = "paid"
    elif trial_active:
        status = "trial"
    else:
        status = "expired"
    # 今日已用次数
    day_start = now - (now % 86400)
    c = _conn()
    used = c.execute("SELECT COUNT(*) FROM runs WHERE gmail_hash=? AND ts>=?",
                    (gmail_hash, day_start)).fetchone()[0]
    c.close()
    cap = PAID_DAILY_CAP if u["subscribed"] else FREE_DAILY_CAP
    return {
        "status": status,
        "subscribed": u["subscribed"],
        "days_left": max(0, int(TRIAL_DAYS - age_days)),
        "used_today": used,
        "cap": cap,
        "remaining": max(0, cap - used),
    }


def record_run(gmail_hash: str, emails: int, now: int = None):
    now = now or int(time.time())
    c = _conn()
    c.execute("INSERT INTO runs (gmail_hash, ts, emails) VALUES (?,?,?)",
              (gmail_hash, now, emails))
    c.commit()
    c.close()


def stats(now: int = None):
    now = now or int(time.time())
    day_start = now - (now % 86400)
    trial_cut = now - TRIAL_DAYS * 86400
    c = _conn()
    total_runs = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    unique_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    subscribed = c.execute("SELECT COUNT(*) FROM users WHERE subscribed=1").fetchone()[0]
    trial_active = c.execute("SELECT COUNT(*) FROM users WHERE subscribed=0 AND first_seen>=?",
                             (trial_cut,)).fetchone()[0]
    expired = c.execute("SELECT COUNT(*) FROM users WHERE subscribed=0 AND first_seen<?",
                        (trial_cut,)).fetchone()[0]
    runs_today = c.execute("SELECT COUNT(*) FROM runs WHERE ts>=?", (day_start,)).fetchone()[0]
    recent = c.execute(
        "SELECT substr(gmail_hash,1,10), ts, emails FROM runs ORDER BY ts DESC LIMIT 15"
    ).fetchall()
    c.close()
    return {
        "total_runs": total_runs,
        "unique_users": unique_users,
        "subscribed": subscribed,
        "trial_active": trial_active,
        "expired": expired,
        "runs_today": runs_today,
        "recent": [{"hash": r[0], "ts": r[1], "emails": r[2]} for r in recent],
    }
