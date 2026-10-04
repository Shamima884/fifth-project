"""Authentication: register, login, logout, password reset."""
import hashlib
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import (
    Blueprint, current_app, flash, g, redirect, render_template, request,
    session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, now_str
from .security import audit, clean, is_valid_email, login_required

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _start_session(user_id: int, doctor_id) -> None:
    """Fresh session with creation timestamp (drives idle/absolute timeouts)."""
    session.clear()
    session["user_id"] = user_id
    session["doctor_id"] = doctor_id
    now = datetime.now().timestamp()
    session["created_at"] = now
    session["last_seen"] = now
    g.user_id = user_id
    g.doctor_id = doctor_id


def _safe_next(target) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.get("user_id"):
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        name = clean(request.form.get("name", ""), 120)
        email = clean(request.form.get("email", ""), 254).lower()
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()
        if not name or not is_valid_email(email):
            flash("Please provide your name and a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            db = get_db()
            if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                flash("An account with that email already exists.", "error")
            else:
                cur = db.execute(
                    "INSERT INTO users (email, password_hash, is_active, created_at, updated_at)"
                    " VALUES (?, ?, 1, ?, ?)",
                    (email, generate_password_hash(password), now_str(), now_str()),
                )
                user_id = cur.lastrowid
                doctor_id = db.execute(
                    "INSERT INTO doctors (user_id, name, email, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (user_id, name, email, now_str(), now_str()),
                ).lastrowid
                db.commit()
                _start_session(user_id, doctor_id)
                audit("account_registered", "user", user_id)
                flash("Welcome to RxSpark! Your account is ready.", "success")
                return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.get("user_id"):
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = clean(request.form.get("email", ""), 254).lower()
        # .strip(): tolerate accidental spaces when pasting; applied
        # consistently everywhere a password is set or checked.
        password = (request.form.get("password", "") or "").strip()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect email or password.", "error")
        elif not user["is_active"]:
            flash("This account has been deactivated. Contact support.", "error")
        else:
            doctor = db.execute(
                "SELECT id FROM doctors WHERE user_id = ?", (user["id"],)
            ).fetchone()
            _start_session(user["id"], doctor["id"] if doctor else None)
            audit("login", "user", user["id"])
            flash("Signed in successfully.", "success")
            return redirect(_safe_next(request.form.get("next")))
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.route("/logout", methods=("POST",))
@login_required
def logout():
    audit("logout", "user", g.user_id)
    session.clear()
    g.user_id = None
    g.doctor_id = None
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


# -------------------------------------------------------- password reset

def _send_mail(to_addr: str, subject: str, body: str) -> bool:
    mail_server = current_app.config.get("MAIL_SERVER", "")
    if not mail_server:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = current_app.config.get("MAIL_FROM", "no-reply@rxspark.local")
    msg["To"] = to_addr
    msg.set_content(body)
    port = int(current_app.config.get("MAIL_PORT", 587))
    with smtplib.SMTP(mail_server, port, timeout=15) as smtp:
        if current_app.config.get("MAIL_USERNAME"):
            smtp.starttls()
            smtp.login(
                current_app.config["MAIL_USERNAME"],
                current_app.config.get("MAIL_PASSWORD", ""),
            )
        smtp.send_message(msg)
    return True


@bp.route("/forgot-password", methods=("GET", "POST"))
def forgot_password():
    if g.get("user_id"):
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = clean(request.form.get("email", ""), 254).lower()
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        # Always show the same message — never leak which emails exist.
        message = "If an account exists for that email, a reset link has been sent."
        if user:
            raw = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw.encode()).hexdigest()
            expires = (datetime.now() + timedelta(minutes=30)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            db.execute(
                "INSERT INTO password_reset_tokens"
                " (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], token_hash, expires, now_str()),
            )
            db.commit()
            reset_url = url_for("auth.reset_password", token=raw, _external=True)
            try:
                _send_mail(
                    email,
                    "RxSpark password reset",
                    f"Reset your password within 30 minutes:\n{reset_url}\n"
                    "If you did not request this, ignore this email.",
                )
            except Exception:
                current_app.logger.exception("password reset mail failed")
            if current_app.config["DEMO_MODE"]:
                # Demo mode has no mail server — surface the link directly.
                flash(f"Demo mode reset link: {reset_url}", "info")
            else:
                flash(message, "info")
        else:
            flash(message, "info")
        return redirect(url_for("auth.forgot_password"))
    return render_template("auth/forgot_password.html")


@bp.route("/reset-password/<token>", methods=("GET", "POST"))
def reset_password(token: str):
    db = get_db()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.execute(
        "SELECT * FROM password_reset_tokens"
        " WHERE token_hash = ? AND used_at IS NULL",
        (token_hash,),
    ).fetchone()
    if row is None or row["expires_at"] < now_str():
        flash("This reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (generate_password_hash(password), now_str(), row["user_id"]),
            )
            db.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
                (now_str(), row["id"]),
            )
            db.commit()
            audit("password_reset", "user", row["user_id"])
            flash("Password updated. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html")

