# CAPACITY CONNECT

**A community-powered learning and capacity-building platform.** Learners and trainers publish and access courses, share lectures and resources, complete assessments, and track progress. Paid courses use PayPal Checkout; trainer earnings, refunds, financial reporting, and PayPal payouts are managed through the platform.

## Features

### Learning

- **Open registration:** users register as learners or trainers. Accounts are active immediately.
- **Discover page:** search courses, then filter by category, free/paid, and sort by popularity, newest, price, or title. Cards show an "Enrolled" badge.
- **Course catalogue:** trainers create free or paid courses with category, difficulty, tags/competencies, price, currency, and estimated duration.
- **Lecture studio:** video links or uploaded lecture files, PDFs and other resources, preview lessons.
- **Quizzes and scoring:** trainers create MCQ assessments; Django grades answers, records attempts, and calculates points and capped speed bonuses. A top-level **Quizzes** page lists every quiz; a completed quiz shows its score and a read-only **Review** with the correct answers and explanations.
- **Practice missed questions:** from a quiz Review, re-answer only the questions you got wrong. Graded instantly; points are awarded for the first correct answer only, so points cannot be farmed.
- **Community question bank:** learners submit MCQs for trainer/admin review; approved questions are published with contributor attribution.
- **Assignments:** trainers publish instructions, deadlines, rubrics, and files; learners submit text, links, or attachments; trainers grade and give feedback.
- **Course discussions:** enrolled learners and course trainers can share messages.
- **Leaderboards:** global and per-question rankings; correctness first, speed as a capped bonus.

### Motivation and recognition

- **Achievements, XP and streaks:** on **My progress**. XP equals leaderboard points (a level every 100 XP), a daily study streak (quizzes, practice, assignments, and community posts all count), a 14-day activity strip, and badges with progress bars. Nothing extra is stored; it is all computed from existing activity.
- **Verifiable certificates:** a learner earns a certificate for a course once every published quiz in it has been taken with an average of at least 50%. Each certificate has a signed ID (`CC-<user>-<course>-<signature>`), can be printed or saved as PDF, and has a public verification link of the form `http://localhost:5173/?verify=<CODE>` that works without signing in.
- **Learning intelligence:** explainable, rule-based course recommendations and a suggested learning path based on the learner's profile and progress.

### Teaching and administration

- **Trainer analytics:** learners, quiz attempts, average score, completion rate, certificates issued, learners who never started a quiz, hardest questions, and gross/refunded/net earnings. Trainers see their own courses; admins see everything.
- **Admin tools:** Django admin, user and role management, platform overview, and the financial dashboard described below.

### Payments

- **PayPal Checkout:** order creation and capture, payment history, invoices, and course access on successful capture.
- **Refunds and finance:** full or partial refunds, verified webhooks, dispute tracking, and reconciliation against PayPal.
- **Trainer payouts:** earnings balances, withdrawal requests, admin approval, PayPal Payouts processing, and payout synchronization.

## Stack

- **Frontend:** React + Vite + Tailwind CSS
- **Backend:** Django + Django REST Framework
- **Authentication:** JSON Web Tokens (JWT)
- **Database:** SQLite by default for local development; PostgreSQL is supported through `DATABASE_URL`
- **Uploads:** Django media storage for development

The application uses one Django backend for all business logic, including assessment scoring. There is no FastAPI service.

## Run locally

You do not need Docker to develop this project. Start with SQLite, which does not require a separate database server. Install **Python 3.11+** and **Node.js 20+** (or a compatible current LTS release).

### 1. Create `backend/.env`

Django refuses to start without it. Create `backend/.env` with at least:

```env
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=any-random-string-of-at-least-32-characters
```

