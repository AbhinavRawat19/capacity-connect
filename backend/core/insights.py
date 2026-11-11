"""Certificates (with public verification) and trainer analytics.

Kept in its own module so it does not touch payment/auth logic. Nothing here needs a
database migration: certificates are derived from quiz results and signed with an HMAC.
"""
import hashlib
import hmac
import re
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Assessment, Attempt, Course, Enrollment, Payment, User
from .permissions import IsApproved, IsTrainerOrAdmin
from .views import _payment_net_financials

# A learner earns a certificate once every published quiz in the course has been
# taken and the average score reaches this percentage.
CERTIFICATE_PASS_PERCENT = 50

_CODE_RE = re.compile(r'^CC-(\d+)-(\d+)-([0-9A-F]{12})$')


def _signature(user_id, course_id):
    message = f'certificate:{user_id}:{course_id}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:12].upper()


def certificate_code(user_id, course_id):
    return f'CC-{user_id}-{course_id}-{_signature(user_id, course_id)}'


def _completion_map(course, trainee_ids=None):
    """Return {trainee_id: {...}} for learners who completed every published quiz of `course`
    with an average score at or above the pass mark."""
    published = list(Assessment.objects.filter(course=course, is_published=True).values_list('id', flat=True))
    if not published:
        return {}
    attempts = Attempt.objects.filter(assessment_id__in=published)
    if trainee_ids is not None:
        attempts = attempts.filter(trainee_id__in=trainee_ids)
    best = defaultdict(dict)
    latest = {}
    for trainee_id, assessment_id, score, submitted_at in attempts.values_list('trainee_id', 'assessment_id', 'score', 'submitted_at'):
        best[trainee_id][assessment_id] = max(score, best[trainee_id].get(assessment_id, 0))
        if trainee_id not in latest or submitted_at > latest[trainee_id]:
            latest[trainee_id] = submitted_at
    done = {}
    for trainee_id, scores in best.items():
        if len(scores) < len(published):
            continue
        average = sum(scores.values()) / len(published)
        if average >= CERTIFICATE_PASS_PERCENT:
            done[trainee_id] = {'average_score': round(average, 1), 'issued_at': latest[trainee_id], 'quizzes': len(published)}
    return done


def _display_name(user):
    return user.get_full_name() or user.username


def _certificate_payload(user, course, info):
    return {
        'code': certificate_code(user.id, course.id),
        'learner_name': _display_name(user),
        'course_id': course.id,
        'course_title': course.title,
        'trainer_name': _display_name(course.trainer) if course.trainer else 'CAPACITY CONNECT',
        'duration_hours': course.duration_hours,
        'average_score': info['average_score'],
        'quizzes_completed': info['quizzes'],
        'issued_at': info['issued_at'],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved])
def my_certificates(request):
    """Certificates the signed-in learner has earned (one per completed course)."""
    user = request.user
    result = []
    enrollments = Enrollment.objects.filter(trainee=user).select_related('course', 'course__trainer')
    for enrollment in enrollments:
        info = _completion_map(enrollment.course, trainee_ids=[user.id]).get(user.id)
        if info:
            result.append(_certificate_payload(user, enrollment.course, info))
    result.sort(key=lambda row: row['issued_at'], reverse=True)
    return Response(result)


@api_view(['GET'])
@permission_classes([AllowAny])
def verify_certificate(request, code):
    """Public check that a certificate code is genuine. Shows only what is printed on it."""
    invalid = Response({'valid': False})
    match = _CODE_RE.match(str(code).strip().upper())
    if not match:
        return invalid
    user_id, course_id, signature = int(match.group(1)), int(match.group(2)), match.group(3)
    if not hmac.compare_digest(signature, _signature(user_id, course_id)):
        return invalid
    user = User.objects.filter(pk=user_id).first()
    course = Course.objects.select_related('trainer').filter(pk=course_id).first()
    if not user or not course:
        return invalid
    info = _completion_map(course, trainee_ids=[user_id]).get(user_id)
    if not info:
        return invalid
    payload = _certificate_payload(user, course, info)
    payload['valid'] = True
    return Response(payload)


