"""Regression tests for the Part 1 + Part 2 integration through the database."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Course, User


class LearningIntelligenceIntegrationTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="li_learner", password="StrongPass123!", role="trainee", is_approved=True,
            competencies=[{"name": "Python", "current_score": 20, "target_score": 90}],
        )
        self.beginner = Course.objects.create(
            title="Python Basics", description="Start Python", category="Programming",
            level="beginner", competencies=["Python"], is_published=True,
        )
        self.intermediate = Course.objects.create(
            title="Python Intermediate", description="Next steps", category="Programming",
            level="intermediate", competencies=["Python"], is_published=True,
        )

    def test_import_that_previously_crashed_the_page(self):
        # ai_service imports infer_level_prerequisites from learning_intelligence.
        from .ai_service import infer_level_prerequisites  # noqa: F401

    def test_endpoint_returns_200_with_prerequisite_aware_path(self):
        client = APIClient()
        client.force_authenticate(self.learner)
        response = client.get("/api/ai/learning-intelligence/?limit=20")
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
        body = response.json()
        for key in ("recommendations", "learning_path", "competency_trends", "learning_analytics", "adaptive_scoring", "ranking_mode"):
            self.assertIn(key, body)
        rec = next(r for r in body["recommendations"] if r["course_id"] == str(self.intermediate.id))
        self.assertEqual(rec["unmet_prerequisites"], [str(self.beginner.id)])
        order = [step["course_id"] for step in body["learning_path"]]
        self.assertLess(order.index(str(self.beginner.id)), order.index(str(self.intermediate.id)))
        self.assertFalse(any("rating" in reason.lower() for r in body["recommendations"] for reason in r["reasons"]))

    def test_endpoint_requires_authentication_and_validates_limit(self):
        self.assertIn(APIClient().get("/api/ai/learning-intelligence/").status_code, (401, 403))
        client = APIClient()
        client.force_authenticate(self.learner)
        self.assertEqual(client.get("/api/ai/learning-intelligence/?limit=0").status_code, 400)
        self.assertEqual(client.get("/api/ai/learning-intelligence/?limit=abc").status_code, 400)
