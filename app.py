"""
InboxTriage —— 完整网页应用（可公网部署版）
------------------------------------------------
功能：
  - 用户填自己的 Gmail + 16 位应用专用密码
  - 点 Run -> 只读拉最近邮件 -> AI 分类/写草稿/抽待办 -> 网页直接出报告
  - /demo 按钮：内置样例数据展示效果，零 API 消耗
  - 全程只读（readonly=True），物理上不可能发信/删信

部署（见 怎么上线.md）：
  - 环境变量：PROVIDER(zhipu|gemini|deepseek) / ZHIPU_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / PAYMENT_URL
  - 启动命令：gunicorn --bind 0.0.0.0:$PORT app:app
  - 依赖见 requirements.txt
"""
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))
import mailbox, ai, report

from flask import Flask, request

app = Flask(__name__)

# ---------------- 密钥从环境变量读（绝不放进代码/仓库）----------------
PROVIDER = os.environ.get("PROVIDER", "zhipu").lower()
if PROVIDER == "gemini":
    API_KEY = os.environ.get("GEMINI_API_KEY", "")
elif PROVIDER == "zhipu":
    API_KEY = os.environ.get("ZHIPU_API_KEY", "")
else:
    API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

GUIDE_LINK = "https://99b4fd12751a4bda9250171ec55201d6.gz5.agentos-app.net"
PAYMENT_URL = os.environ.get("PAYMENT_URL", "")

# ---------------- 极简单 IP 限额（公网无登录墙，防滥用烧额度）--------
_HITS = defaultdict(list)
DAILY_CAP = 10  # 每个 IP 每天最多跑 10 次


def _allowed(ip: str) -> bool:
    now = time.time()
    _HITS[ip] = [t for t in _HITS[ip] if now - t < 86400]
    if len(_HITS[ip]) >= DAILY_CAP:
        return False
    _HITS[ip].append(now)
    return True


# ---------------------------------------------------------------- 引擎封装
def run_triage(gmail, pwd, days, owner_ctx):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mails = mailbox.fetch_recent(gmail, pwd, days=days, limit=60)
    results = []
    for m in mails:
        a = ai.analyse(m, API_KEY, today,
                       owner_context=owner_ctx, provider=PROVIDER)
        results.append({"mail": m, "ai": a})
    return results


# ---------------------------------------------------------------- 首页
PAYMENT_BLOCK = (
    f'<a class="sub-btn" href="{PAYMENT_URL}" target="_blank" rel="noopener">'
    f'Subscribe — $12/mo</a>'
    if PAYMENT_URL else
    '<span class="sub-note">Subscriptions open soon — join the waitlist above.</span>'
)

INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InboxTriage — connect your Gmail</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Helvetica,Arial,sans-serif;
background:#0e1116;color:#e6edf3;line-height:1.55;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.box{width:100%;max-width:480px;background:#161b22;border:1px solid #30363d;border-radius:16px;padding:34px 30px}
.brand{font-weight:800;font-size:21px;letter-spacing:-.02em;margin-bottom:4px}
.brand span{color:#1f6feb}
.sub{color:#8b949e;font-size:14px;margin-bottom:22px}
label{display:block;font-size:12.5px;font-weight:600;color:#c9d1d9;margin:16px 0 7px}
input{width:100%;padding:12px 14px;border:1px solid #30363d;border-radius:9px;background:#0d1117;
color:#e6edf3;font-size:14.5px;font-family:inherit}
input:focus{outline:2px solid #1f6feb;outline-offset:-1px;border-color:transparent}
.row{display:flex;gap:12px}
.row>div{flex:1}
.btn{width:100%;margin-top:22px;padding:13px;border:0;border-radius:10px;background:#1f6feb;
color:#fff;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
.btn:hover{background:#1858c4}
.hint{margin-top:14px;font-size:12px;color:#8b949e;line-height:1.6}
.hint code{background:#0d1117;border:1px solid #30363d;padding:1px 6px;border-radius:5px;color:#79c0ff}
.demo{display:block;text-align:center;margin-top:16px;font-size:13.5px;color:#79c0ff;
text-decoration:none;font-weight:600}
.demo:hover{text-decoration:underline}
.sub-bar{margin-top:20px;padding-top:20px;border-top:1px solid #30363d;text-align:center}
.sub-btn{display:inline-block;background:#137a4d;color:#fff;padding:11px 22px;border-radius:10px;
font-weight:700;font-size:14px;text-decoration:none}
.sub-btn:hover{background:#0f6340}
.sub-note{font-size:13px;color:#8b949e}
</style></head>
<body><div class="box">
  <div class="brand">Inbox<span>Triage</span></div>
  <div class="sub">Read-only Gmail triage. Drafts only — we never send on your behalf.</div>
  <form method="POST" action="/run">
    <label>Your Gmail address</label>
    <input type="email" name="gmail" placeholder="you@gmail.com" required>
    <label>16-char App Password <span style="color:#8b949e;font-weight:400">(not your login password)</span></label>
    <input type="password" name="pwd" placeholder="abcd efgh ijkl mnop" required>
    <div class="row">
      <div>
        <label>Scan last (days)</label>
        <input type="number" name="days" value="1" min="1" max="7">
      </div>
      <div>
        <label>What you sell (optional)</label>
        <input type="text" name="ctx" placeholder="Etsy shop, handmade">
      </div>
    </div>
    <button class="btn" type="submit">Run InboxTriage &rarr;</button>
  </form>
  <a class="demo" href="/demo">Try the demo (no Gmail needed)</a>
  <div class="hint">
    App password: open <code>myaccount.google.com/apppasswords</code> (needs 2-step verification on),
    name it anything, copy the 16-char code. Revoke it anytime to cut access.<br>
    Not sure how? <a href="__GUIDE_LINK__" target="_blank" style="color:#79c0ff">See the 4-step setup guide &rarr;</a>
  </div>
  <div class="sub-bar">__PAYMENT__</div>
</div></body></html>"""
INDEX = INDEX.replace("__GUIDE_LINK__", GUIDE_LINK).replace("__PAYMENT__", PAYMENT_BLOCK)


# ---------------------------------------------------------------- 路由
@app.route("/")
def index():
    return INDEX


@app.route("/run", methods=["POST"])
def run():
    if not API_KEY:
        return ("<div style='font-family:sans-serif;max-width:560px;margin:60px auto;padding:24px;"
                "border:1px solid #e6e9ee;border-radius:12px'>"
                "<h2>Service is being configured.</h2>"
                "<p style='color:#5b6672'>The AI key isn't set yet. Please check back shortly.</p>"
                "<a href='/'>← Back</a></div>")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0").split(",")[0].strip()
    if not _allowed(ip):
        return ("<div style='font-family:sans-serif;max-width:560px;margin:60px auto;padding:24px;"
                "border:1px solid #e6e9ee;border-radius:12px'>"
                "<h2>Daily limit reached</h2>"
                "<p style='color:#5b6672'>You've used your 10 free runs for today. Come back tomorrow, "
                "or subscribe for unlimited daily scans.</p>"
                "<a href='/'>← Back</a></div>")

    gmail = (request.form.get("gmail") or "").strip()
    pwd = (request.form.get("pwd") or "").strip()
    ctx = (request.form.get("ctx") or "").strip()
    try:
        days = max(1, min(7, int(request.form.get("days", 1) or 1)))
    except Exception:
        days = 1

    if not gmail or not pwd:
        return "<h2>Missing Gmail or app password.</h2><a href='/'>Back</a>"

    try:
        results = run_triage(gmail, pwd, days, ctx)
    except Exception as e:
        err = str(e)
        return (f"<div style='font-family:sans-serif;max-width:560px;margin:60px auto;padding:24px;"
                f"border:1px solid #e6e9ee;border-radius:12px'>"
                f"<h2 style='color:#d9480f'>Could not connect to {gmail}</h2>"
                f"<p style='color:#5b6672;margin:12px 0'>Most common causes:</p>"
                f"<ul style='color:#5b6672;line-height:1.8'>"
                f"<li>2-Step Verification is OFF — Google blocks app passwords without it.</li>"
                f"<li>The 16-char app password was typed wrong (no spaces needed).</li>"
                f"<li>Wrong Gmail address.</li></ul>"
                f"<pre style='background:#f6f8fa;padding:12px;border-radius:8px;overflow:auto;font-size:12px'>{err[:300]}</pre>"
                f"<a href='/'>← Back</a></div>")

    if not results:
        return (f"<div style='font-family:sans-serif;max-width:560px;margin:60px auto;padding:24px;"
                f"border:1px solid #e6e9ee;border-radius:12px'>"
                f"<h2>No emails in the last {days} day(s).</h2>"
                f"<p style='color:#5b6672'>Try a larger 'days' value, or send yourself a test email first.</p>"
                f"<a href='/'>← Back</a></div>")

    return report.build(results, gmail)


@app.route("/demo")
def demo():
    SAMPLE = [
        {
            "mail": {
                "subject": "Re: Order #4821 — wrong size, can I swap?",
                "sender": "Anna Whitfield <anna.w@buyer.com>",
                "date": "Tue, 04 Aug 2026 09:12:00 +0000",
                "body": "Hi! I ordered the linen shirt in M but it's too small. "
                        "Can I exchange for L? My wedding is Aug 15 and I need it before then. "
                        "Also do you cover return shipping? Thanks!",
            },
            "ai": {
                "category": "customer", "urgency": 4,
                "summary": "Wants size M->L exchange, needs it before Aug 15 wedding",
                "reply_draft": "Hi Anna,\n\nOf course — let's get you the L sorted before the big day. "
                               "I'll send a prepaid exchange label today; just drop the M back within 7 days. "
                               "Your L shirt ships same-day and should arrive well before Aug 15. "
                               "No extra charge for the swap.\n\nBest,",
                "tasks": [{"title": "Ship L linen shirt to Anna (order #4821)", "due_date": "2026-08-04"}],
            },
        },
        {
            "mail": {
                "subject": "Wholesale inquiry — 200 units for our store",
                "sender": "Marco <marco@boutique.co>",
                "date": "Tue, 04 Aug 2026 11:40:00 +0000",
                "body": "Hello, we run a small retail shop in Lisbon and love your products. "
                        "Could you quote for 200 mixed units? Need pricing and lead time by Wednesday.",
            },
            "ai": {
                "category": "lead", "urgency": 3,
                "summary": "Bulk 200-unit wholesale request, wants quote by Wed",
                "reply_draft": "Hi Marco,\n\nLove that you're interested in stocking us in Lisbon! "
                               "For 200 mixed units: tiered pricing starts at [price per unit] with "
                               "15% off at 500+. Lead time is [X] weeks after deposit. "
                               "I'll send the full PDF catalogue and quote by Wednesday — "
                               "could you confirm which product lines you'd like included?\n\nBest,",
                "tasks": [{"title": "Send wholesale quote to Marco (200 units)", "due_date": "2026-08-05"}],
            },
        },
        {
            "mail": {
                "subject": "PayPal dispute opened on transaction 9F2…",
                "sender": "PayPal <service@paypal.com>",
                "date": "Tue, 04 Aug 2026 08:01:00 +0000",
                "body": "A customer has opened a dispute for transaction 9F2K. "
                        "Respond with evidence by Aug 7 to avoid the chargeback.",
            },
            "ai": {
                "category": "high_risk", "urgency": 5,
                "summary": "PayPal dispute opened, evidence deadline Aug 7",
                "reply_draft": "",
                "tasks": [{"title": "Upload evidence to PayPal dispute (deadline)", "due_date": "2026-08-07"}],
            },
        },
        {
            "mail": {
                "subject": "🔥 Boost your Etsy sales 10x with this one trick!",
                "sender": "GrowthBot <no-reply@spammy.tools>",
                "date": "Tue, 04 Aug 2026 03:20:00 +0000",
                "body": "Congratulations! Your shop qualifies for our premium growth package. "
                        "Limited time 90% off. Click here to claim.",
            },
            "ai": {
                "category": "spam", "urgency": 1,
                "summary": "Promotional spam, ignore",
                "reply_draft": "",
                "tasks": [],
            },
        },
    ]
    return report.build(SAMPLE, "demo@inboxtriage.app")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
