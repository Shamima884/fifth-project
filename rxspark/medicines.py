"""Medicine pharmacopoeia (shared reference list)."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import get_db, now_str
from .security import audit, clean, login_required

bp = Blueprint("medicines", __name__, url_prefix="/medicines")

ROUTES = ["Oral", "IV", "IM", "SC", "Topical", "Inhaled", "Ophthalmic", "Otologic"]
FORMS = ["Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Cream", "Ointment", "Drops"]


def _get_owned(medicine_id):
    row = get_db().execute(
        "SELECT * FROM medicines WHERE id = ?", (medicine_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _form_values():
    return {
        "generic_name": clean(request.form.get("generic_name", ""), 200),
        "brand_name": clean(request.form.get("brand_name", ""), 200),
        "strength": clean(request.form.get("strength", ""), 80),
        "dosage_form": clean(request.form.get("dosage_form", ""), 80),
        "manufacturer": clean(request.form.get("manufacturer", ""), 200),
        "route": clean(request.form.get("route", ""), 60) or "Oral",
    }


@bp.route("/")
@login_required
def list_medicines():
    q = clean(request.args.get("q", ""), 100)
    status = request.args.get("status", "active")
    sql = "SELECT * FROM medicines WHERE 1=1"
    params = []
    if q:
        sql += " AND (generic_name LIKE ? OR brand_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if status in ("active", "inactive"):
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY generic_name COLLATE NOCASE"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("medicines/list.html", rows=rows, q=q, status=status)


@bp.route("/new", methods=("GET", "POST"))
@login_required
def create():
    if request.method == "POST":
        values = _form_values()
        if not values["generic_name"]:
            flash("Generic name is required.", "error")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO medicines (generic_name, brand_name, strength,"
                " dosage_form, manufacturer, route, status, is_demo,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)",
                (*values.values(), now_str(), now_str()),
            )
            db.commit()
            audit("medicine_added", "medicine", None, generic=values["generic_name"])
            flash(f"Medicine '{values['generic_name']}' added.", "success")
            return redirect(url_for("medicines.list_medicines"))
    return render_template(
        "medicines/form.html", medicine=None, routes=ROUTES, forms=FORMS
    )


@bp.route("/<int:medicine_id>/edit", methods=("GET", "POST"))
@login_required
def edit(medicine_id):
    medicine = _get_owned(medicine_id)
    if request.method == "POST":
        values = _form_values()
        status = request.form.get("status", medicine["status"])
        if status not in ("active", "inactive"):
            status = medicine["status"]
        if not values["generic_name"]:
            flash("Generic name is required.", "error")
        else:
            db = get_db()
            db.execute(
                "UPDATE medicines SET generic_name = ?, brand_name = ?, strength = ?,"
                " dosage_form = ?, manufacturer = ?, route = ?, status = ?, updated_at = ?"
                " WHERE id = ?",
                (*values.values(), status, now_str(), medicine_id),
            )
            db.commit()
            audit("medicine_modified", "medicine", medicine_id,
                  generic=values["generic_name"])
            flash("Medicine updated.", "success")
            return redirect(url_for("medicines.list_medicines"))
    return render_template(
        "medicines/form.html", medicine=medicine, routes=ROUTES, forms=FORMS
    )
