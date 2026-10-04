"""RxSpark AI Assistant — Groq-powered, assistive only (never diagnostic).

Chat history lives in the session only; no clinical free text is persisted,
matching the audit-trail rule in security.py.
"""
import time

import requests
from flask import (
    Blueprint, current_app, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)

from .security import clean, login_required

bp = Blueprint("ai", __name__, url_prefix="/ai")

MAX_TURNS = 20          # kept in session; nothing written to the DB
MAX_MESSAGE = 4000

SYSTEM_PROMPT = (
    "You are the RxSpark AI Assistant inside a digital prescription app for "
    "doctors. You are assistive only: help draft wording, explain drug "
    "classes, summarize notes, and suggest questions to consider. Never "
    "present yourself as a substitute for clinical judgement, never confirm a "
    "diagnosis, and always remind the doctor to verify doses and interactions "
    "against local guidelines. Be concise and direct."
)


def _history():
    return session.get("ai_messages", [])


def _call_groq(messages) -> str:
    cfg = current_app.config
    if not cfg.get("AI_API_KEY"):
        raise RuntimeError("No AI API key configured (set RXSPARK_AI_API_KEY).")
    payload = {
        "model": cfg["AI_MODEL"],
        "messages": messages,
        "max_tokens": 1024,   # reasoning models need headroom
        "temperature": 0.3,
    }
    url = cfg["AI_BASE_URL"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['AI_API_KEY']}"}
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"].get("content") or ""
                return content.strip() or "(empty response — please retry)"
            # Retry transient upstream failures only.
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                time.sleep(1 + attempt)
                continue
            raise RuntimeError(
                f"AI request failed (HTTP {resp.status_code}): "
                f"{resp.text[:300]}"
            )
        except requests.RequestException as exc:
            last_err = str(exc)
            time.sleep(1 + attempt)
    raise RuntimeError(f"AI request failed: {last_err}")


@bp.route("/")
@login_required
def chat():
    return render_template("ai/chat.html", messages=_history())


@bp.route("/chat", methods=("POST",))
@login_required
def send():
    body = request.get_json(silent=True) or {}
    user_msg = clean(body.get("message", ""), MAX_MESSAGE)
    if not user_msg:
        return jsonify({"error": "Empty message."}), 400
    history = _history()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-MAX_TURNS:]
    messages.append({"role": "user", "content": user_msg})
    try:
        reply = _call_groq(messages)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("AI assistant error: %s", exc)
        return jsonify({"error": str(exc)}), 502
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": reply})
    session["ai_messages"] = history[-MAX_TURNS:]
    return jsonify({"reply": reply})


@bp.route("/clear", methods=("POST",))
@login_required
def clear():
    session.pop("ai_messages", None)
    if request.form.get("ajax"):
        return jsonify({"ok": True})
    flash("Conversation cleared.", "info")
    return redirect(url_for("ai.chat"))
