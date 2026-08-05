"""
把分析结果渲染成一份可直接发给客户的 HTML 日报。
自包含单文件，双击即可打开，草稿一键复制。
"""
import html
from datetime import datetime

CAT_META = {
    "high_risk": ("HIGH RISK", "#d9480f", "#fdeee6", "Read these yourself. No drafts generated."),
    "lead":      ("LEADS",     "#1f6feb", "#eaf1fe", "Money on the table. Answer while they're warm."),
    "customer":  ("CUSTOMERS", "#137a4d", "#e6f4ec", "Someone is waiting. Draft attached to each."),
    "spam":      ("SPAM / PROMO", "#5b6672", "#eceff3", "Filed. Nothing here needs you."),
}
ORDER = ["high_risk", "lead", "customer", "spam"]


def _esc(s):
    return html.escape(str(s or ""))


def build(results, owner_email, generated_at=None):
    """results: [{mail:..., ai:...}, ...]"""
    generated_at = generated_at or datetime.now()
    buckets = {k: [] for k in ORDER}
    tasks = []

    for item in results:
        cat = item["ai"].get("category", "customer")
        buckets.setdefault(cat, []).append(item)
        for t in item["ai"].get("tasks", []):
            tasks.append({
                "title": t["title"],
                "due": t.get("due_date", ""),
                "from": item["mail"]["subject"],
            })

    tasks.sort(key=lambda t: (t["due"] == "", t["due"]))
    total = len(results)
    need_action = len(buckets["high_risk"]) + len(buckets["lead"]) + len(buckets["customer"])
    ignored = len(buckets["spam"])

    # ---------- 任务清单 ----------
    if tasks:
        rows = "".join(
            f'<li>'
            f'<div class="task-main">'
            f'<span class="due">{_esc(t["due"] or "no date")}</span>'
            f'<span class="tt">{_esc(t["title"])}</span>'
            f'</div>'
            f'<div class="task-src">📩 from <b>{_esc(t["from"][:60])}</b></div>'
            f'</li>'
            for t in tasks
        )
        tasks_html = f'<div class="panel"><h2>Tasks pulled out of your inbox</h2><ul class="tasks">{rows}</ul></div>'
    else:
        tasks_html = '<div class="panel"><h2>Tasks pulled out of your inbox</h2><p class="empty">No commitments or deadlines found today.</p></div>'

    # ---------- 分类区块 ----------
    sections = []
    for cat in ORDER:
        items = buckets.get(cat) or []
        if not items:
            continue
        label, color, bg, note = CAT_META[cat]
        items.sort(key=lambda x: -x["ai"].get("urgency", 3))

        cards = []
        for it in items:
            m, a = it["mail"], it["ai"]
            draft = a.get("reply_draft", "").strip()
            if draft:
                draft_block = (
                    '<div class="draft">'
                    '<div class="draft-head"><span>Reply draft</span>'
                    '<button class="copy" onclick="cp(this)">Copy</button></div>'
                    f'<pre>{_esc(draft)}</pre></div>'
                )
            elif cat == "high_risk":
                draft_block = '<div class="nodraft">No draft — handle this personally.</div>'
            else:
                draft_block = ""

            cards.append(f"""
        <div class="card">
          <div class="card-top">
            <div class="sbj">{_esc(m['subject'])}</div>
            <div class="urg" title="urgency">{'●' * a.get('urgency', 3)}</div>
          </div>
          <div class="from">{_esc(m['sender'])}</div>
          <div class="sum">{_esc(a.get('summary', ''))}</div>
          {draft_block}
        </div>""")

        sections.append(f"""
    <div class="panel">
      <div class="sec-head">
        <span class="badge" style="background:{bg};color:{color}">{label}</span>
        <span class="count">{len(items)}</span>
        <span class="note">{note}</span>
      </div>
      {''.join(cards)}
    </div>""")

    # ---------- 阅读指引 ----------
    if need_action > 0:
        guide = (
            '<div class="guide">'
            '<div class="guide-icon">👆</div>'
            '<div><b>Start here.</b> '
            f'<span style="color:#d9480f">{buckets.get("high_risk", []) and len(buckets["high_risk"]) or 0}</span> urgent item(s) need your eyes now — '
            f'<span style="color:#137a4d">{len(buckets.get("customer", []))} customer(s)</span> waiting for reply, '
            f'<span style="color:#1f6feb">{len(buckets.get("lead", []))} lead(s)</span> worth money. '
            'Drafts have a <b>Copy</b> button — click, paste into Gmail, edit, send.<br>'
            '<span style="color:#5b6672;font-size:12.5px">Everything below "SPAM / PROMO" is safe to ignore.</span>'
            '</div></div>')
    else:
        guide = (
            '<div class="guide" style="border-color:#d0e8c5;background:#f2fcf0">'
            '<div class="guide-icon">✅</div>'
            '<div><b>All clear.</b> Nothing needs your attention today. '
            f'{ignored} email(s) filed as spam/promo — safe to ignore.</div></div>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InboxTriage — {generated_at.strftime('%b %d, %Y')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Helvetica,Arial,sans-serif;
background:#f6f8fa;color:#111418;line-height:1.55;padding:28px 16px}}
.wrap{{max-width:820px;margin:0 auto}}
.hdr{{margin-bottom:22px}}
.hdr h1{{font-size:24px;letter-spacing:-.02em}}
.hdr p{{color:#5b6672;font-size:14px;margin-top:4px}}
.stats{{display:flex;gap:10px;margin:18px 0 16px;flex-wrap:wrap}}
.stat{{background:#fff;border:1px solid #e6e9ee;border-radius:10px;padding:12px 18px;flex:1;min-width:120px}}
.stat b{{display:block;font-size:23px;letter-spacing:-.02em}}
.stat span{{font-size:12px;color:#5b6672;text-transform:uppercase;letter-spacing:.04em}}
.guide{{display:flex;gap:14px;align-items:flex-start;background:#fef9e7;
  border:1.5px solid #f0d85e;border-radius:11px;padding:15px 18px;margin-bottom:18px}}
.guide-icon{{font-size:26px;flex-shrink:0;line-height:1}}
.guide div{{font-size:14px;line-height:1.55}}
.panel{{background:#fff;border:1px solid #e6e9ee;border-radius:12px;padding:20px 22px;margin-bottom:18px}}
.panel h2{{font-size:16px;margin-bottom:12px}}
.sec-head{{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}}
.badge{{font-size:11px;font-weight:800;letter-spacing:.05em;padding:5px 10px;border-radius:6px}}
.count{{font-size:13px;font-weight:700;color:#111418}}
.note{{font-size:12.5px;color:#5b6672}}
.card{{border-top:1px solid #eef1f4;padding:15px 0}}
.card:first-of-type{{border-top:0;padding-top:0}}
.card-top{{display:flex;justify-content:space-between;gap:12px;align-items:baseline}}
.sbj{{font-size:15px;font-weight:650;letter-spacing:-.01em}}
.urg{{font-size:9px;color:#c3ccd6;letter-spacing:1px;white-space:nowrap}}
.from{{font-size:12.5px;color:#5b6672;margin-top:2px}}
.sum{{font-size:14px;margin-top:7px}}
.draft{{margin-top:11px;border:1px solid #e6e9ee;border-radius:9px;overflow:hidden}}
.draft-head{{display:flex;justify-content:space-between;align-items:center;
background:#f6f8fa;padding:7px 12px;font-size:11.5px;font-weight:700;color:#5b6672;
text-transform:uppercase;letter-spacing:.05em}}
.copy{{border:1px solid #d5dbe2;background:#fff;border-radius:6px;padding:3px 11px;
font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;color:#1f6feb}}
.copy:hover{{background:#eaf1fe}}
.draft pre{{padding:13px;font-family:inherit;font-size:13.5px;white-space:pre-wrap;
word-wrap:break-word;line-height:1.6}}
.nodraft{{margin-top:10px;font-size:13px;color:#d9480f;background:#fdeee6;
padding:8px 12px;border-radius:8px;font-weight:600}}
.tasks li{{list-style:none;padding:11px 14px;border-bottom:1px dashed #e6e9ee;font-size:14px}}
.tasks li:last-child{{border:0}}
.task-main{{display:flex;gap:12px;align-items:baseline}}
.due{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
background:#f6f8fa;border:1px solid #e6e9ee;padding:3px 8px;border-radius:5px;
white-space:nowrap;min-width:96px;text-align:center;flex-shrink:0}}
.tt{{flex:1;font-weight:600;line-height:1.5}}
.task-src{{font-size:12px;color:#5b6672;margin-top:4px;padding-left:114px}}
.empty{{color:#5b6672;font-size:14px}}
.ftr{{text-align:center;font-size:12px;color:#8a95a1;padding:22px 0}}
@media(max-width:600px){{.task-src{{padding-left:0}}}}
</style></head><body><div class="wrap">
<div class="hdr">
  <h1>Your inbox, triaged</h1>
  <p>{_esc(owner_email)} · {generated_at.strftime('%A, %B %d, %Y · %H:%M')}</p>
</div>
<div class="stats">
  <div class="stat"><b>{total}</b><span>Emails scanned</span></div>
  <div class="stat"><b>{need_action}</b><span>Need you</span></div>
  <div class="stat"><b>{ignored}</b><span>Safely ignored</span></div>
  <div class="stat"><b>{len(tasks)}</b><span>Tasks found</span></div>
</div>
{tasks_html}
{guide}
{''.join(sections)}
<div class="ftr">InboxTriage · read-only access · drafts are never sent automatically</div>
</div>
<script>
function cp(btn){{
  const t = btn.closest('.draft').querySelector('pre').innerText;
  navigator.clipboard.writeText(t).then(()=>{{
    btn.textContent='Copied'; setTimeout(()=>btn.textContent='Copy',1400);
  }});
}}
</script></body></html>"""
