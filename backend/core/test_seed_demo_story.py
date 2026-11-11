import io
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .achievements import _active_days, compute_streaks
from .models import Assessment, Attempt, Course, CourseLesson, Payment, QuestionPracticeRecord, User


def run_story():
    out = io.StringIO()
    call_command("seed_demo_story", stdout=out)
    return out.getvalue()


def streak(username):
    user = User.objects.get(username=username)
    return compute_streaks(_active_days(user), timezone.localdate())


class SeedDemoStoryTests(TestCase):
    def test_creates_paid_premium_course_with_quiz_and_no_payments(self):
        run_story()
        course = Course.objects.get(title="Incident Response Playbook (Premium)")
        self.assertEqual(course.price, Decimal("9.99"))
        self.assertTrue(course.is_published)
        self.assertEqual(CourseLesson.objects.filter(course=course).count(), 3)
        quiz = Assessment.objects.get(course=course)
        self.assertTrue(all(q.get("question_bank_id") for q in quiz.questions))  # linked to the bank
        self.assertEqual(Payment.objects.count(), 0)  # money flow must stay real

    def test_learners_get_the_designed_streaks(self):
        run_story()
        self.assertEqual(streak("student_ananya"), (9, 9))
        self.assertEqual(streak("student_isha"), (4, 4))
        self.assertEqual(streak("student_riya"), (2, 4))
        self.assertEqual(streak("student_karan"), (2, 2))
        self.assertEqual(streak("student_aarav"), (0, 2))  # lapsed

    def test_star_learner_has_levelled_up_and_earned_streak_badges(self):
        run_story()
        client = APIClient()
        client.force_authenticate(user=User.objects.get(username="student_ananya"))
        data = client.get("/api/achievements/").data
        earned = {b["key"] for b in data["badges"] if b["earned"]}
        self.assertTrue({"streak_3", "streak_7", "first_quiz", "certified", "century"} <= earned)
        self.assertGreaterEqual(data["level"], 2)
        board = client.get("/api/leaderboard/").data["global"]
        ananya_id = User.objects.get(username="student_ananya").id
        self.assertEqual(board[0]["user_id"], ananya_id)  # the star learner leads the leaderboard
        self.assertEqual(board[0]["points"], data["xp"])  # and XP equals leaderboard points

    def test_running_twice_changes_nothing(self):
        run_story()
        snapshot = (
            QuestionPracticeRecord.objects.count(), Attempt.objects.count(), Course.objects.count(),
            streak("student_ananya"), streak("student_aarav"),
        )
        output = run_story()
        self.assertEqual(snapshot, (
            QuestionPracticeRecord.objects.count(), Attempt.objects.count(), Course.objects.count(),
            streak("student_ananya"), streak("student_aarav"),
        ))
        self.assertIn("practice answers added: 0", output)

    def test_legacy_shape_attempts_are_repaired(self):
        run_story()
        attempt = Attempt.objects.filter(trainee__username="student_isha").first()
        # Put one attempt back into the old seed shape: score is a count, results are dicts.
        Attempt.objects.filter(pk=attempt.pk).update(
            score=3, total_questions=4,
            question_results={"a": {"correct": True}, "b": {"correct": True}, "c": {"correct": True}, "d": {"correct": False}},
        )
        run_story()
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 75.0)
        self.assertEqual(attempt.question_results, {"a": True, "b": True, "c": True, "d": False})
        self.assertEqual(attempt.points, 30)
