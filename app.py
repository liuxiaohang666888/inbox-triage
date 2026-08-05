"""
InboxTriage —— 完整网页应用（可公网部署版）
------------------------------------------------
功能：
  - 用户填自己的 Gmail + 16 位应用专用密码
  - 点 Run -> 只读拉最近邮件 -> AI 分类/写草稿/抽待办 -> 网页直接出报告
  - /demo 按钮：内置样例数据展示效果，零 API 消耗
  - 全程只读（readonly=True），物理上不可能发信/删信

部署（见 怎么上线.md）：
  - 环境变量：PROVIDER(zhipu|gemini|deepseek) / ZHIPU_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY
  - PayPal 订阅按钮已内嵌（client-id / plan-id 写死在代码里，可公开）
  - 启动命令：gunicorn --bind 0.0.0.0:$PORT app:app
  - 依赖见 requirements.txt
"""
import os
import sys
import time
import hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))
import mailbox, ai, report, usage

from flask import Flask, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "inboxtriage-secret")

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
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "inboxadmin")

# ---------------- 试用/订阅网关（按 Gmail 身份，非 IP）--------
def _gate_html(title, msg, sub_text=None):
    return (f"<div style='font-family:sans-serif;max-width:560px;margin:60px auto;padding:28px;"
            f"border:1px solid #e6e9ee;border-radius:12px;text-align:center'>"
            f"<h2 style='font-size:20px'>{title}</h2>"
            f"<p style='color:#5b6672;margin:14px 0;line-height:1.6'>{msg}</p>"
            + (f"<a href='/activate' style='display:inline-block;background:#1f6feb;color:#fff;"
               f"padding:11px 22px;border-radius:10px;font-weight:700;text-decoration:none'>"
               f"{sub_text or 'Activate subscription'}</a>" if sub_text else "")
            + f"<br><a href='/' style='display:inline-block;margin-top:16px;color:#1f6feb'>← Back</a></div>")


def access_check(gmail: str):
    """返回 (ok:bool, block_html_or_None)。按 Gmail 哈希做试用/每日上限控制。"""
    h = usage.hash_gmail(gmail)
    st = usage.user_state(h)
    if st["status"] == "expired":
        return False, _gate_html(
            "Your 7-day free trial has ended",
            "InboxTriage is $12/month. Subscribe and activate with your Gmail to keep using it.",
            "Subscribe &amp; activate — $12/mo")
    if st["remaining"] <= 0:
        if st["subscribed"]:
            return False, _gate_html("Daily limit reached",
                                     "You've used your 200 runs for today. Come back tomorrow.")
        return False, _gate_html("Daily free limit reached",
                                 f"You've used your {st['cap']} free runs today. Subscribe for unlimited daily scans, "
                                 "or come back tomorrow.",
                                 "Subscribe — $12/mo")
    return True, None


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
# PayPal 订阅按钮（client-id / plan-id 均为公开值，可直接写进代码）
PAYPAL_CLIENT_ID = "BAAxyItsTaXijHpq8NBvrle3h6xOpEJ9vc1nl_OvLlwnfe_OoFH8Uz3tGTs9x-p-nI88xGGROfurcvVyig"
PAYPAL_PLAN_ID = "P-27Y71376MG851694YNJZU6RY"

if PAYPAL_PLAN_ID:
    PAYMENT_BLOCK = (
        '<div style="max-width:260px;margin:0 auto"><div id="paypal-sub"></div></div>'
        '<script src="https://www.paypal.com/sdk/js?client-id=' + PAYPAL_CLIENT_ID
        + '&vault=true&intent=subscription"></script>'
        '<script>paypal.Buttons({style:{shape:"rect",color:"gold",layout:"vertical",label:"subscribe"},'
        'createSubscription:function(data,actions){return actions.subscription.create({plan_id:"'
        + PAYPAL_PLAN_ID
        + '"})},onApprove:function(data,actions){window.location.href="/activate?sub="+data.subscriptionID}})'
        '.render("#paypal-sub");</script>'
    )
