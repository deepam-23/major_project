<<<<<<< HEAD
# AIML Department Digital Twin

Secure internal operations portal for the Artificial Intelligence and Machine Learning Department at Basaveshwar Engineering College, Bagalkote.

The official BEC AIML website remains the public source for department information: <https://www.becbgk.edu/departments/ug/ai-and-ml>. This project is a separate authenticated portal and does not replace it.

## Current foundation

- React + TypeScript + Vite frontend in `frontend/`
- Flask + SQLAlchemy + JWT backend in `backend/`
- HOD command-center dashboard with verified-record-oriented metrics
- Backend role authorization for HOD, department admin, and faculty dashboard access
- Hashed-password login, JWT sessions, audit logging, and account activation state
- Self-service profile drafts with submit/review/approve/reject/correction-required states
- Google Meet provider boundary for online classes; no meeting URL is fabricated when credentials are absent
- Public API boundary that intentionally returns only approved public records

## Local setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL for shared deployment, or SQLite for local development

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:DEMO_ADMIN_PASSWORD = 'set-a-local-demo-password'
python app.py
```

The API runs at `http://localhost:5000`.

Profile workflow endpoints are authenticated: `GET /api/profile`, `PUT /api/profile`, and `POST /api/profile/submit`. HOD and Department Admin review submitted records through `GET /api/approvals/profiles` and `POST /api/approvals/profiles/<profile_id>`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

The portal runs at `http://localhost:5173` and proxies `/api` to Flask.

## Google Meet configuration

The initial integration is designed around a Google service account or delegated Google Workspace account. Set `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_MEET_CALENDAR_ID` in the backend environment only. Do not commit credentials. The current endpoint persists the class request and reports `not_configured` until provider credentials are available; this is deliberate so the system never claims a live meeting exists without creating one.

## Security notes

- Change `SECRET_KEY` and `JWT_SECRET_KEY` before deployment.
- Use PostgreSQL, HTTPS, secure secret storage, object storage, malware scanning, rate limiting, and a managed email provider in production.
- Add migrations before production schema changes; `db.create_all()` is only a development bootstrap.
- Public serializers must never include private phone numbers, academic records, placement documents, or unapproved records.

## Roadmap

The next vertical slices are self-service profiles and document verification, notification delivery, Google Meet event creation, placement analytics, and AI reports grounded only in approved records.
=======
# major_project
>>>>>>> 08da856d188df6a005bdc7867a6d9e3561be0ad7
