"""Dashboard (landing page after sign-in)."""
from flask import Blueprint, g, render_template

from .db import get_db, now_str, today_str
from .security import current_doctor_id, login_required

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    db = get_db()
    doc = current_doctor_id()
    month_prefix = now_str()[:7]  # YYYY-MM

    stats = {
        "active_patients": db.execute(
            "SELECT COUNT(*) FROM patients WHERE doctor_id = ? AND status = 'active'",
            (doc,),
        ).fetchone()[0],
        "archived_patients": db.execute(
            "SELECT COUNT(*) FROM patients WHERE doctor_id = ? AND status = 'archived'",
            (doc,),
        ).fetchone()[0],
        "prescriptions": db.execute(
            "SELECT COUNT(*) FROM prescriptions WHERE doctor_id = ?", (doc,)
        ).fetchone()[0],
        "rx_this_month": db.execute(
            "SELECT COUNT(*) FROM prescriptions WHERE doctor_id = ?"
            " AND prescription_date LIKE ?",
            (doc, month_prefix + "%"),
        ).fetchone()[0],
        "pending_followups": db.execute(
            "SELECT COUNT(*) FROM follow_ups WHERE doctor_id = ? AND status = 'pending'",
            (doc,),
        ).fetchone()[0],
        "todays_followups": db.execute(
            "SELECT COUNT(*) FROM follow_ups WHERE doctor_id = ? AND status = 'pending'"
            " AND follow_up_date = ?",
            (doc, today_str()),
        ).fetchone()[0],
    }

    recent_rx = db.execute(
        "SELECT r.id, r.prescription_number, r.prescription_date, r.status,"
        " p.name AS patient_name"
        " FROM prescriptions r JOIN patients p ON p.id = r.patient_id"
        " WHERE r.doctor_id = ? ORDER BY r.created_at DESC LIMIT 6",
        (doc,),
    ).fetchall()

    upcoming = db.execute(
        "SELECT f.id, f.follow_up_date, f.status, p.name AS patient_name,"
        " r.prescription_number"
        " FROM follow_ups f"
        " JOIN patients p ON p.id = f.patient_id"
        " LEFT JOIN prescriptions r ON r.id = f.prescription_id"
        " WHERE f.doctor_id = ? AND f.status = 'pending'"
        " ORDER BY f.follow_up_date ASC LIMIT 6",
        (doc,),
    ).fetchall()

    doctor = db.execute(
        "SELECT name, specialty, clinic_name FROM doctors WHERE id = ?", (doc,)
    ).fetchone()

    return render_template(
        "main/dashboard.html",
        stats=stats,
        recent_rx=recent_rx,
        upcoming=upcoming,
        doctor=doctor,
    )
