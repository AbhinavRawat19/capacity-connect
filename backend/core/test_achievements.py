from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from .achievements import compute_streaks
from .models import (
    Assessment, Attempt, Course, Enrollment, QuestionPracticeRecord, QuestionSubmission, User,
)

TODAY = date(2026, 11, 10)


def days_ago(*offsets):
    return {TODAY - timedelta(days=n) for n in offsets}


class StreakMathTests(SimpleTestCase):
    def test_no_activity(self):
        self.assertEqual(compute_streaks(set(), TODAY), (0, 0))

    def test_single_day_today(self):
        self.assertEqual(compute_streaks(days_ago(0), TODAY), (1, 1))

    def test_consecutive_days_ending_today(self):
        self.assertEqual(compute_streaks(days_ago(0, 1, 2, 3), TODAY), (4, 4))

    def test_streak_stays_alive_if_last_activity_was_yesterday(self):
        self.assertEqual(compute_streaks(days_ago(1, 2), TODAY), (2, 2))

    def test_streak_resets_after_a_missed_day(self):
        self.assertEqual(compute_streaks(days_ago(2, 3, 4), TODAY), (0, 3))

    def test_longest_is_kept_when_current_is_shorter(self):
        self.assertEqual(compute_streaks(days_ago(0, 1, 5, 6, 7, 8), TODAY), (2, 4))


class AchievementsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.trainer = User.objects.create_user("ach_trainer", password="StrongPass123!", role="trainer", is_approved=True)
        self.learner = User.objects.create_user("ach_learner", password="StrongPass123!", role="trainee", is_approved=True)
        self.course = Course.objects.create(title="Ach Course", description="d", trainer=self.trainer, is_published=True)
        self.quiz = Assessment.objects.create(
            course=self.course, title="Quiz", created_by=self.trainer,
            questions=[{"id": "q1", "text": "Q?", "options": ["A", "B"], "correct_answer": 0}],
        )
        Enrollment.objects.create(trainee=self.learner, course=self.course)

    def _get(self, user=None):
        self.client.force_authenticate(user=user or self.learner)
        return self.client.get("/api/achievements/")

    def test_requires_login(self):
        self.assertIn(APIClient().get("/api/achievements/").status_code, (401, 403))

    def test_brand_new_learner_starts_at_level_one_with_no_badges(self):
        data = self._get().data
        self.assertEqual((data["xp"], data["level"], data["earned_count"]), (0, 1, 0))
        self.assertEqual(data["streak"], {"current": 0, "longest": 0, "active_today": False})
        self.assertEqual(len(data["last_14_days"]), 14)
        self.assertTrue(all(not b["earned"] for b in data["badges"]))

    def test_first_perfect_quiz_earns_badges_streak_and_certificate(self):
        Attempt.objects.create(trainee=self.learner, assessment=self.quiz, score=100, total_questions=1,
                               question_results={"q1": True}, points=15)
        data = self._get().data
        earned = {b["key"] for b in data["badges"] if b["earned"]}
        self.assertTrue({"first_quiz", "perfect_score", "certified"} <= earned)
        self.assertNotIn("quiz_regular", earned)
        self.assertEqual(data["xp"], 15)
        self.assertEqual(data["streak"]["current"], 1)
        self.assertTrue(data["streak"]["active_today"])
        self.assertTrue(data["last_14_days"][-1]["active"])

    def test_badge_progress_is_reported(self):
        Attempt.objects.create(trainee=self.learner, assessment=self.quiz, score=50, total_questions=1, points=0)
        regular = next(b for b in self._get().data["badges"] if b["key"] == "quiz_regular")
        self.assertEqual((regular["current"], regular["target"], regular["earned"]), (1, 5, False))

    def test_xp_matches_the_leaderboard_points(self):
        Attempt.objects.create(trainee=self.learner, assessment=self.quiz, score=100, total_questions=1,
                               question_results={"q1": True}, points=25)
        bank = QuestionSubmission.objects.create(
            submitted_by=self.trainer, course=self.course, question_text="Bank?", options=["A", "B", "C", "D"],
            correct_answer=0, status="approved",
        )
        QuestionPracticeRecord.objects.create(trainee=self.learner, question=bank, submitted_answer=0, is_correct=True, points_earned=10)
        QuestionSubmission.objects.create(
            submitted_by=self.learner, course=self.course, question_text="Mine?", options=["A", "B", "C", "D"],
            correct_answer=1, status="approved",
        )
        xp = self._get().data["xp"]
        self.assertEqual(xp, 25 + 10 + 5)
        board = self.client.get("/api/leaderboard/").data["global"]
        row = next(r for r in board if r["user_id"] == self.learner.id)
        self.assertEqual(row["points"], xp)

    def test_level_rolls_over_every_100_xp(self):
        Attempt.objects.create(trainee=self.learner, assessment=self.quiz, score=100, total_questions=1, points=250)
        data = self._get().data
        self.assertEqual((data["level"], data["level_xp"]), (3, 50))
