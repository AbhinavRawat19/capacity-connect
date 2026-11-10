"""Learner achievements: XP and level, study streak, and badges.

Everything is derived from data the app already stores (quiz attempts, Question Bank
practice, assignments, community posts), so there is no new table and nothing to migrate.
XP matches the leaderboard's point rules so the two never disagree.
"""
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .insights import _completion_map
from .models import (
    Attempt, AssignmentSubmission, CourseDiscussion, Enrollment,
    QuestionPracticeRecord, QuestionSubmission,
)
from .permissions import IsApproved

XP_PER_LEVEL = 100
CONTRIBUTION_POINTS = 5  # per approved community question, same as the leaderboard


def _active_days(user):
    """Set of calendar dates on which the learner did something."""
    def days(values):
        return {timezone.localtime(v).date() for v in values if v}
    return (
        days(Attempt.objects.filter(trainee=user).values_list('submitted_at', flat=True))
        | days(QuestionPracticeRecord.objects.filter(trainee=user).values_list('updated_at', flat=True))
        | days(AssignmentSubmission.objects.filter(learner=user).values_list('submitted_at', flat=True))
        | days(CourseDiscussion.objects.filter(author=user).values_list('created_at', flat=True))
    )


def compute_streaks(active_days, today):
    """Return (current, longest). A streak survives until the end of the day after the last
    activity, so a learner who studied yesterday still has a live streak this morning."""
    if not active_days:
        return 0, 0
    ordered = sorted(active_days)
    longest = run = 1
    for previous, day in zip(ordered, ordered[1:]):
        run = run + 1 if day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
    last = ordered[-1]
    if (today - last).days > 1:
        return 0, longest
    current = 1
    cursor = last
    while cursor - timedelta(days=1) in active_days:
        cursor -= timedelta(days=1)
        current += 1
    return current, longest


def _badge(key, title, description, current, target):
    return {
        'key': key, 'title': title, 'description': description,
        'current': min(current, target), 'target': target, 'earned': current >= target,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved])
def my_achievements(request):
    user = request.user
    today = timezone.localdate()

    attempts = list(Attempt.objects.filter(trainee=user).values_list('score', 'points'))
    quiz_count = len(attempts)
    perfect = sum(1 for score, _ in attempts if score >= 100)
    practice = QuestionPracticeRecord.objects.filter(trainee=user)
    practice_correct = practice.filter(is_correct=True).count()
    approved_questions = QuestionSubmission.objects.filter(submitted_by=user, status='approved').count()
    assignments = AssignmentSubmission.objects.filter(learner=user).count()
    posts = CourseDiscussion.objects.filter(author=user).count()

    certificates = 0
    for course in (e.course for e in Enrollment.objects.filter(trainee=user).select_related('course')):
        if user.id in _completion_map(course, trainee_ids=[user.id]):
            certificates += 1

    xp = (
        sum(points for _, points in attempts)
        + (practice.aggregate(total=Sum('points_earned'))['total'] or 0)
        + approved_questions * CONTRIBUTION_POINTS
    )
    level = xp // XP_PER_LEVEL + 1

    days = _active_days(user)
    current_streak, longest_streak = compute_streaks(days, today)
    last_14 = [
        {'date': (today - timedelta(days=offset)).isoformat(), 'active': (today - timedelta(days=offset)) in days}
        for offset in range(13, -1, -1)
    ]

    badges = [
        _badge('first_quiz', 'First steps', 'Complete your first quiz.', quiz_count, 1),
        _badge('quiz_regular', 'Quiz regular', 'Complete 5 quizzes.', quiz_count, 5),
        _badge('perfect_score', 'Perfect score', 'Score 100% on a quiz.', perfect, 1),
        _badge('certified', 'Certified', 'Earn a course certificate.', certificates, 1),
        _badge('practice_10', 'Practice makes perfect', 'Answer 10 Question Bank questions correctly.', practice_correct, 10),
        _badge('streak_3', 'On a roll', 'Study three days in a row.', longest_streak, 3),
        _badge('streak_7', 'Week warrior', 'Study seven days in a row.', longest_streak, 7),
        _badge('assignment', 'Hands-on', 'Submit an assignment.', assignments, 1),
        _badge('community', 'Conversation starter', 'Post in a course discussion.', posts, 1),
        _badge('contributor', 'Contributor', 'Get a community question approved.', approved_questions, 1),
        _badge('century', 'Century', 'Earn 100 XP.', xp, 100),
    ]

    return Response({
        'xp': xp,
        'level': level,
        'level_xp': xp % XP_PER_LEVEL,
        'xp_per_level': XP_PER_LEVEL,
        'streak': {
            'current': current_streak,
            'longest': longest_streak,
            'active_today': today in days,
        },
        'last_14_days': last_14,
        'badges': badges,
        'earned_count': sum(1 for b in badges if b['earned']),
    })
