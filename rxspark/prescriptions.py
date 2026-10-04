"""Prescriptions: drafts, finalize, duplicate, PDF print."""
import io
from datetime import datetime

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, send_file,
    url_for,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .db import get_db, next_prescription_number, now_str, today_str
from .security import (
    audit, clean, current_doctor_id, is_valid_date, login_required, parse_date,
)

bp = Blueprint("prescriptions", __name__, url_prefix="/prescriptions")

MED_FIELDS = (
    "generic_name", "brand_name", "strength", "dosage_form",
    "dose", "frequency", "duration", "instructions",
)


def _owned(rx_id):
    row = get_db().execute(
        "SELECT * FROM prescriptions WHERE id = ? AND doctor_id = ?",
        (rx_id, current_doctor_id()),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _parse_med_rows():
    """Read repeated same-name inputs; drop rows where everything is blank."""
    lists = [request.form.getlist(f) for f in MED_FIELDS]
    rows = []
    for i in range(max((len(v) for v in lists), default=0)):
        values = [v[i].strip() if i < len(v) else "" for v in lists]
        if any(values):
            rows.append(dict(zip(MED_FIELDS, values)))
    return rows[:30]


def _save_med_rows(rx_id, rows, db):
    db.execute("DELETE FROM prescription_medicines WHERE prescription_id = ?", (rx_id,))
    for order, row in enumerate(rows):
        medicine = None
        if row.get("generic_name"):
            medicine = db.execute(
                "SELECT * FROM medicines WHERE generic_name = ? COLLATE NOCASE"
                " AND status = 'active' LIMIT 1",
                (row["generic_name"],),
            ).fetchone()
        db.execute(
            "INSERT INTO prescription_medicines (prescription_id, medicine_id,"
            " generic_name_snapshot, brand_name_snapshot, strength_snapshot,"
            " dosage_form_snapshot, route, dose, frequency, duration,"
            " instructions, display_order, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rx_id,
                medicine["id"] if medicine else None,
                row["generic_name"],
                row["brand_name"] or (medicine["brand_name"] if medicine else ""),
                row["strength"],
                row["dosage_form"] or (medicine["dosage_form"] if medicine else ""),
                medicine["route"] if medicine else "",
                row["dose"], row["frequency"], row["duration"], row["instructions"],
                order, now_str(),
            ),
        )


def _med_suggest(db):
    """Generic names for the form's datalist (pharmacopoeia autocomplete)."""
    return [
        r["generic_name"]
        for r in db.execute(
            "SELECT generic_name FROM medicines WHERE status = 'active'"
            " ORDER BY generic_name COLLATE NOCASE LIMIT 300"
        ).fetchall()
    ]


def _rx_form_values():
    rx_date = clean(request.form.get("prescription_date", ""), 20) or today_str()
    if not is_valid_date(rx_date):
        rx_date = today_str()
    follow_date = clean(request.form.get("follow_up_date", ""), 20)
    if follow_date and not is_valid_date(follow_date):
        follow_date = ""
    visit_raw = clean(request.form.get("visit_id", ""), 12)
    return {
        "patient_id": int(request.form.get("patient_id", 0) or 0),
        "visit_id": int(visit_raw) if visit_raw.isdigit() else None,
        "prescription_date": parse_date(rx_date).isoformat(),
        "weight": clean(request.form.get("weight", ""), 20),
        "advice": clean(request.form.get("advice", ""), 5000),
        "investigation": clean(request.form.get("investigation", ""), 5000),
        "follow_up_date": (
            parse_date(follow_date).isoformat() if follow_date else None
        ),
        "follow_up_instructions": clean(
            request.form.get("follow_up_instructions", ""), 3000
        ),
        "follow_up_notes": clean(request.form.get("follow_up_notes", ""), 3000),
    }


@bp.route("/")
@login_required
def list_prescriptions():
    q = clean(request.args.get("q", ""), 100)
    status = request.args.get("status", "")
    sql = (
        "SELECT r.*, p.name AS patient_name FROM prescriptions r"
        " JOIN patients p ON p.id = r.patient_id WHERE r.doctor_id = ?"
    )
    params = [current_doctor_id()]
    if status in ("draft", "finalized"):
        sql += " AND r.status = ?"
        params.append(status)
    if q:
        sql += " AND (r.prescription_number LIKE ? OR p.name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY r.created_at DESC LIMIT 200"
    rows = get_db().execute(sql, params).fetchall()
    return render_template(
        "prescriptions/list.html", rows=rows, q=q, status=status
    )


