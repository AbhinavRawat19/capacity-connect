from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .insights import certificate_code
from .models import Assessment, Attempt, Course, Enrollment, Payment, User


def make_questions():
    return [
        {"id": "q1", "text": "Easy one?", "options": ["A", "B"], "correct_answer": 0},
        {"id": "q2", "text": "Hard one?", "options": ["A", "B"], "correct_answer": 1},
    ]


class CertificateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.trainer = User.objects.create_user("cert_trainer", password="StrongPass123!", role="trainer", is_approved=True)
        self.learner = User.objects.create_user("cert_learner", password="StrongPass123!", role="trainee", is_approved=True, first_name="Ada", last_name="Lovelace")
        self.other = User.objects.create_user("cert_other", password="StrongPass123!", role="trainee", is_approved=True)
        self.course = Course.objects.create(title="Certified Course", description="d", trainer=self.trainer, is_published=True)
        self.quiz1 = Assessment.objects.create(course=self.course, title="Quiz 1", created_by=self.trainer, questions=make_questions())
        self.quiz2 = Assessment.objects.create(course=self.course, title="Quiz 2", created_by=self.trainer, questions=make_questions())
        Enrollment.objects.create(trainee=self.learner, course=self.course)

    def _attempt(self, user, quiz, score):
        return Attempt.objects.create(trainee=user, assessment=quiz, score=score, total_questions=2, question_results={"q1": score >= 50, "q2": score == 100})

    def test_no_certificate_until_every_quiz_is_taken(self):
        self._attempt(self.learner, self.quiz1, 100)
        self.client.force_authenticate(user=self.learner)
        self.assertEqual(self.client.get("/api/certificates/").data, [])

    def test_certificate_issued_after_all_quizzes_with_passing_average(self):
        self._attempt(self.learner, self.quiz1, 100)
        self._attempt(self.learner, self.quiz2, 50)
        self.client.force_authenticate(user=self.learner)
        data = self.client.get("/api/certificates/").data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["course_title"], "Certified Course")
        self.assertEqual(data[0]["learner_name"], "Ada Lovelace")
        self.assertEqual(data[0]["average_score"], 75.0)
        self.assertEqual(data[0]["code"], certificate_code(self.learner.id, self.course.id))

    def test_no_certificate_when_average_below_pass_mark(self):
        self._attempt(self.learner, self.quiz1, 0)
        self._attempt(self.learner, self.quiz2, 40)
        self.client.force_authenticate(user=self.learner)
        self.assertEqual(self.client.get("/api/certificates/").data, [])

    def test_certificates_are_private_to_the_learner(self):
        self._attempt(self.learner, self.quiz1, 100)
        self._attempt(self.learner, self.quiz2, 100)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get("/api/certificates/").data, [])

    def test_public_verification_of_genuine_certificate(self):
        self._attempt(self.learner, self.quiz1, 100)
        self._attempt(self.learner, self.quiz2, 100)
        code = certificate_code(self.learner.id, self.course.id)
        response = self.client.get(f"/api/certificates/verify/{code}/")  # no login
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["valid"])
        self.assertEqual(response.data["learner_name"], "Ada Lovelace")
        self.assertNotIn("email", response.data)

    def test_forged_or_malformed_codes_are_invalid(self):
        self._attempt(self.learner, self.quiz1, 100)
        self._attempt(self.learner, self.quiz2, 100)
        genuine = certificate_code(self.learner.id, self.course.id)
        forged = genuine[:-1] + ("0" if genuine[-1] != "0" else "1")
        swapped = certificate_code(self.other.id, self.course.id).replace(f"-{self.other.id}-", f"-{self.learner.id}-", 1)
        for code in (forged, swapped, "garbage", "CC-1-1-ZZZZZZZZZZZZ"):
            response = self.client.get(f"/api/certificates/verify/{code}/")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.data["valid"], code)

    def test_signed_code_is_invalid_without_completion(self):
        code = certificate_code(self.learner.id, self.course.id)
        self.assertFalse(self.client.get(f"/api/certificates/verify/{code}/").data["valid"])


class TrainerAnalyticsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.trainer = User.objects.create_user("an_trainer", password="StrongPass123!", role="trainer", is_approved=True)
        self.trainer2 = User.objects.create_user("an_trainer2", password="StrongPass123!", role="trainer", is_approved=True)
        self.admin = User.objects.create_user("an_admin", password="StrongPass123!", role="admin", is_approved=True)
        self.l1 = User.objects.create_user("an_l1", password="StrongPass123!", role="trainee", is_approved=True)
        self.l2 = User.objects.create_user("an_l2", password="StrongPass123!", role="trainee", is_approved=True)
        self.course = Course.objects.create(title="Mine", description="d", trainer=self.trainer, is_published=True, price=Decimal("100.00"))
        self.theirs = Course.objects.create(title="Theirs", description="d", trainer=self.trainer2, is_published=True)
        self.quiz = Assessment.objects.create(course=self.course, title="Quiz", created_by=self.trainer, questions=make_questions())
        Enrollment.objects.create(trainee=self.l1, course=self.course)
        Enrollment.objects.create(trainee=self.l2, course=self.course)
        Attempt.objects.create(trainee=self.l1, assessment=self.quiz, score=100, total_questions=2, question_results={"q1": True, "q2": True})
        # l2 never attempts: counted as inactive.
        Payment.objects.create(
            learner=self.l1, course=self.course, paypal_order_id="AN-ORDER-1", paypal_capture_id="AN-CAP-1",
            gross_amount=Decimal("100.00"), platform_fee=Decimal("1.00"), trainer_share=Decimal("99.00"),
            currency="USD", status="captured", refunded_amount=Decimal("0.00"),
        )

    def test_learner_cannot_see_analytics(self):
        self.client.force_authenticate(user=self.l1)
        self.assertEqual(self.client.get("/api/trainer/analytics/").status_code, 403)

    def test_requires_login(self):
        self.assertIn(self.client.get("/api/trainer/analytics/").status_code, (401, 403))

    def test_trainer_sees_only_own_courses(self):
        self.client.force_authenticate(user=self.trainer)
        data = self.client.get("/api/trainer/analytics/").data
        self.assertEqual(data["scope"], "mine")
        self.assertEqual([c["title"] for c in data["courses"]], ["Mine"])
        course = data["courses"][0]
        self.assertEqual(course["learners"], 2)
        self.assertEqual(course["quiz_attempts"], 1)
        self.assertEqual(course["average_score"], 100.0)
        self.assertEqual(course["certificates"], 1)
        self.assertEqual(course["completion_rate"], 50)
        self.assertEqual(course["inactive_learners"], 1)
        self.assertEqual(course["gross_revenue"], "100.00")
        self.assertEqual(course["trainer_earnings"], "99.00")
        self.assertEqual(data["summary"]["learners"], 2)

    def test_refund_reduces_trainer_earnings(self):
        payment = Payment.objects.get(paypal_order_id="AN-ORDER-1")
        payment.refunded_amount = Decimal("50.00")
        payment.status = "captured"
        payment.save()
        self.client.force_authenticate(user=self.trainer)
        course = self.client.get("/api/trainer/analytics/").data["courses"][0]
        self.assertEqual(course["refunded"], "50.00")
        self.assertEqual(course["trainer_earnings"], "49.50")

    def test_hardest_question_is_reported(self):
        Attempt.objects.create(trainee=self.l2, assessment=self.quiz, score=50, total_questions=2, question_results={"q1": True, "q2": False})
        self.client.force_authenticate(user=self.trainer)
        hardest = self.client.get("/api/trainer/analytics/").data["hardest_questions"]
        self.assertEqual(hardest[0]["text"], "Hard one?")
        self.assertEqual(hardest[0]["accuracy"], 50)

    def test_admin_sees_all_courses(self):
        self.client.force_authenticate(user=self.admin)
        data = self.client.get("/api/trainer/analytics/").data
        self.assertEqual(data["scope"], "all")
        self.assertEqual({c["title"] for c in data["courses"]}, {"Mine", "Theirs"})

    def test_trainer_with_no_courses_gets_empty_report(self):
        self.client.force_authenticate(user=self.trainer2)
        data = self.client.get("/api/trainer/analytics/").data
        self.assertEqual([c["title"] for c in data["courses"]], ["Theirs"])
        self.assertIsNone(data["courses"][0]["average_score"])
