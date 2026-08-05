"""
IMAP 只读拉取 Gmail。
核心安全点：select(readonly=True) —— 代码层面不可能发信、删信、改状态。
"""
import imaplib
import email
import re
from email.header import decode_header, make_header
from datetime import datetime, timedelta, timezone

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
MAX_BODY_CHARS = 4000  # 截断超长正文，省 token


def _decode(raw):
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return text


def _extract_body(msg) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                continue
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                chunk = payload.decode(charset, errors="replace")
            except Exception:
                chunk = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain" and not plain:
                plain = chunk
            elif ctype == "text/html" and not html:
                html = chunk
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        chunk = payload.decode(charset, errors="replace")
        if msg.get_content_type() == "text/html":
            html = chunk
        else:
            plain = chunk

    body = plain or _strip_html(html)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:MAX_BODY_CHARS]


def fetch_recent(gmail_address: str, app_password: str, days: int = 1, limit: int = 60):
    """
    返回 [{uid, subject, sender, sender_email, date, body}, ...]
    app_password: Google 生成的 16 位应用专用密码（空格可有可无）
    """
    pwd = app_password.replace(" ", "")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        M.login(gmail_address, pwd)
        # readonly=True —— 只读挂载，物理上无法修改邮箱
        M.select("INBOX", readonly=True)

        status, data = M.search(None, f'(SINCE "{since}")')
        if status != "OK":
            return []

        uids = data[0].split()
        uids = uids[-limit:]  # 只取最近 N 封

        results = []
        for uid in uids:
            status, msg_data = M.fetch(uid, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            sender_raw = _decode(msg.get("From"))
            m = re.search(r"<([^>]+)>", sender_raw)
            sender_email = m.group(1) if m else sender_raw

            results.append({
                "uid": uid.decode(),
                "subject": _decode(msg.get("Subject")) or "(no subject)",
                "sender": sender_raw,
                "sender_email": sender_email,
                "date": _decode(msg.get("Date")),
                "body": _extract_body(msg),
            })
        return results
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()
