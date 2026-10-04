"""Follow-ups: schedule, track, complete."""
from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)

from .db import get_db, now_str, today_str
from .security import (
    audit, clean, current_doctor_id, is_valid_date, login_required, parse_date,
)

bp = Blueprint("followups", __name__, url_prefix="/follow-ups")

STATUSES = ("pending", "completed", "cancelled")


def _owned(fu_id):
    row = get_db().execute(
        "SELECT * FROM follow_ups WHERE id = ? AND doctor_id = ?",
        (fu_id, current_doctor_id()),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _form_values():
    date = clean(request.form.get("follow_up_date", ""), 20) or today_str()
    if not is_valid_date(date):
        date = today_str()
    status = request.form.get("status", "pending")
    if status not in STATUSES:
        status = "pending"
    return (
        parse_date(date).isoformat(),
        clean(request.form.get("instructions", ""), 3000),
        clean(request.form.get("doctor_notes", ""), 3000),
        status,
    )


@bp.route("/")
@login_required
def list_followups():
    status = request.args.get("status", "pending")
    sql = (
        "SELECT f.*, p.name AS patient_name, p.patient_code,"
        " r.prescription_number FROM follow_ups f"
        " JOIN patients p ON p.id = f.patient_id"
        " LEFT JOIN prescriptions r ON r.id = f.prescription_id"
        " WHERE f.doctor_id = ?"
    )
    params = [current_doctor_id()]
    if status in STATUSES:
        sql += " AND f.status = ?"
        params.append(status)
    sql += " ORDER BY f.follow_up_date ASC, f.id ASC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("followups/list.html", rows=rows, status=status,
                           statuses=STATUSES)


@bp.route("/new", methods=("POST",))
@login_required
def create():
    doc = current_doctor_id()
    db = get_db()
    patient_id = request.form.get("patient_id", type=int, default=0)
    prescription_id = request.form.get("prescription_id", type=int, default=0)
    patient = db.execute(
        "SELECT id FROM patients WHERE id = ? AND doctor_id = ?",
        (patient_id, doc),
    ).fetchone()
    if patient is None:
        flash("Please select a patient.", "error")
        return redirect(url_for("followups.list_followups"))
    rx = None
    if prescription_id:
        rx = db.execute(
            "SELECT id FROM prescriptions WHERE id = ? AND doctor_id = ?",
            (prescription_id, doc),
        ).fetchone()
    date, instructions, notes, status = _form_values()
    cur = db.execute(
        "INSERT INTO follow_ups (doctor_id, patient_id, prescription_id,"
        " follow_up_date, instructions, doctor_notes, status, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doc, patient_id, rx["id"] if rx else None,
            date, instructions, notes, status, now_str(), now_str(),
        ),
    )
    db.commit()
    audit("followup_created", "follow_up", cur.lastrowid, date=date)
    flash("Follow-up scheduled.", "success")
    target = request.form.get("next", "")
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(url_for("followups.list_followups"))


@bp.route("/<int:fu_id>/edit", methods=("GET", "POST"))
@login_required
def edit(fu_id):
    fu = _owned(fu_id)
    if request.method == "POST":
        date, instructions, notes, status = _form_values()
        db = get_db()
        db.execute(
            "UPDATE follow_ups SET follow_up_date = ?, instructions = ?,"
            " doctor_notes = ?, status = ?, updated_at = ? WHERE id = ?"
            " AND doctor_id = ?",
            (date, instructions, notes, status, now_str(), fu_id,
             current_doctor_id()),
        )
        db.commit()
        audit("followup_updated", "follow_up", fu_id, date=date)
        flash("Follow-up updated.", "success")
        return redirect(url_for("followups.list_followups"))
    db = get_db()
    patient = db.execute(
        "SELECT * FROM patients WHERE id = ?", (fu["patient_id"],)
    ).fetchone()
    return render_template("followups/form.html", fu=fu, patient=patient,
                           statuses=STATUSES)


@bp.route("/<int:fu_id>/status", methods=("POST",))
@login_required
def set_status(fu_id):
    fu = _owned(fu_id)
    status = request.form.get("status", fu["status"])
    if status not in STATUSES:
        status = fu["status"]
    db = get_db()
    db.execute(
        "UPDATE follow_ups SET status = ?, updated_at = ? WHERE id = ?"
        " AND doctor_id = ?",
        (status, now_str(), fu_id, current_doctor_id()),
    )
    db.commit()
    audit("followup_updated", "follow_up", fu_id, status=status)
    flash(f"Follow-up marked {status}.", "success")
    return redirect(url_for("followups.list_followups"))