elif PAYMENT_URL:
    PAYMENT_BLOCK = (
        f'<a class="sub-btn" href="{PAYMENT_URL}" target="_blank" rel="noopener">'
        f'Subscribe — $12/mo</a>'
    )
else:
    PAYMENT_BLOCK = '<span class="sub-note">Subscriptions open soon — join the waitlist above.</span>'

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
  <div class="sub-bar">__PAYMENT__
    <div style="margin-top:12px;font-size:12.5px"><a href="/activate" style="color:#8b949e">Already subscribed? Activate your account &rarr;</a></div>
  </div>
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
    gmail = (request.form.get("gmail") or "").strip()
    pwd = (request.form.get("pwd") or "").strip()
    ctx = (request.form.get("ctx") or "").strip()
    try:
        days = max(1, min(7, int(request.form.get("days", 1) or 1)))
    except Exception:
        days = 1

    if not gmail or not pwd:
        return "<h2>Missing Gmail or app password.</h2><a href='/'>Back</a>"

    # 试用/订阅网关：先拦再用，避免白烧 AI 额度
    ok, block = access_check(gmail)
    if not ok:
        return block

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

    usage.record_run(usage.hash_gmail(gmail), len(results))
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


# ---------------------------------------------------------------- 激活订阅（付款后解锁）
@app.route("/activate", methods=["GET", "POST"])
def activate():
    if request.method == "POST":
        gmail = (request.form.get("gmail") or "").strip().lower()
        sub_id = (request.form.get("sub_id") or "").strip()
        if not gmail or "@" not in gmail:
            return ("<div style='font-family:sans-serif;max-width:480px;margin:60px auto;padding:24px;"
                    "border:1px solid #e6e9ee;border-radius:12px'>"
                    "<h2>Enter the Gmail you used for InboxTriage</h2>"
                    "<p style='color:#d9480f'>That doesn't look like a valid email.</p>"
                    "<a href='/activate'>← Back</a></div>")
        usage.mark_subscribed(usage.hash_gmail(gmail), sub_id)
        return (f"<div style='font-family:sans-serif;max-width:480px;margin:60px auto;padding:28px;"
                f"border:1px solid #137a4d;border-radius:12px;text-align:center'>"
                f"<h2 style='color:#137a4d'>✅ Activated</h2>"
                f"<p style='color:#5b6672;margin:14px 0'>Thanks! <b>{gmail}</b> is now on the $12/month plan "
                f"with unlimited daily scans. Go run your inbox.</p>"
                f"<a href='/' style='display:inline-block;background:#1f6feb;color:#fff;padding:11px 22px;"
                f"border-radius:10px;font-weight:700;text-decoration:none'>Open InboxTriage →</a></div>")
    sub = request.args.get("sub", "")
    sub_note = (f"<p style='color:#137a4d;font-size:13px;margin-bottom:14px'>"
                f"Payment received (sub ID: <code>{sub}</code>). Enter your Gmail below to unlock.</p>"
                ) if sub else ""
    return (f"<div style='font-family:sans-serif;max-width:480px;margin:60px auto;padding:28px;"
            f"border:1px solid #e6e9ee;border-radius:12px'>"
            f"<h2>Activate your subscription</h2>"
            f"{sub_note}"
            f"<p style='color:#5b6672;font-size:14px;margin:10px 0 18px'>Enter the Gmail address you use with "
            f"InboxTriage. We don't store your email in plain text — just a hash to link your plan.</p>"
            f"<form method='POST' action='/activate'>"
            f"<input type='hidden' name='sub_id' value='{sub}'>"
            f"<input type='email' name='gmail' placeholder='you@gmail.com' required "
            f"style='width:100%;padding:12px 14px;border:1px solid #cdd3da;border-radius:9px;"
            f"font-size:14.5px;margin-bottom:14px'>"
            f"<button type='submit' style='width:100%;padding:12px;border:0;border-radius:10px;"
            f"background:#137a4d;color:#fff;font-weight:700;font-size:15px;cursor:pointer'>Activate</button>"
            f"</form><a href='/' style='display:inline-block;margin-top:16px;color:#1f6feb'>← Back</a></div>")


