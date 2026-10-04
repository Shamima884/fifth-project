"""Local smoke test: boot the app, register, build data, hit every page."""
import re
import sys
from pathlib import Path

# Fresh database every run (dev-only convenience).
_db_dir = Path(__file__).parent / "instance"
for _f in ("rxspark.db", "rxspark.db-wal", "rxspark.db-shm"):
    _p = _db_dir / _f
    if _p.exists():
        _p.unlink()

from rxspark import create_app  # noqa: E402

app = create_app()
print(f"APP OK - {len(list(app.url_map.iter_rules()))} routes")

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def csrf_of(html: bytes) -> str:
    m = re.search(rb'name="csrf_token" value="([0-9a-f]+)"', html)
    return m.group(1).decode() if m else ""


with app.test_client() as client:
    r = client.get("/")
    check("root redirects to login",
          r.status_code == 302 and "/auth/login" in r.headers["Location"])

    r = client.get("/auth/login")
    check("GET /auth/login", r.status_code == 200)

    r = client.get("/auth/register")
    csrf = csrf_of(r.data)
    r = client.post("/auth/register", data={
        "csrf_token": csrf, "name": "Dr Test User", "email": "e2e@test.local",
        "password": "password123", "confirm": "password123",
    }, follow_redirects=True)
    if b"Dashboard" not in r.data:
        # Account already existed — fall back to a plain login.
        r = client.get("/auth/login")
        csrf = csrf_of(r.data)
        r = client.post("/auth/login", data={
            "csrf_token": csrf, "email": "e2e@test.local",
            "password": "password123", "next": "/",
        }, follow_redirects=True)
    check("register/login -> dashboard",
          r.status_code == 200 and b"Dashboard" in r.data)

    r = client.get("/")
    csrf = csrf_of(r.data)
    check("dashboard renders", r.status_code == 200 and b"Active patients" in r.data)

    r = client.post("/patients/new", data={
        "csrf_token": csrf, "name": "Test Patient", "age": "34", "sex": "Male",
        "mobile": "01712345678", "date_of_birth": "", "email": "",
        "address": "Dhaka", "blood_group": "O+", "emergency_contact": "",
        "allergies": "Penicillin", "medical_history": "",
        "previous_medications": "",
    }, follow_redirects=True)
    check("create patient", r.status_code == 200 and b"Test Patient" in r.data)
    # IDs are never assumed: with demo seeding on, other rows may exist first.
    patient_id = re.search(r"/patients/(\d+)", r.request.path).group(1)

    r = client.post("/medicines/new", data={
        "csrf_token": csrf, "generic_name": "Cefixime", "brand_name": "Cefix",
        "strength": "200 mg", "dosage_form": "Capsule", "manufacturer": "Square",
        "route": "Oral",
    }, follow_redirects=True)
    check("create medicine", r.status_code == 200 and b"Cefixime" in r.data)

    r = client.post("/prescriptions/new", data={
        "csrf_token": csrf, "patient_id": patient_id, "visit_id": "",
        "prescription_date": "2026-10-01", "weight": "70 kg",
        "generic_name": ["Cefixime", ""], "brand_name": ["Cefix", ""],
        "strength": ["200 mg", ""], "dosage_form": ["Capsule", ""],
        "dose": ["1 capsule", ""], "frequency": ["Once daily", ""],
        "duration": ["5 days", ""], "instructions": ["After food", ""],
        "advice": "Plenty of fluids", "investigation": "",
        "follow_up_date": "2026-10-15",
        "follow_up_instructions": "Review if fever persists",
        "follow_up_notes": "",
    }, follow_redirects=True)
    check("create prescription draft", r.status_code == 200 and b"RX-" in r.data)
    rx_id = re.search(r"/prescriptions/(\d+)", r.request.path).group(1)

    r = client.get("/prescriptions/")
    check("prescriptions list", r.status_code == 200 and b"RX-" in r.data)

    r = client.post(f"/prescriptions/{rx_id}/finalize", data={"csrf_token": csrf},
                    follow_redirects=True)
    check("finalize prescription",
          r.status_code == 200 and b"finalized" in r.data.lower())

    r = client.post(f"/prescriptions/{rx_id}/duplicate", data={"csrf_token": csrf},
                    follow_redirects=True)
    check("duplicate prescription", r.status_code == 200 and b"RX-" in r.data)

    r = client.get(f"/prescriptions/{rx_id}/print")
    check("print PDF", r.status_code == 200 and r.data[:4] == b"%PDF",
          f"({len(r.data)} bytes)")

    r = client.post("/follow-ups/new", data={
        "csrf_token": csrf, "patient_id": patient_id, "prescription_id": rx_id,
        "follow_up_date": "2026-10-15", "instructions": "Review",
        "doctor_notes": "", "status": "pending",
    }, follow_redirects=True)
    check("create follow-up", r.status_code == 200 and b"Follow-up" in r.data)
    fu_id = re.search(r"/follow-ups/(\d+)/edit", r.data.decode()).group(1)

    r = client.post(f"/follow-ups/{fu_id}/status",
                    data={"csrf_token": csrf, "status": "completed"},
                    follow_redirects=True)
    check("complete follow-up",
          r.status_code == 200 and b"completed" in r.data.lower())

    r = client.get("/profile/edit")
    check("GET profile edit",
          r.status_code == 200 and b"Professional profile" in r.data)

    r = client.post("/profile/settings", data={
        "csrf_token": csrf, "language": "en", "date_format": "YYYY-MM-DD",
        "prescription_template": "compact",
    }, follow_redirects=True)
    check("save settings", r.status_code == 200)

    r = client.get("/ai/")
    check("GET AI chat page", r.status_code == 200 and b"AI Assistant" in r.data)

    r = client.post("/ai/chat",
                    json={"message": "Say the word OK and nothing else."},
                    headers={"X-CSRF-Token": csrf})
    if r.status_code == 200:
        reply = r.get_json().get("reply", "")
        check("AI chat Groq call", "OK" in reply.upper(),
              f"(reply: {reply[:60]!r})")
    else:
        check("AI chat Groq call", False,
              f"(status {r.status_code}: {r.data[:120]!r})")

    r = client.get("/no-such-page")
    check("404 page", r.status_code == 404)

    r = client.post("/auth/logout", data={"csrf_token": csrf},
                    follow_redirects=True)
    check("logout", r.status_code == 200 and b"Sign in" in r.data)

failed = [x for x in results if not x[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)

