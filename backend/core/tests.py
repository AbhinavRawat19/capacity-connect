from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
import tempfile

from .models import Course, Enrollment, CourseLesson, QuestionSubmission, Assessment, Attempt, QuestionPracticeRecord
from .ai_service import get_learning_recommendations
from .views import sync_assessment_questions_to_bank

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

    def test_question_bank_practice_updates_leaderboard_and_prevents_duplicate_points(self):
        self.client.force_authenticate(user=self.learner)
        first = self.client.post("/api/question-submissions/grade-practice/", {
            "answers": {str(self.question.id): 1}
        }, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["points_earned"], 10)
        second = self.client.post("/api/question-submissions/grade-practice/", {
            "answers": {str(self.question.id): 1}
        }, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["points_earned"], 0)
        self.assertEqual(QuestionPracticeRecord.objects.filter(trainee=self.learner, question=self.question).count(), 1)
        board = self.client.get("/api/leaderboard/")
        self.assertEqual(board.status_code, 200)
        learner_row = next(row for row in board.data["global"] if row["user_id"] == self.learner.id)
        self.assertEqual(learner_row["points"], 10)
        self.assertTrue(any(row["question_key"] == f"qb:{self.question.id}" for row in board.data["per_question"]))

    def test_trainer_can_publish_question_to_owned_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/question-submissions/", {
            "course": self.course.id,
            "question_text": "Trainer authored practice question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 2,
            "topic": "Regression",
            "difficulty": "beginner",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        created = QuestionSubmission.objects.get(question_text="Trainer authored practice question?")
        self.assertEqual(created.status, "approved")
        self.assertEqual(created.course_id, self.course.id)

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

    def test_assessment_questions_are_synced_to_question_bank(self):
        assessment = Assessment.objects.create(
            course=self.course, title="Sync Test", created_by=self.trainer,
            questions=[{"id": "legacy-q1", "text": "A question only in an assessment?",
                        "options": ["No", "Yes", "Maybe", "Later"], "correct_answer": 1}],
        )
        sync_assessment_questions_to_bank(assessment)
        assessment.refresh_from_db()
        linked_id = assessment.questions[0].get("question_bank_id")
        self.assertIsNotNone(linked_id)
        bank_question = QuestionSubmission.objects.get(pk=linked_id)
        self.assertEqual(bank_question.status, "approved")
        self.assertEqual(bank_question.question_text, "A question only in an assessment?")
        self.assertEqual(bank_question.correct_answer, 1)

    def test_assessment_question_not_in_bank_is_not_shown_in_per_question_leaderboard(self):
        assessment = Assessment.objects.create(
            course=self.course, title="Legacy Unsynced Quiz", created_by=self.trainer,
            questions=[{"id": "legacy-q2", "text": "Unlinked question?", "options": ["A", "B"], "correct_answer": 0}],
        )
        Attempt.objects.create(
            trainee=self.learner, assessment=assessment, score=100, total_questions=1,
            question_results={"legacy-q2": True}, question_timings={"legacy-q2": 1000}, points=15,
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/leaderboard/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(row["assessment_id"] == assessment.id for row in response.data["per_question"]))

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

    def test_admin_can_add_lecture_to_another_trainers_course(self):
        admin = User.objects.create_user(
            username="site_admin", password="StrongPass123!", role="admin", is_approved=True
        )
        self.client.force_authenticate(user=admin)
        response = self.client.post("/api/lessons/", {
            "course": self.course.id,
            "title": "Admin-added lecture",
            "description": "Published by administrator",
            "position": 1,
            "video_url": "https://example.com/lecture",
            "duration_minutes": 12,
            "is_preview": True,
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(CourseLesson.objects.filter(course=self.course, title="Admin-added lecture").exists())

    def test_trainer_cannot_add_lecture_to_another_trainers_course(self):
        other_trainer = User.objects.create_user(
            username="other_trainer_upload", password="StrongPass123!", role="trainer", is_approved=True
        )
        Course.objects.create(title="Other Trainer Course", description="Other course", trainer=other_trainer)
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/lessons/", {
            "course": Course.objects.get(title="Other Trainer Course").id,
            "title": "Should be denied",
            "video_url": "https://example.com/lecture",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_upload_video_file(self):
        admin = User.objects.create_user(
            username="video_admin", password="StrongPass123!", role="admin", is_approved=True
        )
        self.client.force_authenticate(user=admin)
        with tempfile.TemporaryDirectory() as media_dir, override_settings(MEDIA_ROOT=media_dir):
            video = SimpleUploadedFile("sample.mp4", b"fake-video-content", content_type="video/mp4")
            response = self.client.post("/api/lessons/", {
                "course": self.course.id,
                "title": "Uploaded video",
                "video_file": video,
            }, format="multipart")
            self.assertEqual(response.status_code, 201, response.data)
            lesson = CourseLesson.objects.get(title="Uploaded video")
            self.assertTrue(lesson.video_file.name)
            self.assertIn("video_file_url", response.data)

    def test_trainer_can_upload_video_file_to_owned_course(self):
        self.client.force_authenticate(user=self.trainer)
        with tempfile.TemporaryDirectory() as media_dir, override_settings(MEDIA_ROOT=media_dir):
            video = SimpleUploadedFile("trainer-sample.mp4", b"fake-video-content", content_type="video/mp4")
            response = self.client.post("/api/lessons/", {
                "course": self.course.id,
                "title": "Trainer uploaded video",
                "video_file": video,
            }, format="multipart")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertTrue(CourseLesson.objects.filter(title="Trainer uploaded video", course=self.course).exists())

    def test_learning_recommendations_use_popularity_when_no_interests(self):
        popular = Course.objects.create(title="Popular Course", description="Popular", trainer=self.trainer)
        less_popular = Course.objects.create(title="Less Popular Course", description="Less popular", trainer=self.trainer)
        another_learner = User.objects.create_user(
            username="enrolled_learner", password="StrongPass123!", role="trainee", is_approved=True
        )
        Enrollment.objects.create(trainee=self.learner, course=popular)
        Enrollment.objects.create(trainee=another_learner, course=popular)
        Enrollment.objects.create(trainee=self.learner, course=less_popular)
        self.learner.competencies = []
        self.learner.save(update_fields=["competencies"])
        result = get_learning_recommendations(self.learner, max_recommendations=5)
        self.assertGreaterEqual(len(result.recommendations), 2)
        self.assertEqual(result.recommendations[0].course_id, str(popular.id))
        self.assertTrue(any("popularity" in note.lower() for note in result.notes))

    def test_newly_published_course_is_in_recommendation_catalog(self):
        self.learner.competencies = []
        self.learner.save(update_fields=["competencies"])
        fresh_course = Course.objects.create(
            title="Fresh Published Course", description="New course", trainer=self.trainer, is_published=True
        )
        result = get_learning_recommendations(self.learner, max_recommendations=20)
        self.assertIn(str(fresh_course.id), [rec.course_id for rec in result.recommendations])