@bp.route("/new", methods=("GET", "POST"))
@login_required
def create():
    db = get_db()
    doc = current_doctor_id()
    patient_id = request.values.get("patient_id", type=int, default=0)
    if request.method == "POST":
        values = _rx_form_values()
        patient = db.execute(
            "SELECT id FROM patients WHERE id = ? AND doctor_id = ? AND status = 'active'",
            (values["patient_id"], doc),
        ).fetchone()
        rows = _parse_med_rows()
        if patient is None:
            flash("Please select a valid active patient.", "error")
        elif not rows:
            flash("Add at least one medicine row.", "error")
        else:
            number = next_prescription_number(db)
            cur = db.execute(
                "INSERT INTO prescriptions (doctor_id, patient_id, visit_id,"
                " prescription_number, prescription_date, status, weight, advice,"
                " investigation, follow_up_date, follow_up_instructions,"
                " follow_up_notes, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc, values["patient_id"],
                    values["visit_id"] if values["visit_id"] else None,
                    number, values["prescription_date"], values["weight"],
                    values["advice"], values["investigation"],
                    values["follow_up_date"], values["follow_up_instructions"],
                    values["follow_up_notes"], now_str(), now_str(),
                ),
            )
            _save_med_rows(cur.lastrowid, rows, db)
            db.commit()
            audit("prescription_created", "prescription", cur.lastrowid,
                  number=number)
            flash(f"Draft {number} created.", "success")
            return redirect(url_for("prescriptions.detail", rx_id=cur.lastrowid))
    patients = db.execute(
        "SELECT id, patient_code, name FROM patients WHERE doctor_id = ?"
        " AND status = 'active' ORDER BY name COLLATE NOCASE",
        (doc,),
    ).fetchall()
    visits = []
    if patient_id:
        visits = db.execute(
            "SELECT id, visit_date, chief_complaints FROM patient_visits"
            " WHERE patient_id = ? AND doctor_id = ? ORDER BY visit_date DESC",
            (patient_id, doc),
        ).fetchall()
    return render_template(
        "prescriptions/form.html", rx=None, patients=patients, visits=visits,
        patient_id=patient_id, medicines=[], med_suggest=_med_suggest(db),
    )


@bp.route("/<int:rx_id>")
@login_required
def detail(rx_id):
    rx = _owned(rx_id)
    db = get_db()
    items = db.execute(
        "SELECT * FROM prescription_medicines WHERE prescription_id = ?"
        " ORDER BY display_order",
        (rx_id,),
    ).fetchall()
    patient = db.execute(
        "SELECT * FROM patients WHERE id = ?", (rx["patient_id"],)
    ).fetchone()
    duplicate = None
    if rx["duplicate_of"]:
        duplicate = db.execute(
            "SELECT prescription_number FROM prescriptions WHERE id = ?",
            (rx["duplicate_of"],),
        ).fetchone()
    return render_template(
        "prescriptions/detail.html", rx=rx, items=items, patient=patient,
        duplicate=duplicate,
    )


@bp.route("/<int:rx_id>/edit", methods=("GET", "POST"))
@login_required
def edit(rx_id):
    rx = _owned(rx_id)
    if rx["status"] != "draft":
        flash("Finalized prescriptions cannot be edited. Duplicate instead.", "warning")
        return redirect(url_for("prescriptions.detail", rx_id=rx_id))
    db = get_db()
    if request.method == "POST":
        values = _rx_form_values()
        rows = _parse_med_rows()
        if not rows:
            flash("Add at least one medicine row.", "error")
        else:
            db.execute(
                "UPDATE prescriptions SET visit_id = ?, prescription_date = ?,"
                " weight = ?, advice = ?, investigation = ?, follow_up_date = ?,"
                " follow_up_instructions = ?, follow_up_notes = ?, updated_at = ?"
                " WHERE id = ? AND doctor_id = ?",
                (
                    values["visit_id"] if values["visit_id"] else None,
                    values["prescription_date"], values["weight"], values["advice"],
                    values["investigation"], values["follow_up_date"],
                    values["follow_up_instructions"], values["follow_up_notes"],
                    now_str(), rx_id, current_doctor_id(),
                ),
            )
            _save_med_rows(rx_id, rows, db)
            db.commit()
            audit("prescription_saved", "prescription", rx_id,
                  number=rx["prescription_number"])
            flash("Draft saved.", "success")
            return redirect(url_for("prescriptions.detail", rx_id=rx_id))
    items = db.execute(
        "SELECT * FROM prescription_medicines WHERE prescription_id = ?"
        " ORDER BY display_order",
        (rx_id,),
    ).fetchall()
    patients = db.execute(
        "SELECT id, patient_code, name FROM patients WHERE doctor_id = ?"
        " ORDER BY name COLLATE NOCASE",
        (current_doctor_id(),),
    ).fetchall()
    visits = db.execute(
        "SELECT id, visit_date, chief_complaints FROM patient_visits"
        " WHERE patient_id = ? AND doctor_id = ? ORDER BY visit_date DESC",
        (rx["patient_id"], current_doctor_id()),
    ).fetchall()
    return render_template(
        "prescriptions/form.html", rx=rx, patients=patients, visits=visits,
        patient_id=rx["patient_id"], medicines=items, med_suggest=_med_suggest(db),
    )


