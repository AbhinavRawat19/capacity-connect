from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    RegisterView,
    me,
    become_trainer,
    CourseViewSet,
    MyEnrollmentsView,
    AssessmentViewSet,
    AttemptView,
    admin_overview,
    AdminUsersView,
    approve_user,
    update_user_role,
    QuestionSubmissionViewSet,
    leaderboard,
    CourseLessonViewSet,
    AssignmentViewSet,
    AssignmentSubmissionListView,
    review_assignment_submission,
    CourseDiscussionViewSet,
    learning_intelligence,
    paypal_create_order,
    paypal_capture_order,
    payment_history,
    transactions_and_enrollments,
    withdraw_from_course,
    rejoin_paid_course,
    paypal_webhook,
    admin_refund_payment,
    admin_financial_report,
    admin_reconcile_payments,
    admin_paypal_disputes,
    admin_webhook_reconciliation_events,
    trainer_payouts,
    admin_trainer_payouts,
    admin_sync_trainer_payout,
)
from .insights import my_certificates, verify_certificate, trainer_analytics

router = DefaultRouter()

router.register('courses', CourseViewSet, basename='course')
router.register('assessments', AssessmentViewSet, basename='assessment')
router.register('question-submissions', QuestionSubmissionViewSet, basename='question-submission')
router.register('lessons', CourseLessonViewSet, basename='lesson')
router.register('assignments', AssignmentViewSet, basename='assignment')
router.register('discussions', CourseDiscussionViewSet, basename='discussion')


urlpatterns = [
    path('ai/learning-intelligence/', learning_intelligence),
    path('payments/create-order/', paypal_create_order),
    path('payments/capture-order/', paypal_capture_order),
    path('payments/history/', payment_history),
    path('payments/webhook/', paypal_webhook),
    path('admin/payments/<int:payment_id>/refund/', admin_refund_payment),
    path('admin/financial-report/', admin_financial_report),
    path('admin/reconcile-payments/', admin_reconcile_payments),
    path('admin/paypal-disputes/', admin_paypal_disputes),
    path('admin/webhook-reconciliation-events/', admin_webhook_reconciliation_events),
    path('trainer/payouts/', trainer_payouts),
    path('admin/trainer-payouts/', admin_trainer_payouts),
    path('admin/trainer-payouts/<int:payout_id>/sync/', admin_sync_trainer_payout),
    path('certificates/', my_certificates),
    path('certificates/verify/<str:code>/', verify_certificate),
    path('trainer/analytics/', trainer_analytics),
    path('transactions/', transactions_and_enrollments),
    path('courses/<int:course_id>/withdraw/', withdraw_from_course),
    path('courses/<int:course_id>/rejoin/', rejoin_paid_course),

    path('auth/register/', RegisterView.as_view()),
    path('auth/token/', TokenObtainPairView.as_view()),
    path('auth/token/refresh/', TokenRefreshView.as_view()),
    path('auth/me/', me),
    path('auth/become-trainer/', become_trainer),

    path('enrollments/', MyEnrollmentsView.as_view()),
    path('attempts/', AttemptView.as_view()),
    path('assignment-submissions/', AssignmentSubmissionListView.as_view()),

    path(
        'assignment-submissions/<int:submission_id>/review/',
        review_assignment_submission
    ),

    path('leaderboard/', leaderboard),
    path('admin/overview/', admin_overview),
    path('admin/users/', AdminUsersView.as_view()),

    path(
        'admin/users/<int:user_id>/approve/',
        approve_user
    ),

    path(
        'admin/users/<int:user_id>/role/',
        update_user_role
    ),

    path('', include(router.urls)),
]