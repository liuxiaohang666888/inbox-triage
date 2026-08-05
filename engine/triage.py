"""
InboxTriage 主程序。

用法：
    python triage.py              # 处理 config.json 里所有客户
    python triage.py --demo       # 用内置假邮件跑一遍，不连任何邮箱、不用 API key
    python triage.py --days 3     # 拉最近 3 天
    python triage.py --all        # 忽略去重记录，重新处理所有邮件

产出：out/<邮箱>_<日期>.html
"""
import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailbox as mbx
import ai as brain
import report as rpt
import store

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
OUT = os.path.join(HERE, "out")


def log(msg):
    print(f"  {msg}", flush=True)


def run_account(acc, api_key, provider, days, ignore_seen):
    addr = acc["gmail_address"]
    print(f"\n[{addr}]")
    log("connecting to Gmail (read-only)...")

    try:
        mails = mbx.fetch_recent(addr, acc["app_password"], days=days,
                                 limit=acc.get("max_emails", 60))
    except Exception as e:
        log(f"FAILED to connect: {e}")
        log("check: 2-Step Verification on? app password correct? IMAP enabled in Gmail settings?")
        return None

    log(f"fetched {len(mails)} emails from the last {days} day(s)")
    if not mails:
        return None

    seen = set() if ignore_seen else store.seen_uids(addr)
    todo = [m for m in mails if m["uid"] not in seen]
    if len(todo) < len(mails):
        log(f"{len(mails) - len(todo)} already processed, skipping")
    if not todo:
        log("nothing new")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    ctx = acc.get("owner_context", "")
    results = []

    for i, m in enumerate(todo, 1):
        print(f"  [{i}/{len(todo)}] {m['subject'][:58]}", flush=True)
        a = brain.analyse(m, api_key, today, ctx, provider=provider)
        if a.get("_error"):
            log(f"    ! {a['_error']}")
        results.append({"mail": m, "ai": a})
        store.save(addr, m, a)

    os.makedirs(OUT, exist_ok=True)
    fname = f"{addr.split('@')[0]}_{datetime.now().strftime('%Y-%m-%d')}.html"
    path = os.path.join(OUT, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(rpt.build(results, addr))
    log(f"report -> {path}")
    return path


DEMO_MAILS = [
    {"uid": "d1", "subject": "Re: Order #4821 - received the wrong size",
     "sender": "Megan Ellis <megan.ellis@gmail.com>", "sender_email": "megan.ellis@gmail.com",
     "date": "Fri, 31 Jul 2026 09:12:00 +0000",
     "body": "Hi, I got my order yesterday but it's a medium and I ordered a large. "
             "I need it for a wedding on August 15th. Can you send the right one? "
             "Do I have to pay return shipping?"},
    {"uid": "d2", "subject": "Wholesale inquiry - 200 units for our store",
     "sender": "Daniel Okafor <daniel@northsidegoods.com>", "sender_email": "daniel@northsidegoods.com",
     "date": "Fri, 31 Jul 2026 08:40:00 +0000",
     "body": "Hello, we run three retail locations in Portland and would like to carry your product. "
             "Looking at roughly 200 units to start. What's your wholesale pricing and lead time? "
             "We'd need a quote by next Wednesday to present at our buying meeting."},
    {"uid": "d3", "subject": "A dispute has been opened on transaction 9F2K1183",
     "sender": "PayPal <service@paypal.com>", "sender_email": "service@paypal.com",
     "date": "Fri, 31 Jul 2026 07:05:00 +0000",
     "body": "A buyer has opened a dispute for $148.00 claiming the item was not as described. "
             "You must respond with tracking information or evidence by August 7, 2026, "
             "or the case will be resolved in the buyer's favor."},
    {"uid": "d4", "subject": "Boost your Etsy sales 10x with our AI tool!!",
     "sender": "Growth Hackers <no-reply@growthblast.io>", "sender_email": "no-reply@growthblast.io",
     "date": "Fri, 31 Jul 2026 06:00:00 +0000",
     "body": "Limited time offer! Our AI listing optimizer has helped 12,000 sellers triple revenue. "
             "Click here for 70% off. Unsubscribe at the bottom."},
    {"uid": "d5", "subject": "Question before I buy - does it ship to Canada?",
     "sender": "Priya Raman <priya.r88@outlook.com>", "sender_email": "priya.r88@outlook.com",
     "date": "Fri, 31 Jul 2026 05:20:00 +0000",
     "body": "Hi there! Love your shop. Before I order - do you ship to Toronto, and roughly how long "
             "does it take? Also is there duty on top?"},
    {"uid": "d6", "subject": "Confirming delivery for next Tuesday",
     "sender": "Tom Baker <tom@bakerstudio.co.uk>", "sender_email": "tom@bakerstudio.co.uk",
     "date": "Fri, 31 Jul 2026 04:10:00 +0000",
     "body": "Just confirming you'll have the 12 custom pieces ready to ship next Tuesday as agreed. "
             "Let me know if anything slips - our launch is the following Monday."},
]

DEMO_AI = [
    {"category": "customer", "urgency": 4,
     "summary": "Wrong size delivered, needs correct item before August 15 wedding.",
     "reply_draft": "Hi Megan,\n\nI'm really sorry about the mix-up on order #4821 — that's on me. "
                    "I'm shipping the large out today and you'll have it well before the 15th.\n\n"
                    "You don't pay a cent for the return. I'm emailing you a prepaid label separately — "
                    "just drop the medium in any post box whenever it's convenient. No rush.\n\n"
                    "Your new tracking number is [tracking number].\n\nBest,",
     "tasks": [{"title": "Ship large replacement for order #4821", "due_date": "2026-08-01"},
               {"title": "Email prepaid return label to Megan", "due_date": "2026-07-31"}]},
    {"category": "lead", "urgency": 5,
     "summary": "Portland retailer wants 200-unit wholesale quote before Wednesday meeting.",
     "reply_draft": "Hi Daniel,\n\nThree locations in Portland — that's a great fit, thanks for reaching out.\n\n"
                    "For 200 units my wholesale price is [price per unit], which is [X]% off retail. "
                    "Lead time on that quantity is [X] weeks from deposit. I can hold that pricing for 30 days.\n\n"
                    "I'll have a formal quote in your inbox by Tuesday so you've got it ahead of the "
                    "buying meeting. Anything specific your buyers will want to see — margins, "
                    "display options, sample pack?\n\nBest,",
     "tasks": [{"title": "Send formal wholesale quote to Daniel", "due_date": "2026-08-04"}]},
    {"category": "high_risk", "urgency": 5,
     "summary": "PayPal dispute for $148, evidence required by August 7 or you lose.",
     "reply_draft": "",
     "tasks": [{"title": "Submit tracking evidence for PayPal dispute", "due_date": "2026-08-07"}]},
    {"category": "spam", "urgency": 1,
     "summary": "Marketing blast selling an Etsy optimization tool.",
     "reply_draft": "", "tasks": []},
    {"category": "lead", "urgency": 3,
     "summary": "Pre-purchase question about Canada shipping time and duties.",
     "reply_draft": "Hi Priya,\n\nThank you — and yes, I ship to Toronto regularly.\n\n"
                    "Delivery usually runs [X-X] business days once it's dispatched. Duty is handled "
                    "at the border by Canada Post; on an order this size it's typically small or "
                    "nothing at all, but I can't guarantee it since it's out of my hands.\n\n"
                    "Anything you'd like to know about sizing or materials before you order? "
                    "Happy to help.\n\nBest,",
     "tasks": []},
    {"category": "customer", "urgency": 4,
     "summary": "Client confirming 12 custom pieces ship Tuesday ahead of Monday launch.",
     "reply_draft": "Hi Tom,\n\nConfirmed — all 12 pieces go out Tuesday as agreed, which puts them "
                    "with you comfortably before your Monday launch.\n\nI'll send tracking the moment "
                    "they're collected. If anything at all changes on my end you'll hear from me "
                    "immediately rather than at the last minute.\n\nBest,",
     "tasks": [{"title": "Ship 12 custom pieces to Tom Baker", "due_date": "2026-08-04"}]},
]


def run_demo():
    print("\n[DEMO MODE] no mailbox, no API key — showing what the output looks like")
    results = [{"mail": m, "ai": a} for m, a in zip(DEMO_MAILS, DEMO_AI)]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "demo_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(rpt.build(results, "seller@yourshop.com"))
    print(f"  report -> {path}")
    return path


def test_ai(open_after=False):
    """用真实 AI 跑 3 封样本邮件，不连任何邮箱。验证 key 和输出质量。"""
    if not os.path.exists(CONFIG):
        print("config.json not found — copy config.example.json and fill in api_key")
        sys.exit(1)
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    provider = (cfg.get("provider") or "deepseek").lower()
    api_key = (os.environ.get("GEMINI_API_KEY" if provider == "gemini" else "DEEPSEEK_API_KEY", "")
               or cfg.get("api_key") or "").strip()
    today = datetime.now().strftime("%Y-%m-%d")
    ctx = "Runs a small Etsy shop selling handmade leather goods, ships worldwide."

    sample = [DEMO_MAILS[0], DEMO_MAILS[1], DEMO_MAILS[2]]
    print(f"\n[AI TEST] engine={provider} · {len(sample)} sample emails\n")

    results = []
    for i, m in enumerate(sample, 1):
        print(f"  [{i}/{len(sample)}] {m['subject'][:56]}", flush=True)
        a = brain.analyse(m, api_key, today, ctx, provider=provider)
        if a.get("_error"):
            print(f"      FAILED: {a['_error']}")
        else:
            print(f"      -> {a['category']} | urgency {a['urgency']} | "
                  f"{len(a['tasks'])} task(s) | draft {len(a['reply_draft'])} chars")
        results.append({"mail": m, "ai": a})

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "ai_test.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(rpt.build(results, "ai-test"))
    print(f"\n  report -> {path}")
    if open_after:
        webbrowser.open("file://" + path.replace("\\", "/"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="run with fake emails, no config needed")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--all", action="store_true", help="ignore dedupe, reprocess everything")
    p.add_argument("--open", action="store_true", help="open report in browser when done")
    p.add_argument("--testai", action="store_true",
                   help="run the real AI on 3 sample emails, no mailbox needed")
    args = p.parse_args()

    if args.testai:
        test_ai(args.open)
        return

    if args.demo:
        path = run_demo()
        if args.open:
            webbrowser.open("file://" + path.replace("\\", "/"))
        return

    if not os.path.exists(CONFIG):
        print("config.json not found.")
        print("copy config.example.json to config.json and fill it in.")
        sys.exit(1)

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    provider = (cfg.get("provider") or "deepseek").lower()
    api_key = (os.environ.get("GEMINI_API_KEY" if provider == "gemini" else "DEEPSEEK_API_KEY", "")
               or cfg.get("api_key") or "").strip()
    if not api_key or api_key.startswith("PASTE"):
        print("api_key missing — set GEMINI_API_KEY / DEEPSEEK_API_KEY env var, or fill config.json")
        print("  deepseek -> https://platform.deepseek.com")
        print("  gemini   -> https://aistudio.google.com (free)")
        sys.exit(1)

    accounts = cfg.get("accounts", [])
    if not accounts:
        print("no accounts in config.json")
        sys.exit(1)

    print(f"InboxTriage · engine={provider} · {len(accounts)} account(s) · last {args.days} day(s)")
    last = None
    for acc in accounts:
        r = run_account(acc, api_key, provider, args.days, args.all)
        last = r or last

    print("\ndone.")
    if last and args.open:
        webbrowser.open("file://" + last.replace("\\", "/"))


if __name__ == "__main__":
    main()
