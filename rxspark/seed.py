"""Fictional demo data (DEMO_MODE only) — never real patient records."""
from datetime import date, timedelta

from flask import g
from werkzeug.security import generate_password_hash

from .db import (
    get_db, next_patient_code, next_prescription_number, now_str,
)


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def seed_demo() -> None:
    db = get_db()
    if db.execute(
        "SELECT id FROM users WHERE email = ?", ("demo@rxspark.local",)
    ).fetchone():
        return  # demo account already present — nothing to do

    user_id = db.execute(
        "INSERT INTO users (email, password_hash, is_active, created_at, updated_at)"
        " VALUES (?, ?, 1, ?, ?)",
        ("demo@rxspark.local", generate_password_hash("demo1234"),
         now_str(), now_str()),
    ).lastrowid
    doctor_id = db.execute(
        "INSERT INTO doctors (user_id, name, title, degree, specialty,"
        " bmdc_registration_number, clinic_name, phone, email, address,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id, "Dr. Ayesha Rahman", "Consultant Physician",
            "MBBS, FCPS (Medicine)", "Medicine", "A-12345",
            "City Clinic", "01711000000", "ayesha@cityclinic.example",
            "12 Mirpur Road, Dhaka", now_str(), now_str(),
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO doctor_settings (doctor_id, created_at, updated_at)"
        " VALUES (?, ?, ?)",
        (doctor_id, now_str(), now_str()),
    )
    g.user_id = user_id
    g.doctor_id = doctor_id

    medicines = [
        ("Paracetamol", "Napa", "500 mg", "Tablet", "Square", "Oral"),
        ("Ibuprofen", "Brufen", "400 mg", "Tablet", "Abbott", "Oral"),
        ("Amoxicillin", "Novamox", "500 mg", "Capsule", "Beximco", "Oral"),
        ("Metformin", "Glucophage", "500 mg", "Tablet", "Merck", "Oral"),
        ("Omeprazole", "Losec", "20 mg", "Capsule", "AstraZeneca", "Oral"),
        ("Cetirizine", "Zyrtec", "10 mg", "Tablet", "UCB", "Oral"),
        ("Oral rehydration salts", "ORS", "20.5 g/L", "Sachet", "UNICEF", "Oral"),
        ("Salbutamol", "Ventolin", "100 mcg", "Inhaler", "GSK", "Inhaled"),
    ]
    # Shared pharmacopoeia: only seed when the table is still empty so a
    # re-run (or a DB left over from tests) never duplicates entries.
    if not db.execute("SELECT id FROM medicines LIMIT 1").fetchone():
        for m in medicines:
            db.execute(
                "INSERT INTO medicines (generic_name, brand_name, strength,"
                " dosage_form, manufacturer, route, status, is_demo,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)",
                (*m, now_str(), now_str()),
            )

    patients = [
        ("Rahim Uddin", 45, "Male", "01712345678", "Type 2 diabetes, hypertension",
         "Metformin 500 mg BD"),
        ("Fatema Khatun", 32, "Female", "01812345678", "Bronchial asthma",
         "Salbutamol inhaler PRN"),
        ("Karim Hossain", 8, "Male", "01912345678", "No known allergies", ""),
        ("Salma Akter", 27, "Female", "01612345678", "Iron deficiency anaemia",
         "Ferrous sulphate"),
        ("Jashim Uddin", 61, "Male", "01512345678", "CAD, dyslipidaemia",
         "Atorvastatin 20 mg HS"),
    ]
    patient_ids = []
    for name, age, sex, mobile, history, prev in patients:
        pid = db.execute(
            "INSERT INTO patients (doctor_id, patient_code, name, age, sex, mobile,"
            " address, blood_group, allergies, medical_history,"
            " previous_medications, status, is_demo, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, 'active', 1, ?, ?)",
            (doctor_id, next_patient_code(db), name, age, sex, mobile,
             "Dhaka, Bangladesh", history, prev, now_str(), now_str()),
        ).lastrowid
        patient_ids.append(pid)

    db.execute(
        "INSERT INTO patient_visits (doctor_id, patient_id, visit_date,"
        " chief_complaints, history, examination, diagnosis, investigation,"
        " advice, notes, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)",
        (
            doctor_id, patient_ids[0], _d(3),
            "Fasting glucose 9.8 mmol/L on routine check",
            "Polyuria, occasional dizziness",
            "BP 140/90, BMI 27",
            "Type 2 diabetes mellitus, poorly controlled",
            "HbA1c, lipid profile",
            "Continue Metformin, lifestyle modification, follow-up in 3 months",
            now_str(), now_str(),
        ),
    )

    rx_id = db.execute(
        "INSERT INTO prescriptions (doctor_id, patient_id, prescription_number,"
        " prescription_date, status, weight, advice, investigation,"
        " follow_up_date, follow_up_instructions, finalized_at,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, 'finalized', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doctor_id, patient_ids[0], next_prescription_number(db),
            _d(3), "78 kg",
            "Low glycemic diet, 30 min walk daily, monitor fasting glucose",
            "HbA1c in 3 months", _d(-87),
            "Review after 3 months with reports", now_str(), now_str(), now_str(),
        ),
    ).lastrowid
    for order, med in enumerate(medicines[:2]):
        generic, brand, strength, form = med[0], med[1], med[2], med[3]
        db.execute(
            "INSERT INTO prescription_medicines (prescription_id, generic_name_snapshot,"
            " brand_name_snapshot, strength_snapshot, dosage_form_snapshot,"
            " dose, frequency, duration, display_order, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rx_id, generic, brand, strength, form, "1 tablet",
                "Three times daily" if order == 0 else "Twice daily",
                "5 days", order, now_str(),
            ),
        )

    db.execute(
        "INSERT INTO follow_ups (doctor_id, patient_id, prescription_id,"
        " follow_up_date, instructions, doctor_notes, status, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, '', 'pending', ?, ?)",
        (
            doctor_id, patient_ids[0], rx_id, _d(-87),
            "Bring HbA1c and lipid profile reports", now_str(), now_str(),
        ),
    )
    db.commit()

