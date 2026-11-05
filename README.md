# CAPACITY CONNECT

**A community-powered learning and capacity-building platform.** Learners and trainers can publish and access courses, share lectures and resources, complete assessments, and track progress. Paid courses use PayPal Checkout; trainer earnings, refunds, financial reporting, and PayPal payouts are managed through the platform.

## Features in this MVP

- **Open registration:** users can register as learners or trainers. Accounts are active immediately.
- **Course catalogue:** trainers create free or paid courses with category, difficulty, tags/competencies, price, currency, and estimated duration. Learners can browse and enroll.
- **Lecture studio:** add video links or upload lecture files; attach PDFs and other resources; mark preview lessons.
- **Quizzes and scoring:** trainers create MCQ assessments; Django grades answers, records attempts, and calculates points and capped speed bonuses. No separate scoring service is needed.
- **Leaderboards:** global rankings and per-question rankings, with correctness as the priority and speed as a capped bonus.
- **Community question bank:** learners submit MCQs for trainer/admin review; approved questions are published with contributor attribution.
- **Assignments:** trainers publish instructions, deadlines, rubrics, and files; learners submit text, links, or attachments; trainers grade submissions and provide feedback.
- **Course discussions:** enrolled learners and course trainers can share messages.
- **Learning progress:** enrollment library, quiz history, points, and contribution history.
- **Admin tools:** Django admin, user management, and platform overview.
- **Learning intelligence:** personalized learning recommendations based on learner profile and progress.
- **PayPal payments:** order creation/capture, payment history, refund management, verified webhooks, dispute tracking, and financial reconciliation.
- **Trainer payouts:** earnings balances, withdrawal requests, admin approval, PayPal Payouts processing, and payout synchronization.

## Stack

- **Frontend:** React + Vite + Tailwind CSS
- **Backend:** Django + Django REST Framework
- **Authentication:** JSON Web Tokens (JWT)
- **Database:** SQLite by default for local development; PostgreSQL is supported through `DATABASE_URL`
- **Uploads:** Django media storage for development

The application uses one Django backend for all business logic, including assessment scoring. There is no FastAPI service.

## Run locally on Windows (recommended for an 8 GB RAM laptop)

You do not need Docker to develop this project. Start with SQLite, which does not require a separate database server. Install Python 3.11+ and Node.js 20+ (or a compatible current LTS release).

### 1. Start Django

Open a terminal in the project directory:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/api/` and Django admin at `http://127.0.0.1:8000/admin/`. If PowerShell blocks virtual-environment activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

### 2. Start React

Open a **second terminal** from the project directory:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend expects the Django API at `http://localhost:8000/api`.

### 3. Create your account

Register through the website as a learner or trainer. To access Django admin, use the superuser created in step 1. A regular user can also become a trainer through the account interface.

## Docker deployment

Docker Compose runs PostgreSQL, Django under Gunicorn, and a production-built React application served by Nginx. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for required environment variables, HTTPS/reverse-proxy setup, PayPal webhook configuration, backup guidance, and the final payment verification checklist. Do not use the example credentials in a public deployment.

## API highlights

- `POST /api/auth/register/`, `POST /api/auth/token/`, `GET /api/auth/me/`
- `GET/POST /api/courses/`, `POST /api/courses/{id}/enroll/`
- `GET/POST /api/lessons/` (supports multipart file upload)
- `GET/POST /api/assessments/`, `POST /api/assessments/{id}/submit/`
- `GET/POST /api/assignments/`, `POST /api/assignments/{id}/submit/`
- `GET /api/assignment-submissions/`, `POST /api/assignment-submissions/{id}/review/`
- `GET/POST /api/discussions/`
- `GET/POST /api/question-submissions/`, `POST /api/question-submissions/{id}/review/`
- `GET /api/leaderboard/`, `GET /api/attempts/`

## Production limitations

The deployment files provide a production-oriented container baseline, not a security audit or a substitute for operational controls. Before public launch, configure external HTTPS termination, email verification and account recovery, upload size/type limits, malware scanning, object storage/video delivery, moderation/reporting, off-site backups, monitoring/alerting, accessibility testing, and browser-based end-to-end tests. Client-side elapsed times can be manipulated; use server-issued timing or per-question answer APIs for high-stakes competitions. Do not upload copyrighted course material unless you have permission to distribute it.

## License

Application code is released under the MIT License. User-uploaded educational content is not automatically relicensed by this software license; each contributor remains responsible for the rights and licenses associated with their content.

## PayPal Phase 3: Financial Management

The backend now exposes these authenticated/admin-only finance operations:

- `POST /api/payments/webhook/` — PayPal webhook receiver. Configure the exact endpoint in the PayPal Developer Dashboard and set `PAYPAL_WEBHOOK_ID` in `backend/.env`. The endpoint verifies the transmission signature with PayPal before processing and stores event IDs for idempotency.
- `POST /api/admin/payments/<payment_id>/refund/` — Admin-only full or partial refund. Optional JSON body: `{"amount":"10.00","reason":"..."}`. Omit `amount` to refund the remaining balance. Local refund totals and commission/earnings are updated only after PayPal confirms `COMPLETED`. A full refund revokes the course enrollment; a partial refund leaves access active.
- `GET /api/admin/paypal-disputes/` — Admin-only dispute/chargeback inbox synchronized from verified PayPal dispute webhooks.
- `GET /api/admin/financial-report/` — Admin-only currency-separated gross, refunded, net, net platform-fee and trainer-share totals.
- `GET /api/admin/reconcile-payments/` — Admin-only read-only comparison of up to 100 local captures against PayPal. Optional repeat query parameter: `?payment_id=123&payment_id=124`.

Required backend environment variables (copy the relevant entries from `.env.example` into `backend/.env`):

```env
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=
PLATFORM_FEE_PERCENT=1
FRONTEND_URL=http://localhost:5173
```

After updating the code, run the migration and tests from `backend/`:

```powershell
python manage.py migrate
python manage.py test core -v 2
```

Do not expose or commit `backend/.env`. Use the sandbox webhook ID with sandbox credentials for local testing. For local webhook delivery, expose the development server through a trusted HTTPS tunnel and register that HTTPS URL in the PayPal sandbox app. Never disable signature verification in production.


## Payment phases

The payment implementation is organized into five development phases: PayPal Checkout, capture and enrollment; refunds and financial management; trainer earnings and payouts; payment reliability and security; and final deployment/integration readiness. The final phase is not a claim of live PayPal certification: live Sandbox/production transactions and browser-level end-to-end flows must still be verified with the actual PayPal app and deployment environment.
