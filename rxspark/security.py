"""Security helpers: access control, CSRF, audit trail, validation."""
import json
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import g, redirect, request, session, url_for, flash

from .db import get_db, now_str

# --------------------------------------------------------------------------
# Authentication / session
# --------------------------------------------------------------------------

def login_required(view):
    """Only authenticated users may reach clinical routes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user_id") is None:
            if request.method == "GET":
                flash("Please log in to continue.", "info")
            else:
                flash("Your session has expired. Please log in again.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user_id():
    return g.get("user_id")


def current_doctor_id():
    return g.get("doctor_id")


def load_session_identity(user_id, doctor_id):
    """Attach identity to flask.g for this request (called from before_request)."""
    g.user_id = user_id
    g.doctor_id = doctor_id


# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------

def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> bool:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return True
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    return bool(expected) and secrets.compare_digest(sent, expected)


# --------------------------------------------------------------------------
# Audit trail (no passwords, no secrets, no clinical free text)
# --------------------------------------------------------------------------

AUDIT_ACTIONS = {
    "patient_created": "Patient created",
    "patient_modified": "Patient modified",
    "patient_archived": "Patient archived",
    "patient_restored": "Patient restored",
    "prescription_created": "Prescription created",
    "prescription_modified": "Prescription modified",
    "prescription_saved": "Prescription saved",
    "prescription_finalized": "Prescription finalized",
    "prescription_duplicated": "Prescription duplicated",
    "prescription_printed": "Prescription printed/downloaded",
    "followup_created": "Follow-up created",
    "followup_updated": "Follow-up updated",
    "profile_updated": "Profile updated",
    "settings_changed": "Settings changed",
    "medicine_added": "Medicine added",
    "medicine_modified": "Medicine modified",
    "login": "Signed in",
    "logout": "Signed out",
    "password_reset": "Password reset",
    "account_registered": "Account registered",
}


def audit(action: str, entity_type: str, entity_id=None, **metadata) -> None:
    """Record a clinically important action for the authenticated doctor."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_logs (doctor_id, action, entity_type, entity_id, metadata, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                current_doctor_id(),
                action,
                entity_type,
                str(entity_id) if entity_id is not None else None,
                json.dumps(metadata, ensure_ascii=False) if metadata else "{}",
                now_str(),
            ),
        )
        db.commit()
    except Exception:
        # Auditing must never break the primary workflow.
        pass


# --------------------------------------------------------------------------
# Input validation / normalisation
# --------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BD_MOBILE_RE = re.compile(r"^(?:\+?880|0)1[3-9]\d{8}$")


def clean(value, max_len: int = 5000) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value or ""))


def normalize_mobile(value: str) -> str:
    """Normalise BD mobile numbers to 01XXXXXXXXX."""
    v = re.sub(r"[\s\-()]", "", value or "")
    if v.startswith("+880"):
        v = "0" + v[4:]
    elif v.startswith("880"):
        v = "0" + v[3:]
    return v


def is_valid_mobile(value: str) -> bool:
    return bool(BD_MOBILE_RE.match(normalize_mobile(value)))


def format_mobile(value: str) -> str:
    v = normalize_mobile(value)
    if len(v) == 11 and v.startswith("01"):
        return f"{v[0:5]}-{v[5:10]}{v[10:]}"
    return value or ""


def parse_date(value: str):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value or "", fmt).date()
        except ValueError:
            continue
    return None


def is_valid_date(value: str) -> bool:
    return parse_date(value) is not None


def humanize_date(value, fmt: str = "DD/MM/YYYY"):
    """Format a date string for display according to doctor settings."""
    if not value:
        return ""
    text = str(value)
    iso = text[:10]
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return text
    if fmt == "YYYY-MM-DD":
        return d.strftime("%Y-%m-%d")
    if fmt == "MM/DD/YYYY":
        return d.strftime("%m/%d/%Y")
    return d.strftime("%d/%m/%Y")


def datetime_display(value):
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
        return dt.strftime("%d/%m/%Y %I:%M %p")
    except ValueError:
        return text