def _money(value):
    return str(Decimal(value).quantize(Decimal('0.01')))


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved, IsTrainerOrAdmin])
def trainer_analytics(request):
    """Per-course teaching analytics: reach, quiz performance, hardest questions and earnings.
    Trainers see their own courses; administrators see every course."""
    user = request.user
    is_admin = user.is_superuser or user.role == 'admin'
    courses = Course.objects.select_related('trainer').order_by('-created_at')
    if not is_admin:
        courses = courses.filter(trainer=user)

    course_rows = []
    all_hard = []
    totals = {'learners': 0, 'quiz_attempts': 0, 'certificates': 0, 'gross': Decimal('0'), 'refunded': Decimal('0'), 'net_share': Decimal('0'), 'platform_fee': Decimal('0')}
    score_sum = 0.0

    for course in courses:
        learner_ids = set(Enrollment.objects.filter(course=course).values_list('trainee_id', flat=True))
        published = list(Assessment.objects.filter(course=course, is_published=True))
        attempts = list(Attempt.objects.filter(assessment__in=published).select_related('assessment'))
        completions = {tid for tid in _completion_map(course) if tid in learner_ids}
        active_ids = {a.trainee_id for a in attempts}

        tallies = {}
        for attempt in attempts:
            results = attempt.question_results or {}
            for index, question in enumerate(attempt.assessment.questions or []):
                qid = str(question.get('id', index + 1))
                if qid not in results:
                    continue
                key = (attempt.assessment_id, qid)
                row = tallies.setdefault(key, {'text': question.get('text', 'Question'), 'assessment': attempt.assessment.title, 'course': course.title, 'attempts': 0, 'correct': 0})
                row['attempts'] += 1
                row['correct'] += 1 if results[qid] else 0
        hardest = sorted(
            ({**row, 'accuracy': round(row['correct'] / row['attempts'] * 100)} for row in tallies.values() if row['attempts']),
            key=lambda row: (row['accuracy'], -row['attempts']),
        )[:3]
        all_hard.extend(hardest)

        payments = Payment.objects.filter(course=course, status__in=('captured', 'refunded'))
        gross = refunded = net_share = fee = Decimal('0')
        for payment in payments:
            _, net_fee, share = _payment_net_financials(payment)
            gross += payment.gross_amount
            refunded += payment.refunded_amount
            net_share += share
            fee += net_fee

        average = Attempt.objects.filter(assessment__in=published).aggregate(avg=Avg('score'))['avg']
        course_rows.append({
            'id': course.id,
            'title': course.title,
            'is_published': course.is_published,
            'price': _money(course.price),
            'trainer_name': _display_name(course.trainer) if course.trainer else 'Unassigned',
            'learners': len(learner_ids),
            'quizzes': len(published),
            'quiz_attempts': len(attempts),
            'average_score': round(average, 1) if average is not None else None,
            'certificates': len(completions),
            'completion_rate': round(len(completions) / len(learner_ids) * 100) if learner_ids else 0,
            'inactive_learners': len(learner_ids - active_ids) if published else 0,
            'gross_revenue': _money(gross),
            'refunded': _money(refunded),
            'trainer_earnings': _money(net_share),
            'platform_fee': _money(fee),
            'hardest_questions': hardest,
        })
        totals['learners'] += len(learner_ids)
        totals['quiz_attempts'] += len(attempts)
        totals['certificates'] += len(completions)
        totals['gross'] += gross
        totals['refunded'] += refunded
        totals['net_share'] += net_share
        totals['platform_fee'] += fee
        score_sum += sum(a.score for a in attempts)

    all_hard.sort(key=lambda row: (row['accuracy'], -row['attempts']))
    return Response({
        'scope': 'all' if is_admin else 'mine',
        'summary': {
            'courses': len(course_rows),
            'learners': totals['learners'],
            'quiz_attempts': totals['quiz_attempts'],
            'average_score': round(score_sum / totals['quiz_attempts'], 1) if totals['quiz_attempts'] else None,
            'certificates': totals['certificates'],
            'gross_revenue': _money(totals['gross']),
            'refunded': _money(totals['refunded']),
            'trainer_earnings': _money(totals['net_share']),
            'platform_fee': _money(totals['platform_fee']),
        },
        'courses': course_rows,
        'hardest_questions': all_hard[:5],
    })
