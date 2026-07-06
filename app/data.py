"""Synthetic shared inbox + in-memory state for the AI Inbox Manager demo.

Everything here is fabricated sample data — no real people, no real mailbox.
The demo ships a realistic support+sales inbox so the AI triage, the human
approval queue, the CRM writes and the audit log all have something to act on.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

# ── The synthetic inbox ────────────────────────────────────────────────────
# A spread of the message types a small UK business actually receives:
# hot lead, outage, billing dispute, churn risk, partnership, spam, FAQ, etc.
_SEED_EMAILS: list[dict] = [
    {
        "id": "E-1001",
        "from_name": "Rachel Okafor",
        "from_email": "rachel@brightsmiledental.co.uk",
        "subject": "Pricing for 3 locations?",
        "received": "2026-07-06T08:12:00Z",
        "body": (
            "Hi, we run three dental practices in Leeds and are looking at your "
            "Growth plan to handle bookings and reminders across all of them. "
            "Could you send pricing for 3 locations and let me know if we can "
            "get on a call this week? Keen to move quickly."
        ),
    },
    {
        "id": "E-1002",
        "from_name": "Tom Beckett",
        "from_email": "tom@beckettplumbing.co.uk",
        "subject": "URGENT: booking page is down",
        "received": "2026-07-06T08:31:00Z",
        "body": (
            "Your booking widget on our site has been throwing an error all "
            "morning and customers can't book. This is costing us jobs. Please "
            "fix ASAP or call me on 07700 900412."
        ),
    },
    {
        "id": "E-1003",
        "from_name": "Priya Shah",
        "from_email": "priya@shahaccountants.com",
        "subject": "Charged twice this month",
        "received": "2026-07-06T09:02:00Z",
        "body": (
            "I've just noticed two charges of £149 on my card for this month's "
            "subscription. I should only be billed once. Please refund the "
            "duplicate and confirm it won't happen again."
        ),
    },
    {
        "id": "E-1004",
        "from_name": "Unclaimed Rewards",
        "from_email": "winner@prize-claim-now.info",
        "subject": "Congratulations!!! You have WON",
        "received": "2026-07-06T09:15:00Z",
        "body": (
            "Dear user, you have been selected to receive a $1,000 gift card. "
            "Click here to claim your reward now before it expires!!!"
        ),
    },
    {
        "id": "E-1005",
        "from_name": "Daniel Foss",
        "from_email": "dan@fosslettings.co.uk",
        "subject": "Do you integrate with Calendly?",
        "received": "2026-07-06T09:40:00Z",
        "body": (
            "Quick question before we sign up — does the assistant sync with "
            "Calendly, or only your own calendar? We already run everything "
            "through Calendly and don't want to switch."
        ),
    },
    {
        "id": "E-1006",
        "from_name": "Megan Hurst",
        "from_email": "megan@hurstsalon.co.uk",
        "subject": "Thinking of cancelling",
        "received": "2026-07-06T10:05:00Z",
        "body": (
            "Honestly I'm pretty frustrated. The reminders went out with the "
            "wrong times twice last week and two clients missed appointments. "
            "If this isn't sorted I'll be cancelling at the end of the month."
        ),
    },
    {
        "id": "E-1007",
        "from_name": "Aisha Rahman",
        "from_email": "aisha@rahmanvet.co.uk",
        "subject": "How do I change my opening hours?",
        "received": "2026-07-06T10:22:00Z",
        "body": (
            "Hi, we're changing our Saturday hours to 9-1. Where in the "
            "dashboard do I update this so the booking assistant knows? Thanks!"
        ),
    },
    {
        "id": "E-1008",
        "from_name": "Marcus Webb",
        "from_email": "marcus@webbdigitalpartners.com",
        "subject": "Reseller partnership",
        "received": "2026-07-06T10:48:00Z",
        "body": (
            "We're a digital agency with ~40 small-business clients and would "
            "like to explore reselling your AI assistant to them. Do you have "
            "a partner or white-label programme? Happy to jump on a call."
        ),
    },
    {
        "id": "E-1009",
        "from_name": "Sofia Almeida",
        "from_email": "sofia.almeida.dev@gmail.com",
        "subject": "Application - support role",
        "received": "2026-07-06T11:03:00Z",
        "body": (
            "Hello, I saw you might be hiring for customer support. I've "
            "attached my CV and would love to be considered. Thank you!"
        ),
    },
    {
        "id": "E-1010",
        "from_name": "Rachel Okafor",
        "from_email": "rachel@brightsmiledental.co.uk",
        "subject": "Re: Pricing for 3 locations?",
        "received": "2026-07-06T11:30:00Z",
        "body": (
            "Just following up on my earlier email — our practice manager is "
            "free Thursday or Friday afternoon if that works for a call. We'd "
            "want to go live before the end of the month."
        ),
    },
    {
        "id": "E-1011",
        "from_name": "Greg Mills",
        "from_email": "greg@millsmotorsmot.co.uk",
        "subject": "Does it work for MOT reminders?",
        "received": "2026-07-06T11:52:00Z",
        "body": (
            "We're a garage doing MOTs and services. Can the assistant text "
            "customers when their MOT is due and let them rebook? That's the "
            "main thing we'd use it for."
        ),
    },
    {
        "id": "E-1012",
        "from_name": "No Reply",
        "from_email": "noreply@newsletter-deals.biz",
        "subject": "50% off SEO backlinks this week only",
        "received": "2026-07-06T12:10:00Z",
        "body": (
            "Boost your rankings with 5,000 backlinks for $49. Limited time "
            "offer. Unsubscribe at the bottom. Act now!"
        ),
    },
]

# ── Runtime state (in-memory; reset on restart or via /api/reset) ───────────
# analyses:  email_id -> analysis dict produced by the agent
# decisions: email_id -> {"action": "approved"|"rejected", ...}
# crm:       list of records "written" to the (simulated) CRM on approval
# audit:     append-only list of {ts, email_id, actor, action, detail}
_state: dict = {}


def reset_state() -> None:
    _state["emails"] = copy.deepcopy(_SEED_EMAILS)
    _state["analyses"] = {}
    _state["decisions"] = {}
    _state["crm"] = []
    _state["audit"] = []
    _state["crm_seq"] = 0


def _ensure() -> None:
    if not _state:
        reset_state()


def list_emails() -> list[dict]:
    _ensure()
    return _state["emails"]


def get_email(email_id: str) -> dict | None:
    _ensure()
    return next((e for e in _state["emails"] if e["id"] == email_id), None)


def get_analysis(email_id: str) -> dict | None:
    _ensure()
    return _state["analyses"].get(email_id)


def set_analysis(email_id: str, analysis: dict) -> None:
    _ensure()
    _state["analyses"][email_id] = analysis


def get_decision(email_id: str) -> dict | None:
    _ensure()
    return _state["decisions"].get(email_id)


def set_decision(email_id: str, decision: dict) -> None:
    _ensure()
    _state["decisions"][email_id] = decision


def crm_records() -> list[dict]:
    _ensure()
    return _state["crm"]


def add_crm_record(record: dict) -> dict:
    _ensure()
    _state["crm_seq"] += 1
    record = {"crm_id": f"CRM-{2000 + _state['crm_seq']}", **record}
    _state["crm"].append(record)
    return record


def audit_log() -> list[dict]:
    _ensure()
    return _state["audit"]


def add_audit(email_id: str, actor: str, action: str, detail: str) -> None:
    _ensure()
    _state["audit"].insert(0, {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "email_id": email_id,
        "actor": actor,
        "action": action,
        "detail": detail,
    })
