# CAPACITY CONNECT

**A free, community-powered open learning platform.** Anyone can register as a learner or trainer, publish free courses, share lectures and resources, set assignments and quizzes, and learn together. There are no course fees, teaching fees, commissions, or paid course listings.

## Features in this MVP

- **Open registration:** users can register as learners or trainers. Accounts are active immediately.
- **Free course catalogue:** trainers create courses with category, difficulty, tags/competencies, and estimated duration. Learners can browse and enroll at no cost.
- **Lecture studio:** add video links or upload lecture files; attach PDFs and other resources; mark preview lessons.
- **Quizzes and scoring:** trainers create MCQ assessments; Django grades answers, records attempts, and calculates points and capped speed bonuses. No separate scoring service is needed.
- **Leaderboards:** global rankings and per-question rankings, with correctness as the priority and speed as a capped bonus.
- **Community question bank:** learners submit MCQs for trainer/admin review; approved questions are published with contributor attribution.
- **Assignments:** trainers publish instructions, deadlines, rubrics, and files; learners submit text, links, or attachments; trainers grade submissions and provide feedback.
- **Course discussions:** enrolled learners and course trainers can share messages.
- **Learning progress:** enrollment library, quiz history, points, and contribution history.
- **Admin tools:** Django admin, user management, and platform overview.
- **No AI or payments:** AI can be added later. Payment and monetization features are intentionally excluded.

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

## Optional: PostgreSQL and Docker

SQLite is suitable for local development and keeps the setup light. If you later want PostgreSQL, set `DATABASE_URL` in the environment to a valid PostgreSQL connection string and install/configure PostgreSQL. Docker Compose is included as an optional convenience, not a requirement. If using Docker Compose, copy `.env.example` to `.env`, set a strong secret and database password, then run:

```bash
docker compose up --build
```

Create an administrator in another terminal with:

```bash
docker compose exec backend python manage.py createsuperuser
```

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

## Before public launch

This is a development MVP, not a security-audited production service. Before opening it to the public, add HTTPS, email verification and account recovery, stronger API throttling, upload size/type limits, malware scanning, production object storage/video delivery, moderation/reporting policies, backups, monitoring, accessibility testing, and automated end-to-end tests. Client-side elapsed times can be manipulated; use server-issued timing or per-question answer APIs for high-stakes competitions. Do not upload copyrighted course material unless you have permission to distribute it.

## License

Application code is released under the MIT License. User-uploaded educational content is not automatically relicensed by this software license; each contributor remains responsible for the rights and licenses associated with their content.
