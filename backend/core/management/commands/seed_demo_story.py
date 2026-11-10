"""Make the demo data tell a story: streaks, levels, a leaderboard with history, and a paid course.

Run from backend/:  python manage.py seed_demo_story
Safe to run repeatedly. It does NOT create payments, refunds or payouts: buy the premium course
with a PayPal sandbox buyer during the demo so the money flow is real.

It builds on `seed_student_data` (run automatically) and adds:
  - a paid "Premium" course with lectures and a quiz, ready for a live sandbox purchase
  - quiz attempts spread over the last days instead of all being "today"
  - Question Bank practice on past days, so learners have different streaks and XP levels
  - repair of attempts stored in the old seed shape (counts instead of percents)
"""
import io
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.achievements import _active_days, compute_streaks
from core.models import (
    AssignmentSubmission, Assessment, Attempt, Course, CourseDiscussion, CourseLesson,
    QuestionPracticeRecord, QuestionSubmission, User,
)

PREMIUM_TITLE = "Incident Response Playbook (Premium)"
PREMIUM_PRICE = Decimal("9.99")

PREMIUM_LESSONS = [
    ("Detecting an incident", "Recognise the signals that something has gone wrong and who to tell first.", 1, 14),
    ("Containment and recovery", "Limit the damage, restore service and preserve evidence.", 2, 18),
    ("Writing the post-incident review", "Turn what happened into lessons the team will actually use.", 3, 15),
]
PREMIUM_QUIZ = ("Incident Response Check", [
    {"id": "ir1", "text": "What is the first priority when you suspect an active incident?", "options": ["Delete all logs", "Contain it and notify the response team", "Post about it publicly", "Wait and see"], "correct_answer": 1, "explanation": "Containing the incident and alerting the right people limits damage."},
    {"id": "ir2", "text": "Why preserve evidence during recovery?", "options": ["It is optional", "To understand root cause and support any investigation", "To slow the team down", "To fill storage"], "correct_answer": 1, "explanation": "Evidence shows how the incident happened and what was affected."},
    {"id": "ir3", "text": "A good post-incident review is…", "options": ["Blame-focused", "Skipped if the fix was quick", "Blameless and focused on improvements", "Kept secret from the team"], "correct_answer": 2, "explanation": "Blameless reviews encourage honesty and lead to real fixes."},
])

# Days ago on which each existing seeded quiz attempt happened.
ATTEMPT_DAYS_AGO = {
    ("student_aarav", "Python Programming: Zero to One"): 5,
    ("student_isha", "Cybersecurity Fundamentals"): 6,
    ("student_isha", "Python Programming: Zero to One"): 3,
    ("student_riya", "Practical Data Analysis with Python"): 2,
    ("student_riya", "SQL and Database Essentials"): 8,
    ("student_karan", "SQL and Database Essentials"): 1,
    ("student_ananya", "Python Programming: Zero to One"): 7,
    ("student_ananya", "Cybersecurity Fundamentals"): 4,
}

# Seeded assignment submissions and discussion posts are re-dated too, otherwise they would all
# count as activity "today" and flatten the streaks below. Chosen so they never bridge a gap.
OTHER_ACTIVITY_DAYS_AGO = {
    "student_ananya": 5, "student_isha": 5, "student_riya": 10, "student_karan": 9, "student_aarav": 6,
}

# Days ago on which each learner practised Question Bank questions: this drives streaks and XP.
PRACTICE_DAYS_AGO = {
    "student_ananya": [0, 1, 2, 3, 4, 5, 6, 7, 8],   # 9-day streak, the star learner
    "student_isha": [0, 1, 2, 3],                     # 4-day streak
    "student_riya": [1, 2, 5, 6, 7],                  # 2-day live streak, longest 3
    "student_karan": [0],                             # just started
    "student_aarav": [2, 3],                          # streak lapsed: "study today" nudge
}


