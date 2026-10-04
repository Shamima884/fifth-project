"""RxSpark application factory."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, g, redirect, render_template, request, session, url_for, flash,
)

from .config import Config
from .db import close_db, get_db, init_db
from .security import (
    AUDIT_ACTIONS, current_doctor_id, get_csrf_token, humanize_date,
    datetime_display, format_mobile, load_session_identity, validate_csrf,
)


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    init_db_app(app)

    # ---- session: identity, idle timeout, absolute timeout -------------
    @app.before_request
    def _session_guard():
        g.user_id = None
        g.doctor_id = None
        now = datetime.now().timestamp()
        if "user_id" in session:
            created = session.get("created_at", now)
            last = session.get("last_seen", now)
            expired = (
                now - last > app.config["SESSION_IDLE_TIMEOUT"]
                or now - created > app.config["SESSION_ABSOLUTE_TIMEOUT"]
            )
            if expired:
                session.clear()
                flash(
                    "Your session expired for security. Please log in again.",
                    "warning",
                )
            else:
                session["last_seen"] = now
                load_session_identity(session["user_id"], session.get("doctor_id"))

    @app.before_request
    def _csrf_protect():
        if not validate_csrf():
            flash("Security check failed. Please retry the action.", "error")
            return redirect(request.referrer or url_for("main.dashboard"))

    @app.context_processor
    def _inject_globals():
        return {
            "csrf_token": get_csrf_token,
            "current_doctor_id": current_doctor_id,
            "demo_mode": app.config["DEMO_MODE"],
            "audit_label": lambda a: AUDIT_ACTIONS.get(a, a),
            "fmt_date": humanize_date,
            "fmt_dt": datetime_display,
            "fmt_mobile": format_mobile,
            "app_name": app.config["APP_NAME"],
            "app_tagline": app.config["APP_TAGLINE"],
            "now_year": datetime.now().year,
        }

    @app.teardown_appcontext
    def _close(exc):
        close_db(exc)

    # ---- error handling -------------------------------------------------
    @app.errorhandler(404)
    def _not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def _forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def _server_error(e):
        return render_template("errors/500.html"), 500

    @app.errorhandler(413)
    def _too_large(e):
        flash("File is too large. Maximum upload size is 6 MB.", "error")
        return redirect(request.referrer or url_for("profile.edit_profile"))

    # ---- blueprints -----------------------------------------------------
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .patients import bp as patients_bp
    from .medicines import bp as medicines_bp
    from .prescriptions import bp as rx_bp
    from .followups import bp as followups_bp
    from .profile import bp as profile_bp
    from .ai import bp as ai_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(medicines_bp)
    app.register_blueprint(rx_bp)
    app.register_blueprint(followups_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(ai_bp)

    # ---- Flask CLI -------------------------------------------------------
    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables."""
        init_db()
        print("Database initialised.")

    @app.cli.command("seed-demo")
    def seed_command():
        """Insert fictional demo data."""
        from .seed import seed_demo
        seed_demo()
        print("Demo data seeded.")

    return app


def init_db_app(app: Flask) -> None:
    with app.app_context():
        init_db()
        # Demo mode: make sure the demo account exists on fresh databases
        # (e.g. a new deployment). seed_demo() is idempotent — it exits
        # immediately when the demo user is already present.
        if app.config["DEMO_MODE"]:
            from .seed import seed_demo
            seed_demo()