@bp.route("/<int:rx_id>/finalize", methods=("POST",))
@login_required
def finalize(rx_id):
    rx = _owned(rx_id)
    if rx["status"] == "finalized":
        flash("This prescription is already finalized.", "info")
        return redirect(url_for("prescriptions.detail", rx_id=rx_id))
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM prescription_medicines WHERE prescription_id = ?",
        (rx_id,),
    ).fetchone()[0]
    if not count:
        flash("Cannot finalize a prescription without medicines.", "error")
        return redirect(url_for("prescriptions.detail", rx_id=rx_id))
    db.execute(
        "UPDATE prescriptions SET status = 'finalized', finalized_at = ?,"
        " updated_at = ? WHERE id = ? AND doctor_id = ?",
        (now_str(), now_str(), rx_id, current_doctor_id()),
    )
    db.commit()
    audit("prescription_finalized", "prescription", rx_id,
          number=rx["prescription_number"])
    flash(f"{rx['prescription_number']} finalized.", "success")
    return redirect(url_for("prescriptions.detail", rx_id=rx_id))


@bp.route("/<int:rx_id>/duplicate", methods=("POST",))
@login_required
def duplicate(rx_id):
    rx = _owned(rx_id)
    db = get_db()
    doc = current_doctor_id()
    number = next_prescription_number(db)
    cur = db.execute(
        "INSERT INTO prescriptions (doctor_id, patient_id, visit_id,"
        " prescription_number, prescription_date, status, weight, advice,"
        " investigation, follow_up_date, follow_up_instructions, follow_up_notes,"
        " duplicate_of, requires_reconfirmation, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (
            doc, rx["patient_id"], rx["visit_id"], number, today_str(),
            rx["weight"], rx["advice"], rx["investigation"], rx["follow_up_date"],
            rx["follow_up_instructions"], rx["follow_up_notes"], rx_id,
            now_str(), now_str(),
        ),
    )
    items = db.execute(
        "SELECT * FROM prescription_medicines WHERE prescription_id = ?"
        " ORDER BY display_order",
        (rx_id,),
    ).fetchall()
    rows = [{
        "generic_name": item["generic_name_snapshot"],
        "brand_name": item["brand_name_snapshot"],
        "strength": item["strength_snapshot"],
        "dosage_form": item["dosage_form_snapshot"],
        "dose": item["dose"],
        "frequency": item["frequency"],
        "duration": item["duration"],
        "instructions": item["instructions"],
    } for item in items]
    _save_med_rows(cur.lastrowid, rows, db)
    db.commit()
    audit("prescription_duplicated", "prescription", cur.lastrowid,
          source=rx["prescription_number"])
    flash(f"Created {number} as a draft copy — review before finalizing.", "info")
    return redirect(url_for("prescriptions.edit", rx_id=cur.lastrowid))


# ------------------------------------------------------------------- PDF

