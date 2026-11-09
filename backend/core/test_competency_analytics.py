from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .ai_service import get_learning_recommendations, parse_profile_skills
from .competency_analytics import analyze_observations
from .models import Assessment, Attempt, Course, User


class CompetencyTrendCalculationTests(SimpleTestCase):
    def observations(self, values):
        start = timezone.now() - timedelta(days=len(values))
        return [(start + timedelta(days=index), value) for index, value in enumerate(values)]

    def test_detects_improvement(self):
        result = analyze_observations("Python", self.observations([30, 35, 60, 70, 80, 90]))
        self.assertEqual(result["trend"], "improving")
        self.assertGreater(result["difference"], 5)

    def test_detects_decline(self):
        result = analyze_observations("Python", self.observations([90, 85, 70, 60, 40, 30]))
        self.assertEqual(result["trend"], "declining")

    def test_detects_stability(self):
        result = analyze_observations("Python", self.observations([70, 72, 71, 73, 72, 71]))
        self.assertEqual(result["trend"], "stable")

    def test_detects_inconsistent_performance(self):
        result = analyze_observations("Python", self.observations([10, 90, 15, 95, 20, 90]))
        self.assertEqual(result["trend"], "inconsistent")

    def test_insufficient_history_is_not_misclassified(self):
        result = analyze_observations("Python", self.observations([30, 90, 95]))
        self.assertEqual(result["trend"], "insufficient_data")
        self.assertIsNone(result["difference"])

    def test_invalid_scores_and_missing_timestamps_are_ignored(self):
        result = analyze_observations("Python", [
            (timezone.now(), 50), (timezone.now(), 120), (None, 80),
            (timezone.now(), "bad"),
        ])
        self.assertEqual(result["observations"], 1)
        self.assertEqual(result["trend"], "insufficient_data")

    def test_classifies_weak_and_strong_levels(self):
        weak = analyze_observations("A", self.observations([20, 25, 30, 35]))
        strong = analyze_observations("B", self.observations([85, 90, 92, 95]))
        self.assertEqual(weak["level"], "weak")
        self.assertEqual(strong["level"], "strong")


class CompetencyAnalyticsIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="analytics_learner", password="test-password",
            role="trainee", is_approved=True,
            competencies=[{"name": "Python", "current_score": 55, "target_score": 90}, "SQL"],
        )
        self.course = Course.objects.create(
            title="Python Foundations", description="Python course",
            competencies=["Python", "SQL"], is_published=True,
        )
        self.assessment = Assessment.objects.create(
            course=self.course, title="Python assessment", questions=[],
        )
        base = timezone.now() - timedelta(days=6)
        Attempt.objects.bulk_create([
            Attempt(trainee=self.user, assessment=self.assessment, score=30, submitted_at=base),
            Attempt(trainee=self.user, assessment=self.assessment, score=40, submitted_at=base + timedelta(days=1)),
            Attempt(trainee=self.user, assessment=self.assessment, score=70, submitted_at=base + timedelta(days=2)),
            Attempt(trainee=self.user, assessment=self.assessment, score=80, submitted_at=base + timedelta(days=3)),
            Attempt(trainee=self.user, assessment=self.assessment, score=90, submitted_at=base + timedelta(days=4)),
            Attempt(trainee=self.user, assessment=self.assessment, score=95, submitted_at=base + timedelta(days=5)),
        ])

    def test_explicit_profile_score_is_preserved_and_adaptive_score_is_separate(self):
        result = get_learning_recommendations(self.user)
        python = next(item for item in result.competency_trends if item["competency"] == "Python")
        self.assertEqual(python["profile_score"], 55)
        self.assertNotEqual(python["adaptive_score"], 55)
        self.assertTrue(result.adaptive_scoring["explicit_profile_scores_preserved"])
        # The profile value is preserved, while the request-local gap score is adaptive.
        python_gap = next(item for item in result.skill_gaps if item.skill_name == "Python")
        self.assertEqual(python_gap.current_score, python["adaptive_score"])

    def test_unscored_profile_skill_uses_assessment_derived_score(self):
        self.user.competencies = ["SQL"]
        self.user.save(update_fields=["competencies"])
        result = get_learning_recommendations(self.user)
        sql_gap = next(item for item in result.skill_gaps if item.skill_name == "SQL")
        self.assertGreater(sql_gap.current_score, 0)
        self.assertTrue(any(item["competency"] == "SQL" for item in result.competency_trends))

    def test_learning_analytics_reports_attempts_and_course_completion(self):
        result = get_learning_recommendations(self.user)
        self.assertEqual(result.learning_analytics["assessment_attempts"], 6)
        self.assertIsNotNone(result.learning_analytics["average_assessment_score"])
        self.assertEqual(result.learning_analytics["courses_enrolled"], 0)

    def test_empty_history_returns_safe_analytics(self):
        Attempt.objects.all().delete()
        result = get_learning_recommendations(self.user)
        self.assertEqual(result.learning_analytics["assessment_attempts"], 0)
        self.assertIsNone(result.learning_analytics["average_assessment_score"])
