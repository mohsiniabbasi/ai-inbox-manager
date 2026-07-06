"""AI Inbox Manager — FastAPI backend.

Endpoints:
  GET  /                     -> the console UI
  GET  /api/emails           -> inbox + each email's AI analysis + decision state
  POST /api/analyze          -> (re)run triage over the whole inbox
  POST /api/decision/{id}    -> approve (writes to CRM + logs "reply sent") or reject
  GET  /api/crm              -> records written to the (simulated) CRM
  GET  /api/audit            -> append-only audit log
  POST /api/reset            -> reset demo state
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import agent, data

app = FastAPI(title="AI Inbox Manager", version="1.0")

_STATIC = os.path.join(os.path.dirname(__file__), "static")


def _analysis_for(email: dict) -> dict:
    cached = data.get_analysis(email["id"])
    if cached is None:
        cached = agent.analyze(email)
        data.set_analysis(email["id"], cached)
    return cached


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/api/emails")
def emails() -> dict:
    out = []
    for e in data.list_emails():
        out.append({
            **e,
            "analysis": _analysis_for(e),
            "decision": data.get_decision(e["id"]),
        })
    llm_on = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {"emails": out, "engine": "llm" if llm_on else "rules"}


@app.post("/api/analyze")
def analyze_all() -> dict:
    for e in data.list_emails():
        data.set_analysis(e["id"], agent.analyze(e))
    return {"ok": True, "count": len(data.list_emails())}


class Decision(BaseModel):
    action: str                      # "approve" | "reject"
    edited_reply: str | None = None
    edited_fields: dict | None = None


@app.post("/api/decision/{email_id}")
def decide(email_id: str, body: Decision) -> dict:
    email = data.get_email(email_id)
    if not email:
        raise HTTPException(404, "email not found")
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")

    analysis = _analysis_for(email)
    who = email["from_name"]

    if body.action == "reject":
        data.set_decision(email_id, {"action": "rejected"})
        data.add_audit(email_id, "operator", "rejected",
                       f"Dismissed AI recommendation ({analysis['intent']}) for {who}.")
        return {"ok": True, "action": "rejected"}

    # approve -> apply the CRM action (with any human edits) + log the reply
    crm_action = analysis.get("crm_action")
    if body.edited_fields is not None and crm_action:
        crm_action = {**crm_action, "fields": {**crm_action["fields"], **body.edited_fields}}

    crm_record = None
    if crm_action:
        crm_record = data.add_crm_record({
            "object": crm_action["object"],
            "operation": crm_action["operation"],
            "source_email": email_id,
            **crm_action["fields"],
        })
        data.add_audit(email_id, "operator", "crm_write",
                       f"{crm_action['operation']} {crm_action['object']} for {who} "
                       f"({crm_record['crm_id']}).")

    reply = body.edited_reply if body.edited_reply is not None else analysis.get("draft_reply", "")
    edited = body.edited_reply is not None
    if reply.strip():
        data.add_audit(email_id, "operator", "reply_sent",
                       f"Reply {'(edited) ' if edited else ''}sent to {who}.")

    data.set_decision(email_id, {
        "action": "approved",
        "crm_id": crm_record["crm_id"] if crm_record else None,
        "reply_sent": bool(reply.strip()),
        "edited": edited,
    })
    return {"ok": True, "action": "approved", "crm_record": crm_record}


@app.get("/api/crm")
def crm() -> dict:
    return {"records": data.crm_records()}


@app.get("/api/audit")
def audit() -> dict:
    return {"entries": data.audit_log()}


@app.post("/api/reset")
def reset() -> dict:
    data.reset_state()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