PayPal values are only needed for payments (see [PayPal setup](#paypal-setup)). `backend/.env` is git-ignored; never commit it.

### 2. Start Django

From the repository root.

**macOS / Linux:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

**Windows (PowerShell):**

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

The API is at `http://127.0.0.1:8000/api/` and Django admin at `http://127.0.0.1:8000/admin/`. If PowerShell blocks virtual-environment activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

### 3. Start React

In a **second terminal**, from the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend expects the Django API at `http://localhost:8000/api`.

### 4. Load demo data (recommended)

With the virtual environment active, from `backend/`:

```bash
python manage.py seed_demo_story
```

This one command builds a demo-ready platform (it runs `seed_student_data` and `sync_assessment_questions` for you). It is safe to run repeatedly and does not delete data. It creates:

- courses, lectures, quizzes, assignments, discussions, and an approved question bank
- learners with different histories, so the leaderboard, XP levels, badges, and streaks look real (for example `student_ananya` has a 9-day streak and leads the leaderboard; `student_aarav` has a lapsed streak)
- a paid course, **Incident Response Playbook (Premium)** at USD 9.99, ready for a live PayPal sandbox purchase

It deliberately creates **no** payments, refunds, or payouts, so the money flow you demo is real.

**Demo accounts (local development only).** The password for every account below is `DemoPass123!`. Running the seed command resets it to that value.

| Role | Usernames |
|------|-----------|
| Admin | `demo_admin` |
| Trainer | `demo_trainer`, `demo_trainer2` (`demo_pending_trainer` is awaiting approval) |
| Learner | `student_aarav`, `student_isha`, `student_riya`, `student_karan`, `student_ananya`, `student_dev` |

Never create these accounts in a public deployment.

`python manage.py seed_demo_data` is an older, smaller seed (one trainer, a few courses) and is not needed if you ran `seed_demo_story`.

### 5. Or create your own account

Register through the website as a learner or trainer. To use Django admin, sign in with the superuser from step 2. A regular user can also become a trainer through the account interface.

## Run the tests

From `backend/` with the virtual environment active:

```bash
python manage.py test
```

To run one file: `python manage.py test core.test_insights`. The frontend has no test suite; check that it builds with `npm run build` from `frontend/`.

## Suggested demo walkthrough

1. **Learner** (`student_ananya`): open **My progress** for XP, level, streak, and badges. Open **Certificates**, print one, and open its verification link in a private window.
2. **Learner:** open **Quizzes**, review a completed quiz, then use **Practice missed questions**. Back on **Discover**, try the category, price, and sort filters.
3. **Purchase:** as a learner without the premium course, buy **Incident Response Playbook (Premium)** with a PayPal sandbox buyer account.
4. **Trainer** (`demo_trainer`): open **Analytics** to see learners, hardest questions, and net earnings including the new sale.
5. **Admin** (`demo_admin`): open **Admin** for the financial report, issue a refund, run the PayPal reconciliation, and approve a trainer payout.

## Docker deployment

Docker Compose runs PostgreSQL, Django under Gunicorn, and a production-built React application served by Nginx. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for required environment variables, HTTPS/reverse-proxy setup, PayPal webhook configuration, backup guidance, and the final payment verification checklist. Copy `.env.example` to `.env` first. Do not use the example credentials in a public deployment.

## API highlights

**Accounts and learning**

- `POST /api/auth/register/`, `POST /api/auth/token/`, `GET /api/auth/me/`, `POST /api/auth/become-trainer/`
- `GET/POST /api/courses/`, `POST /api/courses/{id}/enroll/`, `POST /api/courses/{id}/withdraw/`, `POST /api/courses/{id}/rejoin/`
- `GET/POST /api/lessons/` (supports multipart file upload)
- `GET/POST /api/assessments/`, `POST /api/assessments/{id}/submit/`
- `GET/POST /api/assignments/`, `POST /api/assignments/{id}/submit/`
- `GET /api/assignment-submissions/`, `POST /api/assignment-submissions/{id}/review/`
- `GET/POST /api/discussions/`
- `GET/POST /api/question-submissions/`, `POST /api/question-submissions/{id}/review/`, `POST /api/question-submissions/grade-practice/`
- `GET /api/leaderboard/`, `GET /api/attempts/`, `GET /api/enrollments/`

**Progress, recognition and insights**

- `GET /api/achievements/`: XP, level, streak, and badges for the signed-in learner
- `GET /api/certificates/`: the learner's earned certificates
- `GET /api/certificates/verify/{code}/`: public certificate verification (no login)
- `GET /api/trainer/analytics/`: trainer (own courses) or admin (all courses)
- `GET /api/ai/learning-intelligence/`: recommendations and learning path

**Payments and payouts** (details in [PayPal setup](#paypal-setup))

- `POST /api/payments/create-order/`, `POST /api/payments/capture-order/`, `GET /api/payments/history/`, `GET /api/transactions/`
- `POST /api/payments/webhook/`
- `GET /api/trainer/payouts/`, `GET /api/admin/trainer-payouts/`, `POST /api/admin/trainer-payouts/{id}/sync/`
- `POST /api/admin/payments/{payment_id}/refund/`, `GET /api/admin/financial-report/`, `GET /api/admin/reconcile-payments/`, `GET /api/admin/paypal-disputes/`, `GET /api/admin/webhook-reconciliation-events/`

## PayPal setup

Use **sandbox** credentials for development and demos. Add these to `backend/.env` (the full list is in `.env.example`):

```env
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=
PLATFORM_FEE_PERCENT=1
FRONTEND_URL=http://localhost:5173
```

After changing models or pulling new code, run `python manage.py migrate` and `python manage.py test` from `backend/`.

Finance operations (authenticated or admin-only):

- `POST /api/payments/webhook/`: PayPal webhook receiver. Configure the exact endpoint in the PayPal Developer Dashboard and set `PAYPAL_WEBHOOK_ID`. The endpoint verifies the transmission signature with PayPal before processing and stores event IDs for idempotency.
- `POST /api/admin/payments/<payment_id>/refund/`: full or partial refund. Optional JSON body: `{"amount":"10.00","reason":"..."}`. Omit `amount` to refund the remaining balance. Local refund totals and commission/earnings are updated only after PayPal confirms `COMPLETED`. A full refund revokes the course enrollment; a partial refund leaves access active.
- `GET /api/admin/paypal-disputes/`: dispute/chargeback inbox synchronized from verified PayPal dispute webhooks.
- `GET /api/admin/financial-report/`: currency-separated gross, refunded, net, net platform-fee, and trainer-share totals.
- `GET /api/admin/reconcile-payments/`: read-only comparison of up to 100 local captures against PayPal. Optional repeat query parameter: `?payment_id=123&payment_id=124`.

Do not expose or commit `backend/.env`. Use the sandbox webhook ID with sandbox credentials for local testing. For local webhook delivery, expose the development server through a trusted HTTPS tunnel and register that HTTPS URL in the PayPal sandbox app. Never disable signature verification in production.

### Payment verification status

The payment implementation was built in five phases: PayPal Checkout, capture and enrollment; refunds and financial management; trainer earnings and payouts; payment reliability and security; and deployment/integration readiness. This is not a claim of live PayPal certification: live sandbox/production transactions and browser-level end-to-end flows must still be verified with the actual PayPal app and deployment environment.

## Production limitations

The deployment files provide a production-oriented container baseline, not a security audit or a substitute for operational controls. Before public launch, configure external HTTPS termination, email verification and account recovery, upload size/type limits, malware scanning, object storage/video delivery, moderation/reporting, off-site backups, monitoring/alerting, accessibility testing, and browser-based end-to-end tests. Client-side elapsed times can be manipulated; use server-issued timing or per-question answer APIs for high-stakes competitions. Do not upload copyrighted course material unless you have permission to distribute it.

## License

Application code is released under the MIT License. User-uploaded educational content is not automatically relicensed by this software license; each contributor remains responsible for the rights and licenses associated with their content.
