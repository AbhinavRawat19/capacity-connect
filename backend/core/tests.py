from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Course, QuestionSubmission, Assessment, Attempt

User = get_user_model()


class CapacityConnectFixRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.trainer = User.objects.create_user(
            username="trainer_owner", password="StrongPass123!", role="trainer", is_approved=True
        )
        self.course = Course.objects.create(
            title="Regression Test Course", description="Test course", trainer=self.trainer
        )
        self.learner = User.objects.create_user(
            username="learner_test", password="StrongPass123!", role="trainee", is_approved=True
        )
        self.question = QuestionSubmission.objects.create(
            submitted_by=self.trainer,
            course=self.course,
            question_text="Which option is correct?",
            options=["A", "B", "C", "D"],
            correct_answer=1,
            explanation="B is correct.",
            status="approved",
        )

    def test_trainer_registration_requires_admin_approval(self):
        response = self.client.post("/api/auth/register/", {
            "username": "pending_trainer", "email": "pending@example.com",
            "password": "StrongPass123!", "role": "trainer",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        account = User.objects.get(username="pending_trainer")
        self.assertEqual(account.role, "trainer")
        self.assertFalse(account.is_approved)

    def test_become_trainer_request_remains_pending(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/auth/become-trainer/", {}, format="json")
        self.learner.refresh_from_db()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.learner.role, "trainer")
        self.assertFalse(self.learner.is_approved)

    def test_learner_registration_is_automatically_approved(self):
        response = self.client.post("/api/auth/register/", {
            "username": "new_learner", "email": "learner@example.com",
            "password": "StrongPass123!", "role": "trainee",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.get(username="new_learner").is_approved)

    def test_question_bank_hides_answer_until_practice_submission(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/question-submissions/")
        question = next(row for row in response.data if row["id"] == self.question.id)
        self.assertNotIn("correct_answer", question)
        graded = self.client.post("/api/question-submissions/grade-practice/", {
            "answers": {str(self.question.id): 1}
        }, format="json")
        self.assertEqual(graded.status_code, 200)
        self.assertEqual(graded.data["correct"], 1)
        self.assertEqual(graded.data["results"][0]["correct_answer"], 1)

    def test_learner_can_edit_and_delete_own_pending_question(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/question-submissions/", {
            "course": self.course.id,
            "question_text": "A new pending question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 0,
            "topic": "Regression",
            "difficulty": "beginner",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        question_id = response.data["submission"]["id"]
        edited = self.client.patch(f"/api/question-submissions/{question_id}/", {
            "question_text": "An edited pending question?"
        }, format="json")
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.data["question_text"], "An edited pending question?")
        deleted = self.client.delete(f"/api/question-submissions/{question_id}/")
        self.assertEqual(deleted.status_code, 204)

    def test_trainer_review_queue_is_limited_to_owned_courses(self):
        other_trainer = User.objects.create_user(
            username="other_trainer", password="StrongPass123!", role="trainer", is_approved=True
        )
        other_course = Course.objects.create(
            title="Another Course", description="Not owned by this trainer", trainer=other_trainer
        )
        other_question = QuestionSubmission.objects.create(
            submitted_by=self.learner, course=other_course,
            question_text="Question from another course?", options=["A", "B", "C", "D"],
            correct_answer=0, status="pending",
        )
        own_question = QuestionSubmission.objects.create(
            submitted_by=self.learner, course=self.course,
            question_text="Question from owned course?", options=["A", "B", "C", "D"],
            correct_answer=0, status="pending",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get("/api/question-submissions/?status=pending")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data]
        self.assertIn(own_question.id, ids)
        self.assertNotIn(other_question.id, ids)

    def test_leaderboard_excludes_trainer_accounts(self):
        assessment = Assessment.objects.create(
            course=self.course, title="Test quiz", created_by=self.trainer,
            questions=[{"id": "1", "text": "Q?", "options": ["A", "B", "C", "D"], "correct_answer": 0}],
        )
        Attempt.objects.create(
            trainee=self.trainer, assessment=assessment, score=100,
            total_questions=1, question_results={"1": True}, points=10,
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/leaderboard/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.trainer.id, [row["user_id"] for row in response.data["global"]])
