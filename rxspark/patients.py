"""Patients: registry, visits, archive/restore. All rows scoped to doctor."""
from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, url_for,
)

from .db import get_db, now_str, today_str
from .security import (
    audit, clean, current_doctor_id, is_valid_date, is_valid_mobile,
    login_required, normalize_mobile, parse_date,
)

bp = Blueprint("patients", __name__, url_prefix="/patients")

BLOOD_GROUPS = ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


def _owned(patient_id):
    row = get_db().execute(
        "SELECT * FROM patients WHERE id = ? AND doctor_id = ?",
        (patient_id, current_doctor_id()),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _form_values():
    dob = clean(request.form.get("date_of_birth", ""), 20)
    if dob and not is_valid_date(dob):
        dob = ""
    age_raw = clean(request.form.get("age", ""), 4)
    age = int(age_raw) if age_raw.isdigit() else None
    mobile = normalize_mobile(clean(request.form.get("mobile", ""), 20))
    sex = request.form.get("sex", "")
    if sex not in ("Male", "Female", "Other"):
        sex = ""
    return {
        "name": clean(request.form.get("name", ""), 150),
        "date_of_birth": dob or None,
        "age": age,
        "sex": sex,
        "mobile": mobile if is_valid_mobile(mobile) else "",
        "email": clean(request.form.get("email", ""), 254),
        "address": clean(request.form.get("address", ""), 300),
        "blood_group": request.form.get("blood_group", "")
        if request.form.get("blood_group", "") in BLOOD_GROUPS else "",
        "emergency_contact": clean(request.form.get("emergency_contact", ""), 30),
        "allergies": clean(request.form.get("allergies", ""), 2000),
        "medical_history": clean(request.form.get("medical_history", ""), 2000),
        "previous_medications": clean(
            request.form.get("previous_medications", ""), 2000
        ),
    }


@bp.route("/")
@login_required
def list_patients():
    q = clean(request.args.get("q", ""), 100)
    status = request.args.get("status", "active")
    sql = "SELECT * FROM patients WHERE doctor_id = ?"
    params = [current_doctor_id()]
    if status in ("active", "archived"):
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (name LIKE ? OR patient_code LIKE ? OR mobile LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    sql += " ORDER BY name COLLATE NOCASE"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("patients/list.html", rows=rows, q=q, status=status)


@bp.route("/new", methods=("GET", "POST"))
@login_required
def create():
    if request.method == "POST":
        values = _form_values()
        if not values["name"]:
            flash("Patient name is required.", "error")
        elif values["mobile"] == "" and clean(request.form.get("mobile", "")):
            flash("Please enter a valid mobile number (e.g. 01712345678).", "error")
        else:
            db = get_db()
            from .db import next_patient_code
            code = next_patient_code(db)
            cur = db.execute(
                "INSERT INTO patients (doctor_id, patient_code, name, date_of_birth,"
                " age, sex, mobile, email, address, blood_group, emergency_contact,"
                " allergies, medical_history, previous_medications, status, is_demo,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)",
                (current_doctor_id(), code, *values.values(), now_str(), now_str()),
            )
            db.commit()
            audit("patient_created", "patient", cur.lastrowid, name=values["name"])
            flash(f"Patient {values['name']} ({code}) created.", "success")
            return redirect(url_for("patients.detail", patient_id=cur.lastrowid))
    return render_template(
        "patients/form.html", patient=None, blood_groups=BLOOD_GROUPS
    )


@bp.route("/<int:patient_id>")
@login_required
def detail(patient_id):
    patient = _owned(patient_id)
    db = get_db()
    visits = db.execute(
        "SELECT * FROM patient_visits WHERE patient_id = ? AND doctor_id = ?"
        " ORDER BY visit_date DESC, id DESC",
        (patient_id, current_doctor_id()),
    ).fetchall()
    prescriptions = db.execute(
        "SELECT * FROM prescriptions WHERE patient_id = ? AND doctor_id = ?"
        " ORDER BY prescription_date DESC, id DESC",
        (patient_id, current_doctor_id()),
    ).fetchall()
    followups = db.execute(
        "SELECT * FROM follow_ups WHERE patient_id = ? AND doctor_id = ?"
        " ORDER BY follow_up_date DESC",
        (patient_id, current_doctor_id()),
    ).fetchall()
    return render_template(
        "patients/detail.html",
        patient=patient, visits=visits, prescriptions=prescriptions,
        followups=followups,
    )


@bp.route("/<int:patient_id>/edit", methods=("GET", "POST"))
@login_required
def edit(patient_id):
    patient = _owned(patient_id)
    if request.method == "POST":
        values = _form_values()
        if not values["name"]:
            flash("Patient name is required.", "error")
        else:
            db = get_db()
            db.execute(
                "UPDATE patients SET name = ?, date_of_birth = ?, age = ?, sex = ?,"
                " mobile = ?, email = ?, address = ?, blood_group = ?,"
                " emergency_contact = ?, allergies = ?, medical_history = ?,"
                " previous_medications = ?, updated_at = ? WHERE id = ? AND doctor_id = ?",
                (*values.values(), now_str(), patient_id, current_doctor_id()),
            )
            db.commit()
            audit("patient_modified", "patient", patient_id, name=values["name"])
            flash("Patient updated.", "success")
            return redirect(url_for("patients.detail", patient_id=patient_id))
    return render_template(
        "patients/form.html", patient=patient, blood_groups=BLOOD_GROUPS
    )


@bp.route("/<int:patient_id>/archive", methods=("POST",))
@login_required
def archive(patient_id):
    patient = _owned(patient_id)
    db = get_db()
    db.execute(
        "UPDATE patients SET status = 'archived', updated_at = ?"
        " WHERE id = ? AND doctor_id = ?",
        (now_str(), patient_id, current_doctor_id()),
    )
    db.commit()
    audit("patient_archived", "patient", patient_id, name=patient["name"])
    flash(f"{patient['name']} archived.", "info")
    return redirect(url_for("patients.list_patients"))


@bp.route("/<int:patient_id>/restore", methods=("POST",))
@login_required
def restore(patient_id):
    patient = _owned(patient_id)
    db = get_db()
    db.execute(
        "UPDATE patients SET status = 'active', updated_at = ?"
        " WHERE id = ? AND doctor_id = ?",
        (now_str(), patient_id, current_doctor_id()),
    )
    db.commit()
    audit("patient_restored", "patient", patient_id, name=patient["name"])
    flash(f"{patient['name']} restored.", "success")
    return redirect(url_for("patients.detail", patient_id=patient_id))


# ------------------------------------------------------------------- visits

def _visit_values():
    visit_date = clean(request.form.get("visit_date", ""), 20) or today_str()
    if not is_valid_date(visit_date):
        visit_date = today_str()
    return (
        parse_date(visit_date).isoformat(),
        clean(request.form.get("chief_complaints", ""), 3000),
        clean(request.form.get("history", ""), 3000),
        clean(request.form.get("examination", ""), 3000),
        clean(request.form.get("diagnosis", ""), 3000),
        clean(request.form.get("investigation", ""), 3000),
        clean(request.form.get("advice", ""), 3000),
        clean(request.form.get("notes", ""), 3000),
    )


@bp.route("/<int:patient_id>/visits/new", methods=("POST",))
@login_required
def visit_create(patient_id):
    _owned(patient_id)
    db = get_db()
    db.execute(
        "INSERT INTO patient_visits (doctor_id, patient_id, visit_date,"
        " chief_complaints, history, examination, diagnosis, investigation,"
        " advice, notes, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (current_doctor_id(), patient_id, *_visit_values(), now_str(), now_str()),
    )
    db.commit()
    flash("Visit added.", "success")
    return redirect(url_for("patients.detail", patient_id=patient_id))


@bp.route("/<int:patient_id>/visits/<int:visit_id>/edit", methods=("GET", "POST"))
@login_required
def visit_edit(patient_id, visit_id):
    _owned(patient_id)
    db = get_db()
    visit = db.execute(
        "SELECT * FROM patient_visits WHERE id = ? AND patient_id = ?"
        " AND doctor_id = ?",
        (visit_id, patient_id, current_doctor_id()),
    ).fetchone()
    if visit is None:
        abort(404)
    if request.method == "POST":
        db.execute(
            "UPDATE patient_visits SET visit_date = ?, chief_complaints = ?,"
            " history = ?, examination = ?, diagnosis = ?, investigation = ?,"
            " advice = ?, notes = ?, updated_at = ? WHERE id = ?",
            (*_visit_values(), now_str(), visit_id),
        )
        db.commit()
        flash("Visit updated.", "success")
        return redirect(url_for("patients.detail", patient_id=patient_id))
    return render_template("patients/visit_form.html", patient_id=patient_id,
                           visit=visit)

