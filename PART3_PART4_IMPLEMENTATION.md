# Capacity Connect — Parts 3 and 4 (final audited version)

## Part 3: AI Quiz Studio

- `POST /api/ai/quizzes/generate/` (trainers for their own courses, admins for any) creates an **unpublished** `Assessment` draft.
  Body: `course`, `title`, `topic`, `difficulty` (`beginner|intermediate|advanced`), `question_count` (1–20),
  optional `lessons` (list of lesson IDs to focus on), `duration_minutes`, `instructions`.
- Source material is the course description, skills, and lesson titles/descriptions (optionally only the chosen lessons) — nothing else.
  Courses without meaningful content are refused rather than padded.
- Output is validated: exactly N questions, 4 distinct options each, integer answer index 0–3, no duplicate questions. One automatic retry on malformed output.
  Questions use the platform's existing schema (`id`, `text`, `options`, `correct_answer`, `explanation`, `topic`).
- **Grading is server-side only** (`POST /api/assessments/{id}/submit/`). The client never submits a score; only answers for real question IDs are stored;
  duplicate submissions are blocked under a row lock; unpublished quizzes cannot be submitted.
- Learners never receive `correct_answer`, `explanation` or `question_bank_id` before submitting. The submit response then includes a per-question `review`
  (selected option, correct option, explanation).
- Attempts are visible only to their learner and the course's trainer/admins. Attempts feed the existing competency analytics.

## Part 4: AI Learning Assistant

- `GET /api/ai/status/` → `{configured: bool}` (no secrets).
- `GET/POST /api/ai/tutor/conversations/`, `GET/DELETE /api/ai/tutor/conversations/{id}/`, `POST /api/ai/tutor/conversations/{id}/messages/`.
- Ownership is part of every query: other users (admins included) get 404.
- Course context is limited to enrolled learners, the course trainer and admins, checked at creation **and on every message** — a learner who withdraws stops receiving course content (403).
- Each prompt contains: selected course/lesson material, the learner's own competency analytics (blended profile + quiz evidence, trends, weakest areas),
  and their recent quiz results including missed question text. Course text and learner data are marked as reference data, not instructions.
- Messages are stored together (transaction) only after the provider answers; provider failures store nothing.
- No offline/canned replies exist. Without `AI_API_KEY` the endpoints return 503.

## Provider configuration (server-side only)

| Variable | Purpose | Default |
|---|---|---|
| `AI_API_KEY` | secret key for an OpenAI-compatible Chat Completions API | required |
| `AI_BASE_URL` | provider base URL (http/https only) | `https://api.openai.com/v1` |
| `AI_MODEL` | model name | `gpt-4o-mini` |
| `AI_TIMEOUT_SECONDS` | provider timeout | `45` |
| `API_AI_RATE` | per-user rate limit for AI endpoints | `60/hour` |

Provider errors map to safe messages (401/403 → 502 "credentials rejected", 429 → 503, timeouts → 503, other → 502). Keys are never returned or logged.

## Database

`0014_tutordata.py` adds `TutorConversation` and `TutorMessage`. Run `python manage.py migrate`.

## Changes in this final pass

1. **Blank AI questions fixed**: generated questions used a `question` key, but the learner UI, grader and question-bank sync read `text`.
2. **Answer leak via Question Bank closed**: assessment questions are mirrored into the bank, and `grade-practice` reveals answers. Bank items linked to an assessment the
   learner has not attempted are now hidden from the learner's bank list and rejected by `grade-practice`. `question_bank_id` and `explanation` are stripped from learner assessment payloads.
3. Prompt context was joined with literal `\n` text; fixed. Source text now includes skills, level and ordered lessons.
4. Tutor now re-checks course access on each message (withdrawn learners), uses real competency analytics and quiz performance, and persists atomically.
5. Provider layer: HTTP-status handling, key redaction in logs, scheme check on `AI_BASE_URL`, fenced-JSON tolerance, retry, configurable timeout.
6. Rate limiting for AI endpoints (`AIRateThrottle`); assessment question validation on create/update; submit grading hardened and returns a review.
7. Frontend: Quiz Studio uses the right fields, lecture focus, discard/publish, trainer-only course list; Tutor has loading/error states, optimistic send with rollback,
   enrolled-course selector; quiz results now show explanations; "not configured" banner.

## Known limits

- MCQs only; lesson files/video transcripts are not ingested (title/description text only).
- A learner could paste a quiz they are currently taking into the tutor; the prompt instructs it to guide rather than answer, but this cannot be enforced technically.
- AG Grid is used only for the admin User management table (`frontend/src/AdminUsersGrid.jsx`).
- Bank questions linked to quizzes are unavailable for practice until the learner attempts the quiz (deliberate).