# ---------------------------------------------------------------- 后台统计（需密码）
ADMIN_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>InboxTriage Admin</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:#0e1116;
color:#e6edf3;padding:28px 16px}.wrap{max-width:880px;margin:0 auto}h1{font-size:22px;margin-bottom:4px}
.sub{color:#8b949e;font-size:13px;margin-bottom:20px}.cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:22px}
.c{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px 20px;flex:1;min-width:140px}
.c b{display:block;font-size:26px}.c span{font-size:11.5px;color:#8b949e;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:11px 14px;font-size:13px;border-bottom:1px solid #21262d}
th{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.code{font-family:ui-monospace,Menlo,monospace;color:#79c0ff}
.warn{background:#fdeee6;border:1px solid #f0c9b8;color:#9a3412;padding:10px 14px;border-radius:9px;
font-size:12.5px;margin-bottom:18px}a{color:#79c0ff}.logout{float:right;font-size:13px}</style></head>
<body><div class="wrap"><a class="logout" href="/admin?logout=1">Log out</a>
<h1>InboxTriage — usage</h1>
<div class="sub">Auto-refreshes every 60s · data resets on redeploy (ephemeral disk)</div>
__WARN__
<div class="cards">
<div class="c"><b>__TOTAL__</b><span>Total runs</span></div>
<div class="c"><b>__USERS__</b><span>Unique users (by Gmail)</span></div>
<div class="c"><b>__SUB__</b><span>Subscribed</span></div>
<div class="c"><b>__TRIAL__</b><span>In trial (7d free)</span></div>
<div class="c"><b>__EXP__</b><span>Trial expired, not paid</span></div>
<div class="c"><b>__TODAY__</b><span>Runs today</span></div>
</div>
<table><tr><th>User (hash)</th><th>Time (UTC)</th><th>Emails</th></tr>__ROWS__</table>
</div><script>setTimeout(function(){location.reload()},60000)</script></body></html>"""


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.args.get("logout"):
        session.pop("admin", None)
        return redirect("/admin")
    if request.method == "POST":
        pw = request.form.get("pw", "")
        if pw == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")
        return ("<div style='font-family:sans-serif;max-width:380px;margin:80px auto;padding:24px;"
                "border:1px solid #e6e9ee;border-radius:12px;text-align:center'>"
                "<h2>Wrong password</h2><a href='/admin'>← Try again</a></div>")
    if not session.get("admin"):
        return ("<div style='font-family:sans-serif;max-width:380px;margin:80px auto;padding:28px;"
                "border:1px solid #e6e9ee;border-radius:12px'>"
                "<h2>InboxTriage Admin</h2><p style='color:#5b6672;font-size:14px;margin:12px 0'>Enter admin password.</p>"
                "<form method='POST' action='/admin'>"
                "<input type='password' name='pw' placeholder='password' required "
                "style='width:100%;padding:11px 13px;border:1px solid #cdd3da;border-radius:9px;margin-bottom:12px'>"
                "<button type='submit' style='width:100%;padding:11px;border:0;border-radius:10px;background:#1f6feb;"
                "color:#fff;font-weight:700;cursor:pointer'>Login</button></form></div>")
    s = usage.stats()
    warn = ('<div class="warn"><b>Security:</b> default admin password is set. Change <code>ADMIN_PASSWORD</code> '
            'in Render env before sharing this URL.</div>') if ADMIN_PASSWORD == "inboxadmin" else ""
    rows = "".join(
        f"<tr><td class='code'>{r['hash']}</td><td>{datetime.utcfromtimestamp(r['ts']).strftime('%Y-%m-%d %H:%M')}</td>"
        f"<td>{r['emails']}</td></tr>" for r in s["recent"]) or "<tr><td colspan=3>no runs yet</td></tr>"
    page = (ADMIN_PAGE.replace("__WARN__", warn).replace("__TOTAL__", str(s["total_runs"]))
            .replace("__USERS__", str(s["unique_users"])).replace("__SUB__", str(s["subscribed"]))
            .replace("__TRIAL__", str(s["trial_active"])).replace("__EXP__", str(s["expired"]))
            .replace("__TODAY__", str(s["runs_today"])).replace("__ROWS__", rows))
    return page


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
