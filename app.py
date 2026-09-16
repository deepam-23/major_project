import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt, get_jwt_identity, jwt_required
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from services.google_meet import GoogleMeetConfigurationError, GoogleMeetProvider

load_dotenv()

db = SQLAlchemy()

PROFILE_FIELDS_BY_ROLE = {
    "hod": {"full_name", "email", "phone", "designation", "department_focus", "about"},
    "department_admin": {"full_name", "email", "phone", "designation", "department_focus", "about"},
    "faculty": {"full_name", "email", "employee_id", "designation", "qualification", "subjects", "specialization", "phone", "about"},
    "student": {"full_name", "college_email", "usn", "semester", "section", "phone", "cgpa", "skills", "about"},
    "alumni": {"full_name", "email", "usn", "graduation_year", "batch", "company", "job_role", "linkedin", "about"},
    "association_coordinator": {"full_name", "email", "employee_or_usn", "association_role", "phone", "about"},
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(40), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    data = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(40), nullable=False, default="draft")
    review_comment = db.Column(db.String(1000), nullable=True)
    reviewed_by = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class OnlineClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    section = db.Column(db.String(10), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    meeting_url = db.Column(db.String(500), nullable=True)
    meeting_provider = db.Column(db.String(40), nullable=False, default="google_meet")
    provider_status = db.Column(db.String(40), nullable=False, default="not_configured")
    created_by = db.Column(db.Integer, nullable=False)


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "development-only-change-me"),
        JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY", "development-only-change-me-too"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///aiml_digital_twin.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    CORS(app, origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")])

    with app.app_context():
        db.create_all()
        seed_demo_users()

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "aiml-digital-twin-api"})

    @app.post("/api/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        user = db.session.scalar(db.select(User).where(User.email == email))
        if not user or not user.is_active or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401
        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role, "name": user.full_name},
            expires_delta=timedelta(hours=8),
        )
        db.session.add(AuditLog(actor_id=user.id, action="login", details={"email": user.email}))
        db.session.commit()
        return jsonify({"access_token": access_token, "user": serialize_user(user)})

    @app.get("/api/auth/me")
    @jwt_required()
    def me():
        user = db.session.get(User, int(get_jwt_identity()))
        if not user or not user.is_active:
            return jsonify({"error": "Account unavailable"}), 401
        return jsonify({"user": serialize_user(user)})

    @app.get("/api/profile")
    @jwt_required()
    def get_profile():
        user_id = int(get_jwt_identity())
        profile = db.session.scalar(db.select(Profile).where(Profile.user_id == user_id))
        return jsonify({"profile": serialize_profile(profile) if profile else {"status": "draft", "data": {}}})

    @app.put("/api/profile")
    @jwt_required()
    def update_profile():
        body = request.get_json(silent=True) or {}
        data = body.get("data")
        if not isinstance(data, dict):
            return jsonify({"error": "Profile data must be an object"}), 400
        user_id = int(get_jwt_identity())
        role = get_jwt().get("role")
        allowed_fields = PROFILE_FIELDS_BY_ROLE.get(role, set())
        unexpected_fields = sorted(set(data) - allowed_fields)
        if unexpected_fields:
            return jsonify({"error": "Profile contains fields not allowed for this role", "fields": unexpected_fields}), 403
        profile = db.session.scalar(db.select(Profile).where(Profile.user_id == user_id))
        if not profile:
            profile = Profile(user_id=user_id)
            db.session.add(profile)
        if profile.status in {"approved", "under_review"}:
            return jsonify({"error": "This profile is locked while it is under review or approved"}), 409
        profile.data = data
        profile.status = "draft"
        profile.review_comment = None
        db.session.add(AuditLog(actor_id=user_id, action="profile_updated", details={"status": profile.status}))
        db.session.commit()
        return jsonify({"profile": serialize_profile(profile)})

    @app.post("/api/profile/submit")
    @jwt_required()
    def submit_profile():
        user_id = int(get_jwt_identity())
        profile = db.session.scalar(db.select(Profile).where(Profile.user_id == user_id))
        if not profile or not profile.data:
            return jsonify({"error": "Complete profile details before submitting"}), 400
        if profile.status not in {"draft", "rejected", "correction_required"}:
            return jsonify({"error": "Profile cannot be submitted from its current state"}), 409
        profile.status = "submitted"
        db.session.add(AuditLog(actor_id=user_id, action="profile_submitted", details={"profile_id": profile.id}))
        db.session.commit()
        return jsonify({"profile": serialize_profile(profile)}), 202

    @app.get("/api/approvals/profiles")
    @jwt_required()
    @role_required("hod", "department_admin")
    def profile_approvals():
        profiles = db.session.scalars(db.select(Profile).where(Profile.status.in_(["submitted", "under_review"]))).all()
        return jsonify({"profiles": [serialize_profile(profile, include_private=True) for profile in profiles]})

    @app.post("/api/approvals/profiles/<int:profile_id>")
    @jwt_required()
    @role_required("hod", "department_admin")
    def review_profile(profile_id):
        body = request.get_json(silent=True) or {}
        decision = body.get("decision")
        comment = str(body.get("comment", "")).strip() or None
        if decision not in {"approved", "rejected", "correction_required"}:
            return jsonify({"error": "Decision must be approved, rejected, or correction_required"}), 400
        profile = db.session.get(Profile, profile_id)
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        reviewer_id = int(get_jwt_identity())
        profile.status = decision
        profile.review_comment = comment
        profile.reviewed_by = reviewer_id
        db.session.add(AuditLog(actor_id=reviewer_id, action="profile_reviewed", details={"profile_id": profile.id, "decision": decision}))
        db.session.commit()
        return jsonify({"profile": serialize_profile(profile, include_private=True)})

    @app.get("/api/dashboard/summary")
    @jwt_required()
    @role_required("hod", "department_admin", "faculty")
    def dashboard_summary():
        return jsonify({
            "metrics": {
                "students": 240,
                "faculty": 8,
                "alumni": 180,
                "active_users": 321,
                "placement_percentage": 82,
                "internship_percentage": 64,
                "projects": 96,
                "certifications": 318,
                "activities": 38,
                "pending_approvals": 12,
            },
            "monitoring": {"normal": 180, "attention": 42, "mentoring": 18},
            "placement_trend": [
                {"batch": "2022", "value": 68},
                {"batch": "2023", "value": 74},
                {"batch": "2024", "value": 79},
                {"batch": "2025", "value": 82},
            ],
            "upcoming_classes": OnlineClass.query.order_by(OnlineClass.start_at).limit(3).count(),
        })

    @app.post("/api/online-classes")
    @jwt_required()
    @role_required("hod", "department_admin", "faculty")
    def create_online_class():
        body = request.get_json(silent=True) or {}
        required = ("title", "semester", "section", "start_at", "duration_minutes")
        missing = [field for field in required if not body.get(field)]
        if missing:
            return jsonify({"error": "Missing required fields", "fields": missing}), 400
        try:
            start_at = datetime.fromisoformat(str(body["start_at"]).replace("Z", "+00:00"))
            duration = int(body["duration_minutes"])
            semester = int(body["semester"])
            if duration < 15 or duration > 240 or semester not in range(1, 9):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid schedule values"}), 400
        user_id = int(get_jwt_identity())
        configured = bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
        meeting_url = None
        provider_status = "not_configured"
        provider_message = "Configure Google Meet credentials to create a live meeting link."
        if configured:
            try:
                meeting_url = GoogleMeetProvider().create_meeting(
                    title=str(body["title"]).strip(),
                    start_at=start_at,
                    end_at=start_at + timedelta(minutes=duration),
                    description=f"AIML Department class for Semester {semester}, Section {str(body['section']).strip().upper()}",
                )
                provider_status = "created"
                provider_message = "Google Meet link created."
            except GoogleMeetConfigurationError as error:
                provider_status = "provider_error"
                provider_message = str(error)
        meeting = OnlineClass(
            title=str(body["title"]).strip(), semester=semester, section=str(body["section"]).strip().upper(),
            start_at=start_at, end_at=start_at + timedelta(minutes=duration), created_by=user_id,
            provider_status=provider_status,
            meeting_url=meeting_url,
        )
        db.session.add(meeting)
        db.session.add(AuditLog(actor_id=user_id, action="online_class_created", details={"title": meeting.title}))
        db.session.commit()
        return jsonify({"class": serialize_class(meeting), "message": provider_message}), 201

    @app.get("/api/public/faculty")
    def public_faculty():
        return jsonify({"data": [], "source": "AIML Digital Twin", "note": "Only HOD-approved public records are exposed here."})

    return app


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if get_jwt().get("role") not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def seed_demo_users():
    if db.session.scalar(db.select(User).limit(1)):
        return
    password = os.getenv("DEMO_ADMIN_PASSWORD")
    if not password:
        return
    db.session.add(User(email="hod@becbgk.edu", full_name="AIML HOD", role="hod", password_hash=generate_password_hash(password)))
    db.session.commit()


def serialize_user(user):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role}


def serialize_profile(profile, include_private=False):
    if not profile:
        return {"status": "draft", "data": {}}
    result = {"id": profile.id, "user_id": profile.user_id, "status": profile.status, "data": profile.data, "review_comment": profile.review_comment, "updated_at": profile.updated_at.isoformat()}
    if include_private:
        result["reviewed_by"] = profile.reviewed_by
    return result


def serialize_class(online_class):
    return {"id": online_class.id, "title": online_class.title, "semester": online_class.semester, "section": online_class.section, "start_at": online_class.start_at.isoformat(), "end_at": online_class.end_at.isoformat(), "meeting_url": online_class.meeting_url, "provider": online_class.meeting_provider, "provider_status": online_class.provider_status}

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
