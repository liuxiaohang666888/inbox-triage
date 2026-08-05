"""
AI 分析器 —— 支持多引擎，config.json / 环境变量里 "provider" 字段切换。

  "provider": "deepseek"  -> DeepSeek（付费，极便宜，约 ¥0.006/封）
  "provider": "gemini"    -> Google Gemini 2.0 Flash（免费 1500 次/天）
  "provider": "zhipu"     -> 智谱 GLM-4-Flash（国内，用户自带 900 万额度，OpenAI 兼容）

一次调用同时产出：分类 + 紧急度 + 摘要 + 回复草稿 + 待办事项。
只依赖 requests，不装任何 SDK。
"""
import json
import re
import time
import requests

# ---------------------------------------------------------------- 引擎配置
PROVIDERS = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "model": "gemini-2.0-flash",
    },
    "zhipu": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
    },
}

SYSTEM_RULES = """You are InboxTriage, an email triage engine for a solo online seller / freelancer.

You will receive ONE email. Return ONE JSON object. No markdown, no code fences, no commentary.

Schema:
{
  "category": "spam" | "customer" | "lead" | "high_risk",
  "urgency": 1-5,
  "summary": "one sentence, max 18 words, what this email actually wants",
  "reply_draft": "" or a complete ready-to-send reply,
  "tasks": [ { "title": "imperative task, max 10 words", "due_date": "YYYY-MM-DD" or "" } ]
}

CATEGORY RULES:
- "spam"      = newsletters, marketing blasts, cold outreach, platform promos, notifications nobody must answer.
- "customer"  = an existing buyer asking something: order status, shipping, sizing, returns, how-to.
- "lead"      = potential money: wholesale, bulk order, collaboration, custom quote, partnership, press.
- "high_risk" = chargeback, PayPal/Stripe dispute, refund demand, legal threat, contract terms,
                copyright/IP claim, account suspension, anything about money going wrong.

REPLY DRAFT RULES:
- category "customer" or "lead"  -> write a full reply draft.
- category "spam"                -> reply_draft MUST be "".
- category "high_risk"           -> reply_draft MUST be "". Never draft answers to disputes or legal matters.
- Tone: warm, direct, professional, first person singular, no corporate filler.
- Length: 40-110 words. Plain text. No subject line. No "Dear Sir/Madam".
- Start with a greeting using the sender's first name if you can infer it, else "Hi there,".
- End with a line break then "Best," on its own line. Do NOT invent a signature name.
- If a fact is unknown (tracking number, exact date, price), write it as [bracketed placeholder]
  so the human fills it in. Never invent order numbers, prices, or dates.

TASK RULES:
- Extract only real commitments, deadlines and promises: ship by X, follow up on X, send quote by X,
  respond before deadline X, deliver X.
- No tasks from spam. Return [] if nothing concrete.
- due_date: resolve relative dates ("next Tuesday", "in 3 days") against TODAY given below. If truly unknown, "".
- Max 3 tasks per email.

Return raw JSON only."""


# ---------------------------------------------------------------- 工具
def _extract_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _fallback(reason: str):
    return {
        "category": "customer",
        "urgency": 3,
        "summary": f"[AI unavailable: {reason}] please read manually",
        "reply_draft": "",
        "tasks": [],
        "_error": reason,
    }


def _build_prompt(mail, today, owner_context):
    return f"""TODAY IS: {today}
ABOUT THE INBOX OWNER: {owner_context or "A solo online seller running their own small shop."}

--- EMAIL START ---
From: {mail['sender']}
Date: {mail['date']}
Subject: {mail['subject']}

{mail['body']}
--- EMAIL END ---"""


# ---------------------------------------------------------------- 两个引擎的实际请求
def _call_deepseek(prompt, api_key, cfg):
    r = requests.post(
        cfg["url"],
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_RULES},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:180]}"
    return r.json()["choices"][0]["message"]["content"], None


def _call_gemini(prompt, api_key, cfg):
    url = cfg["url"].format(model=cfg["model"])
    r = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": SYSTEM_RULES + "\n\n" + prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 900,
                "responseMimeType": "application/json",
            },
        },
        timeout=90,
    )
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:180]}"
    return r.json()["candidates"][0]["content"]["parts"][0]["text"], None


# 智谱 GLM 走 OpenAI 兼容接口，请求体与 DeepSeek 完全一致
def _call_zhipu(prompt, api_key, cfg):
    return _call_deepseek(prompt, api_key, cfg)


CALLERS = {"deepseek": _call_deepseek, "gemini": _call_gemini, "zhipu": _call_zhipu}


# ---------------------------------------------------------------- 主入口
def analyse(mail, api_key, today, owner_context="", provider="deepseek", retries=3):
    provider = (provider or "deepseek").lower()
    if provider not in PROVIDERS:
        return _fallback(f"unknown provider '{provider}'")

    cfg = PROVIDERS[provider]
    caller = CALLERS[provider]
    prompt = _build_prompt(mail, today, owner_context)

    last_err = "unknown"
    for attempt in range(retries):
        try:
            raw, err = caller(prompt, api_key, cfg)
            if err:
                last_err = err
                # 限流 / 服务器忙 -> 退避重试
                if "429" in err or "503" in err or "502" in err:
                    time.sleep(8 * (attempt + 1))
                else:
                    time.sleep(2)
                continue

            data = _extract_json(raw)
            if not data:
                last_err = "unparseable response"
                time.sleep(1)
                continue

            # ---- 规范化 + 强制业务铁律 ----
            cat = str(data.get("category", "customer")).lower().strip()
            if cat not in ("spam", "customer", "lead", "high_risk"):
                cat = "customer"
            data["category"] = cat

            # 铁律：垃圾邮件和高危邮件，AI 想写草稿也写不出来
            if cat in ("spam", "high_risk"):
                data["reply_draft"] = ""
            if cat == "spam":
                data["tasks"] = []

            try:
                data["urgency"] = max(1, min(5, int(data.get("urgency", 3))))
            except Exception:
                data["urgency"] = 3

            clean = []
            for t in (data.get("tasks") or [])[:3]:
                if isinstance(t, dict) and t.get("title"):
                    due = str(t.get("due_date") or "")
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                        due = ""
                    clean.append({"title": str(t["title"])[:120], "due_date": due})
            data["tasks"] = clean

            data["summary"] = str(data.get("summary", ""))[:200]
            data["reply_draft"] = str(data.get("reply_draft", "")).strip()
            return data

        except Exception as e:
            last_err = str(e)[:180]
            time.sleep(2)

    return _fallback(last_err)
