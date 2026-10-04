-- RxSpark database schema (SQLite)
-- All clinical rows are scoped to the owning doctor (data ownership rule).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    degree TEXT NOT NULL DEFAULT '',
    specialty TEXT NOT NULL DEFAULT '',
    bmdc_registration_number TEXT NOT NULL DEFAULT '',
    clinic_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    photo_url TEXT,
    signature_url TEXT,
    clinic_logo_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doctors_user ON doctors(user_id);

CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    date_of_birth TEXT,
    age INTEGER,
    sex TEXT NOT NULL DEFAULT '',
    mobile TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    blood_group TEXT NOT NULL DEFAULT '',
    emergency_contact TEXT NOT NULL DEFAULT '',
    allergies TEXT NOT NULL DEFAULT '',
    medical_history TEXT NOT NULL DEFAULT '',
    previous_medications TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patients_doctor_status ON patients(doctor_id, status);
CREATE INDEX IF NOT EXISTS idx_patients_doctor_name ON patients(doctor_id, name);
CREATE INDEX IF NOT EXISTS idx_patients_doctor_mobile ON patients(doctor_id, mobile);

CREATE TABLE IF NOT EXISTS patient_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_date TEXT NOT NULL,
    chief_complaints TEXT NOT NULL DEFAULT '',
    history TEXT NOT NULL DEFAULT '',
    examination TEXT NOT NULL DEFAULT '',
    diagnosis TEXT NOT NULL DEFAULT '',
    investigation TEXT NOT NULL DEFAULT '',
    advice TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visits_doctor_patient ON patient_visits(doctor_id, patient_id);
CREATE INDEX IF NOT EXISTS idx_visits_doctor_date ON patient_visits(doctor_id, visit_date);

CREATE TABLE IF NOT EXISTS medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generic_name TEXT NOT NULL,
    brand_name TEXT NOT NULL DEFAULT '',
    strength TEXT NOT NULL DEFAULT '',
    dosage_form TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT 'Oral',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_medicines_generic ON medicines(generic_name);
CREATE INDEX IF NOT EXISTS idx_medicines_brand ON medicines(brand_name);

CREATE TABLE IF NOT EXISTS prescriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_id INTEGER REFERENCES patient_visits(id) ON DELETE SET NULL,
    prescription_number TEXT NOT NULL UNIQUE,
    prescription_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized')),
    weight TEXT NOT NULL DEFAULT '',
    advice TEXT NOT NULL DEFAULT '',
    investigation TEXT NOT NULL DEFAULT '',
    follow_up_date TEXT,
    follow_up_instructions TEXT NOT NULL DEFAULT '',
    follow_up_notes TEXT NOT NULL DEFAULT '',
    duplicate_of INTEGER REFERENCES prescriptions(id) ON DELETE SET NULL,
    requires_reconfirmation INTEGER NOT NULL DEFAULT 0,
    finalized_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rx_doctor_date ON prescriptions(doctor_id, prescription_date);
CREATE INDEX IF NOT EXISTS idx_rx_doctor_patient ON prescriptions(doctor_id, patient_id);
CREATE INDEX IF NOT EXISTS idx_rx_doctor_status ON prescriptions(doctor_id, status);

CREATE TABLE IF NOT EXISTS prescription_medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
    medicine_id INTEGER REFERENCES medicines(id) ON DELETE SET NULL,
    generic_name_snapshot TEXT NOT NULL DEFAULT '',
    brand_name_snapshot TEXT NOT NULL DEFAULT '',
    strength_snapshot TEXT NOT NULL DEFAULT '',
    dosage_form_snapshot TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT '',
    dose TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pmed_rx ON prescription_medicines(prescription_id);

CREATE TABLE IF NOT EXISTS follow_ups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    prescription_id INTEGER REFERENCES prescriptions(id) ON DELETE SET NULL,
    follow_up_date TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    doctor_notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_followups_doctor_status ON follow_ups(doctor_id, status);
CREATE INDEX IF NOT EXISTS idx_followups_date ON follow_ups(doctor_id, follow_up_date);

CREATE TABLE IF NOT EXISTS doctor_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL UNIQUE REFERENCES doctors(id) ON DELETE CASCADE,
    language TEXT NOT NULL DEFAULT 'en',
    date_format TEXT NOT NULL DEFAULT 'DD/MM/YYYY',
    prescription_template TEXT NOT NULL DEFAULT 'standard',
    default_print_settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER REFERENCES doctors(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_doctor_time ON audit_logs(doctor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO counters (name, value) VALUES ('patient_code', 0);
INSERT OR IGNORE INTO counters (name, value) VALUES ('prescription_number', 0);

