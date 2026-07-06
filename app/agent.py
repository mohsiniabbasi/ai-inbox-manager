"""The triage agent: read one email -> classify, extract, draft, propose a CRM action.

Two backends behind one interface:
  * LLM (Anthropic Claude) when ANTHROPIC_API_KEY is set and use_llm=True —
    a single structured-JSON call does the classification, extraction and reply draft.
  * A deterministic rule-based engine otherwise, so the demo ALWAYS runs with
    zero keys and zero cost. The rules are transparent and good enough to show
    the full workflow end to end.

The agent NEVER sends anything or writes to the CRM itself. It only produces a
*recommendation*. A human approves (or edits, or rejects) in the console — that
human-in-the-loop step is the whole point.
"""
from __future__ import annotations

import json
import os
import re

INTENTS = ["sales_lead", "support", "billing", "complaint", "partnership", "recruitment", "spam", "other"]

# ── Rule-based backend ──────────────────────────────────────────────────────
_KEYWORDS = {
    "billing":     ["charged", "charge", "refund", "invoice", "billed", "payment", "double", "overcharged"],
    "complaint":   ["frustrated", "disappointed", "cancel", "cancelling", "unhappy", "wrong", "missed", "angry", "poor"],
    "partnership": ["reseller", "partner", "white-label", "white label", "affiliate", "collaborat", "wholesale"],
    "recruitment": ["cv", "resume", "application", "applying", "apply", "hiring", "role", "vacancy", "job"],
    "spam":        ["won", "winner", "prize", "gift card", "backlinks", "unsubscribe", "limited time", "act now", "claim"],
    "support":     ["down", "error", "not working", "broken", "how do i", "change", "update", "reset", "help", "issue", "bug"],
    "sales_lead":  ["pricing", "price", "quote", "plan", "sign up", "signup", "integrate", "demo", "interested", "cost", "trial"],
}
_URGENT = ["urgent", "asap", "immediately", "down", "can't", "cannot", "losing", "costing", "emergency", "now"]
_NEG = ["frustrated", "disappointed", "cancel", "angry", "unhappy", "wrong", "poor", "costing", "missed"]
_POS = ["keen", "love", "great", "interested", "excited", "happy", "thanks", "thank you"]


def _score_intent(text: str) -> tuple[str, float]:
    t = text.lower()
    scores = {intent: sum(1 for kw in kws if kw in t) for intent, kws in _KEYWORDS.items()}
    best = max(scores, key=scores.get)
    hits = scores[best]
    if hits == 0:
        return "other", 0.45
    # spam and billing are high-signal; sales/support need a touch more care
    conf = min(0.95, 0.55 + 0.15 * hits)
    return best, round(conf, 2)


def _urgency(text: str, intent: str) -> str:
    t = text.lower()
    # things we never action get low urgency regardless of urgent-sounding words
    if intent in ("spam", "recruitment"):
        return "low"
    # whole-word match so "now" doesn't fire inside "know", "down" inside "download", etc.
    urgent = any(re.search(rf"\b{re.escape(w)}\b", t) for w in _URGENT)
    if intent == "complaint" or urgent:
        return "high"
    return "medium"


def _sentiment(text: str) -> str:
    t = text.lower()
    neg = sum(1 for w in _NEG if w in t)
    pos = sum(1 for w in _POS if w in t)
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def _company_from_email(addr: str) -> str:
    m = re.search(r"@([^.]+)\.", addr or "")
    if not m:
        return ""
    raw = m.group(1)
    if raw.lower() in ("gmail", "outlook", "hotmail", "yahoo", "icloud"):
        return ""
    return raw.replace("-", " ").title()


def _draft_reply(email: dict, intent: str) -> str:
    name = (email.get("from_name") or "there").split()[0]
    templates = {
        "sales_lead": (
            f"Hi {name},\n\nThanks for your interest — happy to help. I've noted the "
            "details you mentioned and can put together the right pricing for you. "
            "Would a short call this week suit? I'll follow up with times.\n\nBest,\nPivot Bureau"
        ),
        "support": (
            f"Hi {name},\n\nThanks for flagging this — I'm on it. I've logged the issue "
            "and will update you shortly with a fix or next steps. If it's blocking you "
            "right now, let me know and I'll prioritise it.\n\nBest,\nPivot Bureau"
        ),
        "billing": (
            f"Hi {name},\n\nApologies for the mix-up — I can see what you mean and I'm "
            "raising the correction now. I'll confirm as soon as it's processed and make "
            "sure it doesn't recur.\n\nBest,\nPivot Bureau"
        ),
        "complaint": (
            f"Hi {name},\n\nI'm sorry — that's not the experience we want you to have, and "
            "I completely understand the frustration. I'm looking into what went wrong "
            "personally and will come back to you today with how we'll put it right.\n\nBest,\nPivot Bureau"
        ),
        "partnership": (
            f"Hi {name},\n\nThanks for reaching out — a partnership sounds well worth "
            "exploring. I'd love to understand your clients' needs; could we find 20 "
            "minutes this week? I'll send some times over.\n\nBest,\nPivot Bureau"
        ),
        "recruitment": (
            f"Hi {name},\n\nThank you for your interest and for sending this across. I've "
            "passed it to the right person; we'll be in touch if there's a fit. Wishing "
            "you the best.\n\nBest,\nPivot Bureau"
        ),
        "spam": "",
        "other": (
            f"Hi {name},\n\nThanks for getting in touch — could you share a little more "
            "detail so I can point you to the right person? Happy to help.\n\nBest,\nPivot Bureau"
        ),
    }
    return templates.get(intent, templates["other"])


