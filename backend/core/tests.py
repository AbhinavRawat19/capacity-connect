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
from unittest.mock import patch
from decimal import Decimal

from core.models import User, Course, Payment, Enrollment, Payout, PayPalDispute

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



# ---------------------------------------------------------------------------
# Comprehensive API test suite covering all untested endpoints and scenarios.
# ---------------------------------------------------------------------------
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from .models import (
    Course, Enrollment, CourseLesson, QuestionSubmission, Assessment, Attempt,
    QuestionPracticeRecord, Assignment, AssignmentSubmission, CourseDiscussion, Payment,
)


class CapacityConnectFullAPITests(TestCase):
    """Exhaustive test coverage for every API endpoint not already covered by
    CapacityConnectFixRegressionTests."""

    def setUp(self):
        self.client = APIClient()

        # Admin (non-superuser admin role)
        self.admin = User.objects.create_user(
            username="api_admin", password="StrongPass123!",
            role="admin", is_approved=True,
        )
        # Superuser
        self.superuser = User.objects.create_superuser(
            username="su_admin", password="StrongPass123!", email="su@example.com",
        )
        # Approved trainer
        self.trainer = User.objects.create_user(
            username="api_trainer", password="StrongPass123!",
            role="trainer", is_approved=True,
        )
        # Second approved trainer
        self.trainer2 = User.objects.create_user(
            username="api_trainer2", password="StrongPass123!",
            role="trainer", is_approved=True,
        )
        # Approved learner
        self.learner = User.objects.create_user(
            username="api_learner", password="StrongPass123!",
            role="trainee", is_approved=True, first_name="Learner", last_name="One",
        )
        # Second approved learner
        self.learner2 = User.objects.create_user(
            username="api_learner2", password="StrongPass123!",
            role="trainee", is_approved=True,
        )
        # Unapproved trainer (pending)
        self.unapproved = User.objects.create_user(
            username="unapproved_user", password="StrongPass123!",
            role="trainer", is_approved=False,
        )

        # Courses
        self.course = Course.objects.create(
            title="Full API Test Course", description="A free published course",
            trainer=self.trainer, is_published=True, price=0,
        )
        self.unpublished_course = Course.objects.create(
            title="Unpublished Course", description="Draft course",
            trainer=self.trainer, is_published=False,
        )
        self.paid_course = Course.objects.create(
            title="Paid Course", description="Costs money",
            trainer=self.trainer, is_published=True, price=Decimal("19.99"),
        )
        self.course2 = Course.objects.create(
            title="Trainer2 Course", description="Owned by trainer2",
            trainer=self.trainer2, is_published=True, price=0,
        )

        # Lessons
        self.preview_lesson = CourseLesson.objects.create(
            course=self.course, title="Preview Lesson", position=1,
            is_preview=True, video_url="https://example.com/preview",
        )
        self.regular_lesson = CourseLesson.objects.create(
            course=self.course, title="Regular Lesson", position=2,
            is_preview=False, video_url="https://example.com/regular",
        )

        # Assessment with future deadline
        self.assessment = Assessment.objects.create(
            course=self.course, title="Test Assessment", created_by=self.trainer,
            questions=[
                {"id": "q1", "text": "What is 2+2?", "options": ["3", "4", "5", "6"], "correct_answer": 1},
                {"id": "q2", "text": "What color is the sky?", "options": ["Red", "Blue", "Green", "Yellow"], "correct_answer": 1},
            ],
            deadline=timezone.now() + timedelta(days=7),
        )

        # Enrollment for learner in self.course
        self.enrollment = Enrollment.objects.create(trainee=self.learner, course=self.course)

    # ── Auth & User Management ──────────────────────────────────────────

    def test_login_with_valid_credentials(self):
        response = self.client.post("/api/auth/token/", {
            "username": "api_learner", "password": "StrongPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_with_invalid_credentials(self):
        response = self.client.post("/api/auth/token/", {
            "username": "api_learner", "password": "WrongPassword!",
        }, format="json")
        self.assertEqual(response.status_code, 401)

    def test_get_me_returns_user_profile(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "api_learner")
        self.assertEqual(response.data["role"], "trainee")
        self.assertIn("competencies", response.data)

    def test_patch_me_updates_profile_fields(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.patch("/api/auth/me/", {
            "first_name": "Updated", "last_name": "Name",
            "bio": "New bio", "competencies": ["Python", "Django"],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Updated")
        self.assertEqual(response.data["last_name"], "Name")
        self.assertEqual(response.data["bio"], "New bio")
        self.assertEqual(response.data["competencies"], ["Python", "Django"])

    def test_trainer_can_set_paypal_email(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch("/api/auth/me/", {
            "paypal_email": "trainer@paypal.com",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.trainer.refresh_from_db()
        self.assertEqual(self.trainer.paypal_email, "trainer@paypal.com")

    def test_learner_cannot_set_paypal_email(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.patch("/api/auth/me/", {
            "paypal_email": "learner@paypal.com",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.learner.refresh_from_db()
        # paypal_email should remain empty because the field is not in allowed for learners
        self.assertEqual(self.learner.paypal_email, "")

    def test_unapproved_user_denied_access(self):
        self.client.force_authenticate(user=self.unapproved)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 403)

    def test_register_with_admin_role_rejected(self):
        response = self.client.post("/api/auth/register/", {
            "username": "sneaky_admin", "email": "sneaky@example.com",
            "password": "StrongPass123!", "role": "admin",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_register_with_duplicate_username_fails(self):
        response = self.client.post("/api/auth/register/", {
            "username": "api_learner", "email": "dup@example.com",
            "password": "StrongPass123!", "role": "trainee",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    # ── Course CRUD ─────────────────────────────────────────────────────

    def test_trainer_can_create_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/courses/", {
            "title": "New Trainer Course",
            "description": "Created by trainer",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Course.objects.filter(title="New Trainer Course", trainer=self.trainer).exists())

    def test_learner_cannot_create_course(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/courses/", {
            "title": "Learner Course",
            "description": "Should fail",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_trainer_can_update_own_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch(f"/api/courses/{self.course.id}/", {
            "title": "Updated Course Title",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "Updated Course Title")

    def test_trainer_cannot_update_another_trainers_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch(f"/api/courses/{self.course2.id}/", {
            "title": "Hijacked",
        }, format="json")
        # Trainer queryset filters to own courses for update actions → 404
        self.assertIn(response.status_code, [403, 404])

    def test_trainer_can_delete_own_course(self):
        self.client.force_authenticate(user=self.trainer)
        deletable = Course.objects.create(
            title="Deletable", description="To be deleted", trainer=self.trainer,
        )
        response = self.client.delete(f"/api/courses/{deletable.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Course.objects.filter(pk=deletable.id).exists())

    def test_admin_can_view_all_courses(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/courses/")
        self.assertEqual(response.status_code, 200)
        titles = [c["title"] for c in response.data]
        # Admin sees published AND unpublished
        self.assertIn("Unpublished Course", titles)
        self.assertIn("Full API Test Course", titles)

    def test_learner_only_sees_published_courses(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/courses/")
        self.assertEqual(response.status_code, 200)
        titles = [c["title"] for c in response.data]
        self.assertNotIn("Unpublished Course", titles)
        self.assertIn("Full API Test Course", titles)

    def test_free_course_enrollment_works(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.post(f"/api/courses/{self.course.id}/enroll/")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Enrollment.objects.filter(trainee=self.learner2, course=self.course).exists())

    def test_paid_course_enrollment_blocked(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.post(f"/api/courses/{self.paid_course.id}/enroll/")
        self.assertEqual(response.status_code, 402)

    def test_duplicate_enrollment_returns_200(self):
        self.client.force_authenticate(user=self.learner)
        # Already enrolled in setUp
        response = self.client.post(f"/api/courses/{self.course.id}/enroll/")
        self.assertEqual(response.status_code, 200)

    def test_admin_cannot_enroll(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/courses/{self.course.id}/enroll/")
        self.assertEqual(response.status_code, 403)

    # ── Course Withdraw & Rejoin ────────────────────────────────────────

    def test_learner_can_withdraw_from_course(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/courses/{self.course.id}/withdraw/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Enrollment.objects.filter(trainee=self.learner, course=self.course).exists())

    def test_non_learner_cannot_withdraw(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/courses/{self.course.id}/withdraw/")
        self.assertEqual(response.status_code, 403)

    def test_withdraw_from_unenrolled_course_returns_404(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.post(f"/api/courses/{self.course.id}/withdraw/")
        self.assertEqual(response.status_code, 404)

    def test_rejoin_after_withdrawal_with_previous_payment(self):
        # Simulate a previous captured payment
        Payment.objects.create(
            learner=self.learner, course=self.paid_course,
            paypal_order_id="REJOIN-TEST-001", paypal_capture_id="CAP-001",
            gross_amount=Decimal("19.99"), platform_fee=Decimal("0.20"),
            trainer_share=Decimal("19.79"), status="captured",
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/courses/{self.paid_course.id}/rejoin/")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Enrollment.objects.filter(trainee=self.learner, course=self.paid_course).exists())

    def test_rejoin_without_payment_returns_402(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.post(f"/api/courses/{self.paid_course.id}/rejoin/")
        self.assertEqual(response.status_code, 402)

    def test_non_learner_cannot_rejoin(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/courses/{self.paid_course.id}/rejoin/")
        self.assertEqual(response.status_code, 403)

    # ── Lessons ─────────────────────────────────────────────────────────

    def test_lessons_filtered_by_course_query_param(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(f"/api/lessons/?course={self.course.id}")
        self.assertEqual(response.status_code, 200)
        for lesson in response.data:
            self.assertEqual(lesson["course"], self.course.id)

    def test_learner_can_see_preview_lessons_without_enrollment(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.get(f"/api/lessons/?course={self.course.id}")
        self.assertEqual(response.status_code, 200)
        titles = [l["title"] for l in response.data]
        self.assertIn("Preview Lesson", titles)

    def test_learner_cannot_see_non_preview_lessons_without_enrollment(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.get(f"/api/lessons/?course={self.course.id}")
        self.assertEqual(response.status_code, 200)
        titles = [l["title"] for l in response.data]
        self.assertNotIn("Regular Lesson", titles)

    def test_trainer_can_update_own_lesson(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch(f"/api/lessons/{self.preview_lesson.id}/", {
            "title": "Updated Preview Lesson",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.preview_lesson.refresh_from_db()
        self.assertEqual(self.preview_lesson.title, "Updated Preview Lesson")

    def test_trainer_cannot_update_another_trainers_lesson(self):
        lesson2 = CourseLesson.objects.create(
            course=self.course2, title="Trainer2 Lesson", position=1,
            video_url="https://example.com/t2",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch(f"/api/lessons/{lesson2.id}/", {
            "title": "Hijacked Lesson",
        }, format="json")
        self.assertIn(response.status_code, (403, 404))

    def test_trainer_can_delete_own_lesson(self):
        self.client.force_authenticate(user=self.trainer)
        deletable = CourseLesson.objects.create(
            course=self.course, title="Delete Me", position=99,
        )
        response = self.client.delete(f"/api/lessons/{deletable.id}/")
        self.assertEqual(response.status_code, 204)

    def test_trainer_cannot_delete_another_trainers_lesson(self):
        lesson2 = CourseLesson.objects.create(
            course=self.course2, title="Trainer2 Deletable", position=1,
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.delete(f"/api/lessons/{lesson2.id}/")
        self.assertIn(response.status_code, (403, 404))

    # ── Assessments ─────────────────────────────────────────────────────

    def test_trainer_can_create_assessment_for_own_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/assessments/", {
            "course": self.course.id,
            "title": "Trainer Assessment",
            "questions": [
                {"id": "q1", "text": "Test?", "options": ["A", "B", "C", "D"], "correct_answer": 0},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_trainer_cannot_create_assessment_for_anothers_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/assessments/", {
            "course": self.course2.id,
            "title": "Unauthorized Assessment",
            "questions": [
                {"id": "q1", "text": "Test?", "options": ["A", "B", "C", "D"], "correct_answer": 0},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_learner_can_submit_assessment(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/assessments/{self.assessment.id}/submit/", {
            "answers": {"q1": 1, "q2": 1},
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIn("score_percent", response.data)
        self.assertEqual(response.data["correct_answers"], 2)

    def test_duplicate_assessment_submission_rejected(self):
        self.client.force_authenticate(user=self.learner)
        self.client.post(f"/api/assessments/{self.assessment.id}/submit/", {
            "answers": {"q1": 1, "q2": 1},
        }, format="json")
        response = self.client.post(f"/api/assessments/{self.assessment.id}/submit/", {
            "answers": {"q1": 1, "q2": 1},
        }, format="json")
        self.assertEqual(response.status_code, 409)

    def test_assessment_past_deadline_rejected(self):
        expired = Assessment.objects.create(
            course=self.course, title="Expired Assessment", created_by=self.trainer,
            questions=[{"id": "q1", "text": "Q?", "options": ["A", "B", "C", "D"], "correct_answer": 0}],
            deadline=timezone.now() - timedelta(hours=1),
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/assessments/{expired.id}/submit/", {
            "answers": {"q1": 0},
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_admin_cannot_take_assessment(self):
        # Admin must be enrolled to even see the assessment via queryset, so
        # we enroll and then test the role check in submit
        Enrollment.objects.create(trainee=self.admin, course=self.course)
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/assessments/{self.assessment.id}/submit/", {
            "answers": {"q1": 0, "q2": 0},
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_learner_cannot_see_correct_answers_in_assessment_questions(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(f"/api/assessments/{self.assessment.id}/")
        self.assertEqual(response.status_code, 200)
        for q in response.data["questions"]:
            self.assertNotIn("correct_answer", q)

    def test_trainer_can_see_correct_answers_in_own_assessment(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get(f"/api/assessments/{self.assessment.id}/")
        self.assertEqual(response.status_code, 200)
        for q in response.data["questions"]:
            self.assertIn("correct_answer", q)

    def test_learner_sees_correct_answers_only_after_submitting(self):
        self.client.force_authenticate(user=self.learner)
        self.client.post(f"/api/assessments/{self.assessment.id}/submit/", {
            "answers": {"q1": 0, "q2": 0},
        }, format="json")
        response = self.client.get(f"/api/assessments/{self.assessment.id}/")
        self.assertEqual(response.status_code, 200)
        for q in response.data["questions"]:
            self.assertIn("correct_answer", q)

    def test_missed_quiz_question_can_be_practised_through_the_question_bank(self):
        # Trainer creates a quiz through the API so each question is linked to a bank entry.
        self.client.force_authenticate(user=self.trainer)
        created = self.client.post("/api/assessments/", {
            "course": self.course.id, "title": "Practice Quiz",
            "questions": [
                {"id": "a", "text": "Capital of France?", "options": ["Paris", "Rome", "Oslo", "Bern"], "correct_answer": 0, "explanation": "Paris."},
                {"id": "b", "text": "2+2?", "options": ["3", "4", "5", "6"], "correct_answer": 1},
            ],
        }, format="json")
        self.assertEqual(created.status_code, 201)
        quiz_id = created.data["id"]

        self.client.force_authenticate(user=self.learner)
        Enrollment.objects.get_or_create(trainee=self.learner, course=self.course)
        submit = self.client.post(f"/api/assessments/{quiz_id}/submit/", {"answers": {"a": 1, "b": 1}}, format="json")
        self.assertEqual(submit.status_code, 201)

        # The review data now carries the correct answer and the bank link for the missed question.
        detail = self.client.get(f"/api/assessments/{quiz_id}/").data
        missed = next(q for q in detail["questions"] if q["id"] == "a")
        self.assertEqual(missed["correct_answer"], 0)
        self.assertTrue(missed["question_bank_id"])

        wrong = self.client.post("/api/question-submissions/grade-practice/", {"answers": {str(missed["question_bank_id"]): 1}}, format="json")
        self.assertEqual(wrong.status_code, 200)
        self.assertEqual(wrong.data["correct"], 0)
        right = self.client.post("/api/question-submissions/grade-practice/", {"answers": {str(missed["question_bank_id"]): 0}}, format="json")
        self.assertEqual(right.data["correct"], 1)
        self.assertEqual(right.data["points_earned"], 10)
        again = self.client.post("/api/question-submissions/grade-practice/", {"answers": {str(missed["question_bank_id"]): 0}}, format="json")
        self.assertEqual(again.data["points_earned"], 0)  # no point farming

    def test_create_order_with_non_numeric_course_id_returns_404(self):
        self.client.force_authenticate(user=self.learner)
        for bad in ("abc", None, [], {}):
            response = self.client.post("/api/payments/create-order/", {"course_id": bad}, format="json")
            self.assertEqual(response.status_code, 404, bad)

    def test_assessment_rejects_malformed_questions(self):
        self.client.force_authenticate(user=self.trainer)
        bad_sets = [
            "not a list",
            ["not an object"],
            [{"id": "q1", "text": "", "options": ["A", "B"], "correct_answer": 0}],
            [{"id": "q1", "text": "Q?", "options": ["A"], "correct_answer": 0}],
            [{"id": "q1", "text": "Q?", "options": ["A", "B"]}],
            [{"id": "q1", "text": "Q?", "options": ["A", "B"], "correct_answer": 5}],
            [{"id": "q1", "text": "Q?", "options": ["A", "B"], "correct_answer": 0},
             {"id": "q1", "text": "Q2?", "options": ["A", "B"], "correct_answer": 1}],
        ]
        for questions in bad_sets:
            response = self.client.post("/api/assessments/", {
                "course": self.course.id, "title": "Bad", "questions": questions,
            }, format="json")
            self.assertEqual(response.status_code, 400, questions)

    def test_trainer_cannot_move_assessment_to_another_trainers_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch(f"/api/assessments/{self.assessment.id}/", {
            "course": self.course2.id,
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.course_id, self.course.id)

    def test_trainer_cannot_move_lesson_to_another_trainers_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.patch(f"/api/lessons/{self.regular_lesson.id}/", {
            "course": self.course2.id,
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_trainer_cannot_edit_or_delete_another_trainers_bank_question(self):
        question = QuestionSubmission.objects.create(
            submitted_by=self.trainer2, course=self.course2,
            question_text="Trainer2 question?", options=["A", "B", "C", "D"],
            correct_answer=0, status="approved",
        )
        self.client.force_authenticate(user=self.trainer)
        self.assertEqual(self.client.patch(
            f"/api/question-submissions/{question.id}/", {"explanation": "hijacked"}, format="json",
        ).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/question-submissions/{question.id}/").status_code, 403)
        self.assertTrue(QuestionSubmission.objects.filter(pk=question.id).exists())

    def test_trainer_cannot_see_another_trainers_draft_course(self):
        draft = Course.objects.create(title="T2 Draft", description="x", trainer=self.trainer2, is_published=False)
        self.client.force_authenticate(user=self.trainer)
        self.assertEqual(self.client.get(f"/api/courses/{draft.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/courses/{self.unpublished_course.id}/").status_code, 200)

    def test_approved_trainer_calling_become_trainer_keeps_access(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/auth/become-trainer/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.trainer.refresh_from_db()
        self.assertTrue(self.trainer.is_approved)

    def test_admin_cannot_change_own_role(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/users/{self.admin.id}/role/", {"role": "trainee"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "admin")

    # ── Assignments ─────────────────────────────────────────────────────

    def test_trainer_creates_assignment(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/assignments/", {
            "course": self.course.id,
            "title": "Test Assignment",
            "instructions": "Do the thing.",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Assignment.objects.filter(title="Test Assignment").exists())

    def test_learner_submits_assignment(self):
        assignment = Assignment.objects.create(
            course=self.course, title="Submit Me", instructions="Write something.",
            created_by=self.trainer,
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/assignments/{assignment.id}/submit/", {
            "response_text": "Here is my work.",
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_duplicate_assignment_submission_rejected(self):
        assignment = Assignment.objects.create(
            course=self.course, title="No Dupes", instructions="One submission only.",
            created_by=self.trainer,
        )
        self.client.force_authenticate(user=self.learner)
        self.client.post(f"/api/assignments/{assignment.id}/submit/", {
            "response_text": "First attempt.",
        }, format="json")
        response = self.client.post(f"/api/assignments/{assignment.id}/submit/", {
            "response_text": "Second attempt.",
        }, format="json")
        self.assertEqual(response.status_code, 409)

    def test_unenrolled_learner_cannot_submit_assignment(self):
        assignment = Assignment.objects.create(
            course=self.course, title="Enrolled Only", instructions="Must be enrolled.",
            created_by=self.trainer,
        )
        self.client.force_authenticate(user=self.learner2)
        response = self.client.post(f"/api/assignments/{assignment.id}/submit/", {
            "response_text": "I'm not enrolled.",
        }, format="json")
        self.assertIn(response.status_code, (403, 404))

    def test_past_deadline_assignment_submission_rejected(self):
        assignment = Assignment.objects.create(
            course=self.course, title="Overdue", instructions="Too late.",
            created_by=self.trainer,
            due_at=timezone.now() - timedelta(hours=1),
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/assignments/{assignment.id}/submit/", {
            "response_text": "Late submission.",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_trainer_reviews_submission_with_score(self):
        assignment = Assignment.objects.create(
            course=self.course, title="Grading Test", instructions="Grade me.",
            created_by=self.trainer, max_score=100,
        )
        sub = AssignmentSubmission.objects.create(
            assignment=assignment, learner=self.learner,
            response_text="My work.",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/assignment-submissions/{sub.id}/review/", {
            "score": 85, "feedback": "Good job!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.score, 85)
        self.assertEqual(sub.status, "reviewed")

    def test_trainer_can_request_revision(self):
        assignment = Assignment.objects.create(
            course=self.course, title="Revision Test", instructions="Try again.",
            created_by=self.trainer, max_score=100,
        )
        sub = AssignmentSubmission.objects.create(
            assignment=assignment, learner=self.learner,
            response_text="Not good enough.",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/assignment-submissions/{sub.id}/review/", {
            "score": 40, "feedback": "Needs improvement.",
            "request_revision": True,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "revision")

    def test_trainer_cannot_review_another_trainers_submissions(self):
        assignment = Assignment.objects.create(
            course=self.course2, title="Other Trainer Assignment",
            instructions="Not yours.", created_by=self.trainer2, max_score=100,
        )
        Enrollment.objects.create(trainee=self.learner, course=self.course2)
        sub = AssignmentSubmission.objects.create(
            assignment=assignment, learner=self.learner,
            response_text="Submitted to trainer2.",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/assignment-submissions/{sub.id}/review/", {
            "score": 50, "feedback": "Not my course.",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_assignment_submissions_list_filtered_by_role(self):
        assignment = Assignment.objects.create(
            course=self.course, title="List Test", instructions=".",
            created_by=self.trainer, max_score=100,
        )
        AssignmentSubmission.objects.create(
            assignment=assignment, learner=self.learner, response_text="Work.",
        )
        # Learner sees only own
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/assignment-submissions/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(s["learner"] == self.learner.id for s in response.data))

        # Trainer sees submissions in their courses
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get("/api/assignment-submissions/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)

        # Admin sees all
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/assignment-submissions/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)

    # ── Discussions ─────────────────────────────────────────────────────

    def test_enrolled_learner_can_post_discussion(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/discussions/", {
            "course": self.course.id,
            "body": "Great course!",
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_unenrolled_learner_cannot_post_discussion(self):
        self.client.force_authenticate(user=self.learner2)
        response = self.client.post("/api/discussions/", {
            "course": self.course.id,
            "body": "I'm not enrolled.",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_course_trainer_can_post_discussion(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/discussions/", {
            "course": self.course.id,
            "body": "Welcome to the course!",
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_author_can_delete_own_post(self):
        post = CourseDiscussion.objects.create(
            course=self.course, author=self.learner, body="Delete me.",
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.delete(f"/api/discussions/{post.id}/")
        self.assertEqual(response.status_code, 204)

    def test_course_trainer_can_delete_any_post_in_their_course(self):
        post = CourseDiscussion.objects.create(
            course=self.course, author=self.learner, body="Trainer will delete this.",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.delete(f"/api/discussions/{post.id}/")
        self.assertEqual(response.status_code, 204)

    def test_non_owner_non_trainer_cannot_delete_anothers_post(self):
        post = CourseDiscussion.objects.create(
            course=self.course, author=self.learner, body="Protected post.",
        )
        # Enroll learner2 so they can see the post
        Enrollment.objects.create(trainee=self.learner2, course=self.course)
        self.client.force_authenticate(user=self.learner2)
        response = self.client.delete(f"/api/discussions/{post.id}/")
        self.assertEqual(response.status_code, 403)

    # ── Admin Endpoints ─────────────────────────────────────────────────

    def test_admin_can_see_overview_stats(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/admin/overview/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("users", response.data)
        self.assertIn("courses", response.data)
        self.assertIn("pending_users", response.data)

    def test_non_admin_denied_overview(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/admin/overview/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_users(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/admin/users/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)

    def test_admin_can_list_pending_users(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/admin/users/?status=pending")
        self.assertEqual(response.status_code, 200)
        for user_data in response.data:
            self.assertFalse(user_data["is_approved"])

    def test_admin_can_approve_user(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/users/{self.unapproved.id}/approve/")
        self.assertEqual(response.status_code, 200)
        self.unapproved.refresh_from_db()
        self.assertTrue(self.unapproved.is_approved)

    def test_admin_can_change_user_role(self):
        target = User.objects.create_user(
            username="role_target", password="StrongPass123!",
            role="trainee", is_approved=True,
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/users/{target.id}/role/", {
            "role": "trainer",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.role, "trainer")

    def test_cannot_change_superuser_role(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/users/{self.superuser.id}/role/", {
            "role": "trainee",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_admin_cannot_change_role_to_invalid(self):
        target = User.objects.create_user(
            username="invalid_role_target", password="StrongPass123!",
            role="trainee", is_approved=True,
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/users/{target.id}/role/", {
            "role": "superadmin",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    # ── Transactions Endpoint ───────────────────────────────────────────

    def test_learner_sees_own_enrollments_in_transactions(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/transactions/")
        self.assertEqual(response.status_code, 200)
        # Should contain at least the enrollment from setUp
        self.assertGreaterEqual(len(response.data["items"]), 1)
        for item in response.data["items"]:
            self.assertEqual(item["learner_id"], self.learner.id)

    def test_trainer_sees_enrollments_in_their_courses(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get("/api/transactions/")
        self.assertEqual(response.status_code, 200)
        for item in response.data["items"]:
            self.assertEqual(item["trainer_id"], self.trainer.id)

    def test_admin_sees_all_transactions(self):
        # Create a second enrollment in trainer2's course
        Enrollment.objects.create(trainee=self.learner, course=self.course2)
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/transactions/")
        self.assertEqual(response.status_code, 200)
        # Admin should see enrollments across multiple trainers
        self.assertGreaterEqual(len(response.data["items"]), 2)

    # ── Enrollments Endpoint ────────────────────────────────────────────

    def test_enrollments_returns_learner_courses(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/enrollments/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)

    # ── Attempts Endpoint ───────────────────────────────────────────────

    def test_learner_sees_own_attempts(self):
        Attempt.objects.create(
            trainee=self.learner, assessment=self.assessment,
            score=100, total_questions=2, answers={"q1": 1, "q2": 1},
            question_results={"q1": True, "q2": True}, points=20,
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/attempts/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)
        for attempt in response.data:
            self.assertEqual(attempt["trainee"], self.learner.id)

    # ── Question Submissions ────────────────────────────────────────────

    def test_learner_submission_is_pending(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/question-submissions/", {
            "course": self.course.id,
            "question_text": "What is Django?",
            "options": ["A framework", "A language", "A database", "An OS"],
            "correct_answer": 0,
            "topic": "Web",
            "difficulty": "beginner",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["submission"]["status"], "pending")

    def test_trainer_auto_approves_on_own_course(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post("/api/question-submissions/", {
            "course": self.course.id,
            "question_text": "What is REST?",
            "options": ["Architecture", "Language", "Protocol", "Library"],
            "correct_answer": 0,
            "topic": "API",
            "difficulty": "beginner",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["submission"]["status"], "approved")

    def test_review_approve(self):
        q = QuestionSubmission.objects.create(
            submitted_by=self.learner, course=self.course,
            question_text="Review approve test?",
            options=["A", "B", "C", "D"], correct_answer=0, status="pending",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/question-submissions/{q.id}/review/", {
            "status": "approved", "review_feedback": "Looks good!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        q.refresh_from_db()
        self.assertEqual(q.status, "approved")

    def test_review_reject(self):
        q = QuestionSubmission.objects.create(
            submitted_by=self.learner, course=self.course,
            question_text="Review reject test?",
            options=["A", "B", "C", "D"], correct_answer=0, status="pending",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/question-submissions/{q.id}/review/", {
            "status": "rejected", "review_feedback": "Not relevant.",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        q.refresh_from_db()
        self.assertEqual(q.status, "rejected")

    def test_review_revision(self):
        q = QuestionSubmission.objects.create(
            submitted_by=self.learner, course=self.course,
            question_text="Review revision test?",
            options=["A", "B", "C", "D"], correct_answer=0, status="pending",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/question-submissions/{q.id}/review/", {
            "status": "revision", "review_feedback": "Please rephrase.",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        q.refresh_from_db()
        self.assertEqual(q.status, "revision")

    def test_duplicate_question_text_rejected(self):
        QuestionSubmission.objects.create(
            submitted_by=self.trainer, course=self.course,
            question_text="Unique question about testing?",
            options=["A", "B", "C", "D"], correct_answer=0, status="approved",
        )
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/question-submissions/", {
            "course": self.course.id,
            "question_text": "Unique question about testing?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 0,
            "topic": "Testing",
            "difficulty": "beginner",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_grade_practice_with_invalid_answers(self):
        self.client.force_authenticate(user=self.learner)
        # Non-dict answers
        response = self.client.post("/api/question-submissions/grade-practice/", {
            "answers": "not-a-dict",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_grade_practice_with_empty_answers(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/question-submissions/grade-practice/", {
            "answers": {},
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_grade_practice_with_nonexistent_question(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post("/api/question-submissions/grade-practice/", {
            "answers": {"999999": 0},
        }, format="json")
        self.assertEqual(response.status_code, 400)

    # ── Payment History ─────────────────────────────────────────────────

    def test_payment_history_returns_200(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/payments/history/")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)

    def test_payment_history_filtered_by_role(self):
        payment = Payment.objects.create(
            learner=self.learner, course=self.paid_course,
            paypal_order_id="HIST-001", gross_amount=Decimal("19.99"),
            platform_fee=Decimal("0.20"), trainer_share=Decimal("19.79"),
            status="captured",
        )
        # Learner sees only own
        self.client.force_authenticate(user=self.learner)
        response = self.client.get("/api/payments/history/")
        self.assertEqual(response.status_code, 200)
        for p in response.data:
            self.assertEqual(p["learner_id"], self.learner.id)

        # Trainer sees payments for their courses
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get("/api/payments/history/")
        self.assertEqual(response.status_code, 200)

        # Admin sees all
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/payments/history/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)

    # ── Trainer cannot review another trainer's course questions ────────

    def test_trainer_cannot_review_another_trainers_question(self):
        q = QuestionSubmission.objects.create(
            submitted_by=self.learner, course=self.course2,
            question_text="Belongs to trainer2 course?",
            options=["A", "B", "C", "D"], correct_answer=0, status="pending",
        )
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(f"/api/question-submissions/{q.id}/review/", {
            "status": "approved",
        }, format="json")
        self.assertIn(response.status_code, (403, 404))

    # ── Assignment-specific edge cases ──────────────────────────────────

    def test_admin_cannot_submit_assignment(self):
        assignment = Assignment.objects.create(
            course=self.course, title="Admin Blocked",
            instructions="Admin can't submit.", created_by=self.trainer,
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/assignments/{assignment.id}/submit/", {
            "response_text": "Admin attempt.",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_assignment_submissions_endpoint_for_specific_assignment(self):
        assignment = Assignment.objects.create(
            course=self.course, title="View Submissions",
            instructions=".", created_by=self.trainer, max_score=100,
        )
        AssignmentSubmission.objects.create(
            assignment=assignment, learner=self.learner, response_text="Done.",
        )
        # Trainer (owner) can view submissions
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get(f"/api/assignments/{assignment.id}/submissions/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

        # Other trainer cannot
        self.client.force_authenticate(user=self.trainer2)
        response = self.client.get(f"/api/assignments/{assignment.id}/submissions/")
        self.assertIn(response.status_code, (403, 404))

        # Learner cannot
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(f"/api/assignments/{assignment.id}/submissions/")
        self.assertEqual(response.status_code, 403)

    # ── Become Trainer edge cases ───────────────────────────────────────

    def test_admin_cannot_become_trainer(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post("/api/auth/become-trainer/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    # ── Token Refresh ───────────────────────────────────────────────────

    def test_token_refresh(self):
        login = self.client.post("/api/auth/token/", {
            "username": "api_learner", "password": "StrongPass123!",
        }, format="json")
        refresh_token = login.data["refresh"]
        response = self.client.post("/api/auth/token/refresh/", {
            "refresh": refresh_token,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    def test_token_refresh_with_invalid_token(self):
        response = self.client.post("/api/auth/token/refresh/", {
            "refresh": "invalid-token-string",
        }, format="json")
        self.assertEqual(response.status_code, 401)

    # ── Learner who is enrolled can see regular lessons ──────────────────

    def test_enrolled_learner_can_see_all_lessons(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(f"/api/lessons/?course={self.course.id}")
        self.assertEqual(response.status_code, 200)
        titles = [l["title"] for l in response.data]
        self.assertIn("Preview Lesson", titles)
        self.assertIn("Regular Lesson", titles)

    # ── Non-admin denied admin user list ─────────────────────────────────

    def test_non_admin_denied_user_list(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get("/api/admin/users/")
        self.assertEqual(response.status_code, 403)

    def test_learner_denied_admin_approve(self):
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f"/api/admin/users/{self.unapproved.id}/approve/")
        self.assertEqual(response.status_code, 403)

    # ── Superuser approve is 400 ─────────────────────────────────────────

    def test_approve_superuser_returns_400(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/users/{self.superuser.id}/approve/")
        self.assertEqual(response.status_code, 400)


class PayPalPaymentSecurityTests(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.trainer = User.objects.create_user(
            username="payment_trainer",
            password="StrongPass123!",
            role="trainer",
            is_approved=True
        )

        self.student = User.objects.create_user(
            username="payment_student",
            password="StrongPass123!",
            role="trainee",
            is_approved=True
        )

        self.other_student = User.objects.create_user(
            username="other_student",
            password="StrongPass123!",
            role="trainee",
            is_approved=True
        )

        self.course = Course.objects.create(
            title="Payment Security Course",
            description="Testing payments",
            trainer=self.trainer,
            price=Decimal("100.00"),
            currency="USD",
            is_published=True
        )

        self.payment = Payment.objects.create(
            learner=self.student,
            course=self.course,
            paypal_order_id="TEST-ORDER-001",
            gross_amount=Decimal("100.00"),
            platform_fee=Decimal("0.00"),
            trainer_share=Decimal("0.00"),
            currency="USD",
            status="created"
        )

        self.client.force_authenticate(user=self.student)

    # TEST 1: Failed PayPal order must not enroll student

    @patch("core.views._paypal_request")
    def test_failed_payment_does_not_enroll(self, mock_paypal):

        mock_paypal.return_value = {
            "id": "TEST-ORDER-001",
            "status": "VOIDED",
            "purchase_units": [{
                "custom_id": f"{self.student.id}:{self.course.id}",
                "amount": {
                    "currency_code": "USD",
                    "value": "100.00"
                }
            }]
        }

        response = self.client.post(
            "/api/payments/capture-order/",
            {"order_id": "TEST-ORDER-001"},
            format="json"
        )

        self.assertEqual(response.status_code, 402)

        self.assertFalse(
            Enrollment.objects.filter(
                trainee=self.student,
                course=self.course
            ).exists()
        )

        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, "created")

    # TEST 2: Declined capture must not enroll student

    @patch("core.views._paypal_request")
    def test_declined_capture_does_not_enroll(self, mock_paypal):

        mock_paypal.side_effect = [
            {
                "id": "TEST-ORDER-001",
                "status": "APPROVED",
                "purchase_units": [{
                    "custom_id": f"{self.student.id}:{self.course.id}",
                    "amount": {
                        "currency_code": "USD",
                        "value": "100.00"
                    }
                }]
            },
            {
                "id": "TEST-ORDER-001",
                "status": "PAYER_ACTION_REQUIRED",
                "purchase_units": []
            }
        ]

        response = self.client.post(
            "/api/payments/capture-order/",
            {"order_id": "TEST-ORDER-001"},
            format="json"
        )

        self.assertEqual(response.status_code, 402)

        self.assertFalse(
            Enrollment.objects.filter(
                trainee=self.student,
                course=self.course
            ).exists()
        )

        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, "created")

    # TEST 3: Modified PayPal amount must be rejected

    @patch("core.views._paypal_request")
    def test_modified_amount_is_rejected(self, mock_paypal):

        mock_paypal.return_value = {
            "id": "TEST-ORDER-001",
            "status": "APPROVED",
            "purchase_units": [{
                "custom_id": f"{self.student.id}:{self.course.id}",
                "amount": {
                    "currency_code": "USD",
                    "value": "1.00"
                }
            }]
        }

        response = self.client.post(
            "/api/payments/capture-order/",
            {"order_id": "TEST-ORDER-001"},
            format="json"
        )

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            Enrollment.objects.filter(
                trainee=self.student,
                course=self.course
            ).exists()
        )

    # TEST 4: Another student cannot capture this order

    def test_other_student_cannot_capture_order(self):

        self.client.force_authenticate(user=self.other_student)

        response = self.client.post(
            "/api/payments/capture-order/",
            {"order_id": "TEST-ORDER-001"},
            format="json"
        )

        self.assertEqual(response.status_code, 404)

        self.assertFalse(
            Enrollment.objects.filter(
                trainee=self.other_student,
                course=self.course
            ).exists()
        )

    # TEST 5: Successful capture enrolls student exactly once

    @patch("core.views._paypal_request")
    def test_successful_capture_and_duplicate_request(self, mock_paypal):

        mock_paypal.side_effect = [
            {
                "id": "TEST-ORDER-001",
                "status": "APPROVED",
                "purchase_units": [{
                    "custom_id": f"{self.student.id}:{self.course.id}",
                    "amount": {
                        "currency_code": "USD",
                        "value": "100.00"
                    }
                }]
            },
            {
                "id": "TEST-ORDER-001",
                "status": "COMPLETED",
                "purchase_units": [{
                    "payments": {
                        "captures": [{
                            "id": "CAPTURE-001",
                            "status": "COMPLETED",
                            "amount": {
                                "currency_code": "USD",
                                "value": "100.00"
                            }
                        }]
                    }
                }]
            }
        ]

        response = self.client.post(
            "/api/payments/capture-order/",
            {"order_id": "TEST-ORDER-001"},
            format="json"
        )

        self.assertEqual(response.status_code, 200)

        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, "captured")
        self.assertEqual(
            self.payment.paypal_capture_id,
            "CAPTURE-001"
        )

        self.assertTrue(
            Enrollment.objects.filter(
                trainee=self.student,
                course=self.course
            ).exists()
        )

        # Repeat the same request

        response2 = self.client.post(
            "/api/payments/capture-order/",
            {"order_id": "TEST-ORDER-001"},
            format="json"
        )

        self.assertEqual(response2.status_code, 200)

        self.assertEqual(
            Enrollment.objects.filter(
                trainee=self.student,
                course=self.course
            ).count(),
            1
        )

        self.assertEqual(
            Payment.objects.filter(
                paypal_order_id="TEST-ORDER-001"
            ).count(),
            1
        )

        # PayPal should not be called again for an already captured order.

        self.assertEqual(mock_paypal.call_count, 2)


class PaymentHistorySecurityTests(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.admin = User.objects.create_user(
            username="audit_admin",
            password="StrongPass123!",
            role="admin",
            is_approved=True
        )

        self.trainer_a = User.objects.create_user(
            username="trainer_a",
            password="StrongPass123!",
            role="trainer",
            is_approved=True
        )

        self.trainer_b = User.objects.create_user(
            username="trainer_b",
            password="StrongPass123!",
            role="trainer",
            is_approved=True
        )

        self.student_a = User.objects.create_user(
            username="student_a",
            password="StrongPass123!",
            role="trainee",
            is_approved=True
        )

        self.student_b = User.objects.create_user(
            username="student_b",
            password="StrongPass123!",
            role="trainee",
            is_approved=True
        )

        self.course_a = Course.objects.create(
            title="Course A",
            description="Trainer A course",
            trainer=self.trainer_a,
            price=Decimal("100.00"),
            currency="USD"
        )

        self.course_b = Course.objects.create(
            title="Course B",
            description="Trainer B course",
            trainer=self.trainer_b,
            price=Decimal("200.00"),
            currency="USD"
        )

        self.payment_a = Payment.objects.create(
            learner=self.student_a,
            course=self.course_a,
            paypal_order_id="AUDIT-ORDER-A",
            paypal_capture_id="AUDIT-CAPTURE-A",
            gross_amount=Decimal("100.00"),
            platform_fee=Decimal("10.00"),
            trainer_share=Decimal("90.00"),
            currency="USD",
            status="captured"
        )

        self.payment_b = Payment.objects.create(
            learner=self.student_b,
            course=self.course_b,
            paypal_order_id="AUDIT-ORDER-B",
            paypal_capture_id="AUDIT-CAPTURE-B",
            gross_amount=Decimal("200.00"),
            platform_fee=Decimal("20.00"),
            trainer_share=Decimal("180.00"),
            currency="USD",
            status="captured"
        )
        Enrollment.objects.create(
        trainee=self.student_a,
        course=self.course_a
        )

        Enrollment.objects.create(
            trainee=self.student_b,
            course=self.course_b
            )

    def test_student_sees_only_own_payment_history(self):
        self.client.force_authenticate(self.student_a)

        response = self.client.get("/api/payments/history/")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["learner_id"],
            self.student_a.id
        )

    def test_trainer_sees_only_own_course_payments(self):
        self.client.force_authenticate(self.trainer_a)

        response = self.client.get("/api/payments/history/")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["course_id"],
            self.course_a.id
        )

    def test_admin_sees_all_payments(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/payments/history/")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data), 2)

    def test_trainer_revenue_is_limited_to_own_courses(self):
        self.client.force_authenticate(self.trainer_a)

        response = self.client.get("/api/transactions/")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Decimal(response.data["summary"]["gross_revenue"]),
            Decimal("100.00")
        )

        self.assertEqual(
            Decimal(response.data["summary"]["trainer_shares"]),
            Decimal("90.00")
        )

        for item in response.data["items"]:
            self.assertEqual(item["trainer_id"], self.trainer_a.id)

    def test_admin_sees_platform_wide_revenue(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/transactions/")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Decimal(response.data["summary"]["gross_revenue"]),
            Decimal("300.00")
        )

        self.assertEqual(
            Decimal(response.data["summary"]["platform_fees"]),
            Decimal("30.00")
        )

        self.assertEqual(
            Decimal(response.data["summary"]["trainer_shares"]),
            Decimal("270.00")
        )

    def test_student_cannot_see_other_student_payment(self):
        self.client.force_authenticate(self.student_a)

        response = self.client.get("/api/transactions/")

        self.assertEqual(response.status_code, 200)

        for item in response.data["items"]:
            self.assertEqual(
                item["learner_id"],
                self.student_a.id
            )



class PayPalFinanceEdgeCaseRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.trainer = User.objects.create_user(
            username="finance_trainer", password="StrongPass123!",
            role="trainer", is_approved=True, paypal_email="trainer@example.com",
        )
        self.learner = User.objects.create_user(
            username="finance_learner", password="StrongPass123!",
            role="trainee", is_approved=True,
        )
        self.course = Course.objects.create(
            title="Finance Edge Course", description="Finance test",
            trainer=self.trainer, price=Decimal("30.00"),
        )

    def _payment(self):
        return Payment.objects.create(
            learner=self.learner, course=self.course,
            paypal_order_id="ORDER-FINANCE-EDGE",
            paypal_capture_id="CAPTURE-FINANCE-EDGE",
            gross_amount=Decimal("30.00"),
            platform_fee=Decimal("0.30"),
            trainer_share=Decimal("29.70"),
            currency="USD", status="captured",
        )

    def _webhook(self, event_id, event_type, resource):
        payload = {"id": event_id, "event_type": event_type, "resource": resource}
        headers = {
            "HTTP_PAYPAL_AUTH_ALGO": "SHA256withRSA",
            "HTTP_PAYPAL_CERT_URL": "https://example.test/cert",
            "HTTP_PAYPAL_TRANSMISSION_ID": "transmission-" + event_id,
            "HTTP_PAYPAL_TRANSMISSION_SIG": "signature",
            "HTTP_PAYPAL_TRANSMISSION_TIME": "2026-11-05T10:00:00Z",
        }
        with patch("core.views._paypal_verify_webhook_signature",
                   return_value={"verification_status": "SUCCESS"}):
            return self.client.post("/api/payments/webhook/", payload, format="json", **headers)

    def test_nan_payout_amount_returns_400(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.post(
            "/api/trainer/payouts/",
            {"amount": "NaN", "currency": "USD"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payout.objects.filter(trainer=self.trainer).count(), 0)

    def test_capture_refunded_event_before_refund_completed_does_not_double_count(self):
        payment = self._payment()
        with override_settings(PAYPAL_WEBHOOK_ID="test-webhook"):
            first = self._webhook(
                "EVENT-CAPTURE-REFUNDED", "PAYMENT.CAPTURE.REFUNDED",
                {"id": payment.paypal_capture_id, "status": "PARTIALLY_REFUNDED",
                 "amount": {"value": "30.00", "currency_code": "USD"}},
            )
            self.assertEqual(first.status_code, 202)
            payment.refresh_from_db()
            self.assertEqual(payment.refunded_amount, Decimal("0.00"))

            second = self._webhook(
                "EVENT-REFUND-COMPLETED", "PAYMENT.REFUND.COMPLETED",
                {"id": "REFUND-EDGE-1",
                 "supplementary_data": {"related_ids": {"capture_id": payment.paypal_capture_id}},
                 "amount": {"value": "10.00", "currency_code": "USD"}},
            )
            self.assertEqual(second.status_code, 200)
            payment.refresh_from_db()
            self.assertEqual(payment.refunded_amount, Decimal("10.00"))

    def test_disputed_trainer_share_is_not_available_for_withdrawal(self):
        from core.views import _trainer_payout_balances
        payment = self._payment()
        PayPalDispute.objects.create(
            dispute_id="DISPUTE-EDGE-1", payment=payment,
            status="OPEN", amount=Decimal("15.00"), currency="USD",
            raw_payload={"dispute_outcome": {}},
        )
        balance = _trainer_payout_balances(self.trainer)[0]
        self.assertEqual(Decimal(balance["disputed"]), Decimal("14.85"))
        self.assertEqual(Decimal(balance["available"]), Decimal("14.85"))

    def test_payout_item_succeeded_webhook_completes_payout(self):
        payout = Payout.objects.create(
            trainer=self.trainer, amount=Decimal("10.00"), currency="USD",
            status="processing", paypal_batch_id="BATCH-EDGE-1",
            sender_batch_id="SENDER-EDGE-1",
        )
        with override_settings(PAYPAL_WEBHOOK_ID="test-webhook"):
            response = self._webhook(
                "EVENT-PAYOUT-SUCCEEDED", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
                {"payout_batch_id": payout.paypal_batch_id,
                 "transaction_status": "SUCCESS", "payout_item_id": "ITEM-EDGE-1"},
            )
        self.assertEqual(response.status_code, 200)
        payout.refresh_from_db()
        self.assertEqual(payout.status, "completed")
        self.assertIsNotNone(payout.completed_at)
