"""Doctor profile, settings, and password change."""
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,
)
from werkzeug.security import generate_password_hash, check_password_hash

from .db import get_db, now_str
from .security import audit, clean, current_doctor_id, is_valid_email, login_required

bp = Blueprint("profile", __name__, url_prefix="/profile")

DATE_FORMATS = ("DD/MM/YYYY", "YYYY-MM-DD", "MM/DD/YYYY")
TEMPLATES = ("standard", "compact", "classic")
LANGUAGES = ("en", "bn")


def _get_settings(db, doc_id):
    row = db.execute(
        "SELECT * FROM doctor_settings WHERE doctor_id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO doctor_settings (doctor_id, created_at, updated_at)"
            " VALUES (?, ?, ?)",
            (doc_id, now_str(), now_str()),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM doctor_settings WHERE doctor_id = ?", (doc_id,)
        ).fetchone()
    return row


@bp.route("/")
@login_required
def index():
    return redirect(url_for("profile.edit_profile"))


@bp.route("/edit", methods=("GET", "POST"))
@login_required
def edit_profile():
    doc_id = current_doctor_id()
    db = get_db()
    doctor = db.execute("SELECT * FROM doctors WHERE id = ?", (doc_id,)).fetchone()
    if request.method == "POST":
        values = {
            "name": clean(request.form.get("name", ""), 120),
            "title": clean(request.form.get("title", ""), 120),
            "degree": clean(request.form.get("degree", ""), 200),
            "specialty": clean(request.form.get("specialty", ""), 120),
            "bmdc_registration_number": clean(
                request.form.get("bmdc_registration_number", ""), 60
            ),
            "clinic_name": clean(request.form.get("clinic_name", ""), 200),
            "phone": clean(request.form.get("phone", ""), 30),
            "email": clean(request.form.get("email", ""), 254),
            "address": clean(request.form.get("address", ""), 400),
            "photo_url": clean(request.form.get("photo_url", ""), 500),
            "signature_url": clean(request.form.get("signature_url", ""), 500),
            "clinic_logo_url": clean(request.form.get("clinic_logo_url", ""), 500),
        }
        if not values["name"]:
            flash("Name is required.", "error")
        elif values["email"] and not is_valid_email(values["email"]):
            flash("Please enter a valid email address.", "error")
        else:
            db.execute(
                "UPDATE doctors SET name = ?, title = ?, degree = ?, specialty = ?,"
                " bmdc_registration_number = ?, clinic_name = ?, phone = ?,"
                " email = ?, address = ?, photo_url = ?, signature_url = ?,"
                " clinic_logo_url = ?, updated_at = ? WHERE id = ?",
                (*values.values(), now_str(), doc_id),
            )
            db.commit()
            audit("profile_updated", "doctor", doc_id)
            flash("Profile updated.", "success")
            return redirect(url_for("profile.edit_profile"))
    settings = _get_settings(db, doc_id)
    return render_template(
        "profile/edit.html", doctor=doctor, settings=settings,
        date_formats=DATE_FORMATS, templates=TEMPLATES, languages=LANGUAGES,
    )


@bp.route("/settings", methods=("POST",))
@login_required
def update_settings():
    doc_id = current_doctor_id()
    language = request.form.get("language", "en")
    date_format = request.form.get("date_format", "DD/MM/YYYY")
    template = request.form.get("prescription_template", "standard")
    if language not in LANGUAGES:
        language = "en"
    if date_format not in DATE_FORMATS:
        date_format = "DD/MM/YYYY"
    if template not in TEMPLATES:
        template = "standard"
    db = get_db()
    _get_settings(db, doc_id)
    db.execute(
        "UPDATE doctor_settings SET language = ?, date_format = ?,"
        " prescription_template = ?, updated_at = ? WHERE doctor_id = ?",
        (language, date_format, template, now_str(), doc_id),
    )
    db.commit()
    audit("settings_changed", "doctor", doc_id)
    flash("Settings saved.", "success")
    return redirect(url_for("profile.edit_profile"))


@bp.route("/password", methods=("POST",))
@login_required
def change_password():
    current = request.form.get("current_password", "").strip()
    new = request.form.get("new_password", "").strip()
    confirm = request.form.get("confirm_password", "").strip()
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (g.user_id,)
    ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], current):
        flash("Current password is incorrect.", "error")
    elif len(new) < 8:
        flash("New password must be at least 8 characters long.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    else:
        db.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (generate_password_hash(new), now_str(), user["id"]),
        )
        db.commit()
        audit("profile_updated", "user", user["id"], field="password")
        flash("Password changed.", "success")
    return redirect(url_for("profile.edit_profile"))