def _crm_action(email: dict, intent: str, urgency: str) -> dict | None:
    """What we'd write to the CRM on approval. None = nothing to write (e.g. spam)."""
    name = email.get("from_name") or ""
    company = _company_from_email(email.get("from_email", ""))
    base_contact = {
        "name": name, "email": email.get("from_email", ""), "company": company,
    }
    if intent == "spam":
        return None
    if intent == "recruitment":
        return None
    if intent in ("sales_lead", "partnership"):
        return {
            "object": "deal", "operation": "create",
            "fields": {
                **base_contact,
                "stage": "New lead",
                "type": "Partnership" if intent == "partnership" else "New business",
                "priority": urgency,
                "summary": email.get("subject", ""),
            },
        }
    if intent in ("support", "billing", "complaint"):
        return {
            "object": "ticket", "operation": "create",
            "fields": {
                **base_contact,
                "status": "Open",
                "category": intent,
                "priority": urgency,
                "summary": email.get("subject", ""),
            },
        }
    return {"object": "contact", "operation": "create", "fields": base_contact}


def _rule_based(email: dict) -> dict:
    text = f"{email.get('subject','')} {email.get('body','')}"
    intent, conf = _score_intent(text)
    urgency = _urgency(text, intent)
    action = _crm_action(email, intent, urgency)
    return {
        "intent": intent,
        "urgency": urgency,
        "sentiment": _sentiment(text),
        "confidence": conf,
        "extracted": {
            "name": email.get("from_name", ""),
            "email": email.get("from_email", ""),
            "company": _company_from_email(email.get("from_email", "")),
            "topic": email.get("subject", ""),
        },
        "draft_reply": _draft_reply(email, intent),
        "crm_action": action,
        "engine": "rules",
    }


# ── LLM backend (optional) ──────────────────────────────────────────────────
_SYS = (
    "You are an inbox-triage agent for a UK small-business software company. "
    "Given one customer email, classify and extract structured data and draft a "
    "short, warm, professional reply (British English). Respond with ONLY a JSON "
    "object, no prose. Schema:\n"
    '{"intent": one of ["sales_lead","support","billing","complaint","partnership","recruitment","spam","other"],'
    ' "urgency": "low"|"medium"|"high", "sentiment": "positive"|"neutral"|"negative",'
    ' "confidence": 0..1, "extracted": {"name":str,"email":str,"company":str,"topic":str},'
    ' "draft_reply": str (empty string if spam),'
    ' "crm_action": null OR {"object":"deal"|"ticket"|"contact","operation":"create"|"update","fields":{...}}}'
)


def _llm(email: dict) -> dict:
    import anthropic  # imported lazily so the demo runs without the dep
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user = (
        f"From: {email.get('from_name')} <{email.get('from_email')}>\n"
        f"Subject: {email.get('subject')}\n\n{email.get('body')}"
    )
    model = os.environ.get("INBOX_MODEL", "claude-haiku-4-5-20251001")
    msg = client.messages.create(
        model=model, max_tokens=700, system=_SYS,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    data["engine"] = f"llm:{model}"
    # backfill anything the model omitted, so the UI never breaks
    fallback = _rule_based(email)
    for k in ("intent", "urgency", "sentiment", "confidence", "extracted", "draft_reply", "crm_action"):
        data.setdefault(k, fallback[k])
    return data


def analyze(email: dict, use_llm: bool | None = None) -> dict:
    """Return the triage recommendation for one email.

    Uses Claude when ANTHROPIC_API_KEY is present (and use_llm isn't False),
    otherwise the rule-based engine. Any LLM error falls back to rules so the
    demo can't break in front of a client.
    """
    want_llm = (use_llm is not False) and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if want_llm:
        try:
            return _llm(email)
        except Exception:  # noqa: BLE001 — never let the demo hard-fail
            pass
    return _rule_based(email)