def _wrap(c, text, x, y, max_width, leading=11, font="Helvetica", size=9):
    """Word-wrap helper; returns the y position after the last line."""
    c.setFont(font, size)
    line = ""
    for word in str(text or "").split():
        trial = f"{line} {word}".strip()
        if c.stringWidth(trial, font, size) <= max_width:
            line = trial
        else:
            c.drawString(x, y, line)
            y -= leading
            line = word
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def _build_pdf(rx, patient, items, doctor) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 18 * mm
    y = height - margin

    # ---- header: doctor / clinic ----------------------------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, (doctor["clinic_name"] or "RxSpark").strip())
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin, y, rx["prescription_number"])
    y -= 14
    c.setFont("Helvetica-Bold", 11)
    doc_line = " ".join(
        p for p in [
            doctor["name"] or "", doctor["title"] or "", doctor["degree"] or ""
        ] if p
    ) or "Registered Doctor"
    c.drawString(margin, y, doc_line)
    y -= 12
    c.setFont("Helvetica", 9)
    if doctor["specialty"]:
        c.drawString(margin, y, doctor["specialty"])
        y -= 12
    meta = "  |  ".join(
        p for p in [
            f"BMDC: {doctor['bmdc_registration_number']}"
            if doctor["bmdc_registration_number"] else "",
            doctor["phone"] or "",
            doctor["email"] or "",
        ] if p
    )
    if meta:
        c.drawString(margin, y, meta)
        y -= 12
    if doctor["address"]:
        y = _wrap(c, doctor["address"], margin, y, width - 2 * margin)
    c.setStrokeColorRGB(0.2, 0.4, 0.7)
    c.setLineWidth(1.4)
    c.line(margin, y + 4, width - margin, y + 4)
    y -= 12

    # ---- patient box -----------------------------------------------------
    c.setFillColorRGB(0.95, 0.96, 0.98)
    c.rect(margin, y - 52, width - 2 * margin, 58, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 6, y - 6, patient["name"])
    c.setFont("Helvetica", 9)
    details = [
        f"Code: {patient['patient_code']}",
        f"Age: {patient['age'] or '-'} yrs",
        f"Sex: {patient['sex'] or '-'}",
        f"Weight: {rx['weight'] or '-'}",
        f"Date: {rx['prescription_date']}",
    ]
    if patient["blood_group"]:
        details.append(f"Blood: {patient['blood_group']}")
    if patient["mobile"]:
        details.append(f"Mobile: {patient['mobile']}")
    c.drawString(margin + 6, y - 22, "   |   ".join(details[:4]))
    if len(details) > 4:
        c.drawString(margin + 6, y - 36, "   |   ".join(details[4:]))
    if patient["allergies"]:
        c.setFillColorRGB(0.75, 0.1, 0.1)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin + 6, y - 50, f"Allergies: {patient['allergies'][:120]}")
        c.setFillColorRGB(0, 0, 0)
    y -= 66

    # ---- medicines table --------------------------------------------------
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Medicines")
    y -= 14
    col = {"idx": margin, "name": margin + 16, "dose": margin + 265,
           "freq": margin + 345, "dur": margin + 435}
    for item in items:
        if y < 90:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica-Bold", 10)
        c.setFont("Helvetica-Bold", 9)
        strength = " ".join(
            p for p in [item["strength_snapshot"], item["dosage_form_snapshot"]] if p
        )
        c.drawString(col["idx"], y, ".")
        c.drawString(col["name"], y,
                     f"{item['generic_name_snapshot'] or 'Medicine'}"
                     f"{' ' + strength if strength else ''}")
        c.setFont("Helvetica", 9)
        c.drawString(col["dose"], y, item["dose"] or "-")
        c.drawString(col["freq"], y, item["frequency"] or "-")
        c.drawString(col["dur"], y, item["duration"] or "-")
        y -= 12
        if item["brand_name_snapshot"]:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(col["name"], y,
                         f"Brand: {item['brand_name_snapshot']}")
            y -= 11
        if item["instructions"]:
            c.setFont("Helvetica-Oblique", 8)
            y = _wrap(c, f"Note: {item['instructions']}", col["name"] + 10, y,
                      width - margin - col["name"] - 10, leading=10)
        y -= 6

    # ---- advice / investigation / follow-up -------------------------------
    for title, body in (
        ("Advice", rx["advice"]),
        ("Investigation", rx["investigation"]),
        ("Follow-up", " ".join(
            p for p in [rx["follow_up_date"] or "",
                        rx["follow_up_instructions"] or ""] if p
        )),
    ):
        if body:
            if y < 70:
                c.showPage()
                y = height - margin
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, y, title)
            y -= 13
            y = _wrap(c, body, margin, y, width - 2 * margin, leading=12)
            y -= 8

    # ---- signature --------------------------------------------------------
    if y < 70:
        c.showPage()
        y = height - margin
    sig_x = width - margin - 170
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.8)
    c.line(sig_x, y - 24, width - margin, y - 24)
    c.setFont("Helvetica", 9)
    c.drawString(sig_x, y - 38, f"Signature: {doctor['name'] or 'Doctor'}")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(margin, 20,
                 "Generated by RxSpark — digital prescription system.")
    c.save()
    return buf.getvalue()


@bp.route("/<int:rx_id>/print")
@login_required
def print_pdf(rx_id):
    rx = _owned(rx_id)
    db = get_db()
    items = db.execute(
        "SELECT * FROM prescription_medicines WHERE prescription_id = ?"
        " ORDER BY display_order",
        (rx_id,),
    ).fetchall()
    patient = db.execute(
        "SELECT * FROM patients WHERE id = ?", (rx["patient_id"],)
    ).fetchone()
    doctor = db.execute(
        "SELECT * FROM doctors WHERE id = ?", (current_doctor_id(),)
    ).fetchone()
    pdf = _build_pdf(rx, patient, items, doctor)
    audit("prescription_printed", "prescription", rx_id,
          number=rx["prescription_number"])
    return send_file(
        io.BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{rx['prescription_number']}.pdf",
    )