class Command(BaseCommand):
    help = "Seed a demo story: streaks, levels, spread-out history and a paid premium course."

    def handle(self, *args, **options):
        quiet = io.StringIO()
        call_command("seed_student_data", stdout=quiet)
        trainer = User.objects.get(username="demo_trainer")

        self._premium_course(trainer)
        call_command("sync_assessment_questions", stdout=quiet)  # link every quiz question to the bank

        repaired = self._repair_legacy_attempts()
        moved = self._spread_attempts() + self._spread_other_activity()
        practised = self._practice_history()

        self.stdout.write(self.style.SUCCESS("Demo story is ready."))
        self.stdout.write(f"  Repaired legacy-shape attempts: {repaired} | attempts re-dated: {moved} | practice answers added: {practised}")
        self.stdout.write(f"  Paid course for a live PayPal sandbox purchase: '{PREMIUM_TITLE}' (USD {PREMIUM_PRICE})")
        today = timezone.localdate()
        self.stdout.write("  Streaks:")
        for username in PRACTICE_DAYS_AGO:
            user = User.objects.get(username=username)
            current, longest = compute_streaks(_active_days(user), today)
            self.stdout.write(f"    {username:<15} current {current}, longest {longest}")
        self.stdout.write("  Log in as student_ananya (password DemoPass123!) and open My progress.")

    def _premium_course(self, trainer):
        course, _ = Course.objects.get_or_create(
            title=PREMIUM_TITLE,
            defaults={
                "category": "Cybersecurity", "level": "intermediate", "duration_hours": 5,
                "description": "A practical playbook for detecting, containing and learning from security incidents.",
                "competencies": ["Cybersecurity", "Incident response"], "trainer": trainer,
                "is_published": True, "price": PREMIUM_PRICE, "currency": "USD",
            },
        )
        for title, description, position, minutes in PREMIUM_LESSONS:
            CourseLesson.objects.get_or_create(
                course=course, title=title,
                defaults={"description": description, "position": position, "duration_minutes": minutes,
                          "is_preview": position == 1, "video_url": ""},
            )
        quiz_title, questions = PREMIUM_QUIZ
        Assessment.objects.get_or_create(
            course=course, title=quiz_title,
            defaults={"instructions": "Choose the best answer for each question.", "duration_minutes": 10,
                      "questions": questions, "created_by": trainer, "is_published": True},
        )
        return course

    def _repair_legacy_attempts(self):
        """Older seeds stored `score` as a count and `question_results` as {id: {correct: bool}}.
        The app expects a percent score and {id: bool}. Fix only rows still in the old shape."""
        fixed = 0
        for attempt in Attempt.objects.all():
            results = attempt.question_results or {}
            if not any(isinstance(v, dict) for v in results.values()):
                continue
            normalised = {k: bool(v.get("correct")) if isinstance(v, dict) else bool(v) for k, v in results.items()}
            total = attempt.total_questions or len(normalised) or 1
            correct = sum(normalised.values())
            attempt.question_results = normalised
            attempt.score = round(correct / total * 100, 2)
            attempt.points = correct * 10
            attempt.save(update_fields=["question_results", "score", "points"])
            fixed += 1
        return fixed

    def _spread_attempts(self):
        now = timezone.now()
        moved = 0
        for (username, course_title), days_ago in ATTEMPT_DAYS_AGO.items():
            attempt = Attempt.objects.filter(trainee__username=username, assessment__course__title=course_title).first()
            if not attempt:
                continue
            stamp = now - timedelta(minutes=5) if days_ago == 0 else self._at(timezone.localdate() - timedelta(days=days_ago), 15)
            Attempt.objects.filter(pk=attempt.pk).update(submitted_at=stamp)  # auto_now_add: only update() can change it
            moved += 1
        return moved

    def _spread_other_activity(self):
        moved = 0
        for username, days_ago in OTHER_ACTIVITY_DAYS_AGO.items():
            stamp = self._at(timezone.localdate() - timedelta(days=days_ago), 13)
            moved += AssignmentSubmission.objects.filter(learner__username=username).update(submitted_at=stamp)
            moved += CourseDiscussion.objects.filter(author__username=username).update(created_at=stamp, updated_at=stamp)
        return moved

    def _practice_history(self):
        today = timezone.localdate()
        approved = list(QuestionSubmission.objects.filter(status="approved").order_by("id"))
        added = 0
        for index, (username, offsets) in enumerate(PRACTICE_DAYS_AGO.items()):
            learner = User.objects.filter(username=username).first()
            if not learner or not approved:
                continue
            done_days = {timezone.localtime(r.updated_at).date() for r in QuestionPracticeRecord.objects.filter(trainee=learner)}
            for offset in offsets:
                day = today - timedelta(days=offset)
                if day in done_days:
                    continue
                practised = set(QuestionPracticeRecord.objects.filter(trainee=learner).values_list("question_id", flat=True))
                question = next((q for q in approved if q.id not in practised and q.submitted_by_id != learner.id), None)
                if question is None:
                    break
                correct = (offset + index) % 3 != 0  # mostly right, sometimes wrong
                answer = question.correct_answer if correct else (question.correct_answer + 1) % max(1, len(question.options))
                stamp = timezone.now() - timedelta(minutes=3) if offset == 0 else self._at(day, 10 + index)
                record = QuestionPracticeRecord.objects.create(
                    trainee=learner, question=question, submitted_answer=answer, is_correct=correct,
                    points_earned=10 if correct else 0, first_correct_at=stamp if correct else None,
                )
                QuestionPracticeRecord.objects.filter(pk=record.pk).update(updated_at=stamp)  # auto_now
                added += 1
                done_days.add(day)
        return added

    @staticmethod
    def _at(day, hour):
        return timezone.make_aware(datetime.combine(day, time(hour % 24, 20)))
