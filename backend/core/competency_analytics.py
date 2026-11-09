"""Assessment-backed competency trends, adaptive scores, and learner analytics.

All scores are percentages from Attempt.score. Profile-entered scores are kept
as a separate source of evidence and are never mutated by this module.
"""
from collections import defaultdict
from math import sqrt

from .models import Attempt

TREND_MIN_OBSERVATIONS = 4
TREND_DELTA_THRESHOLD = 5.0
INCONSISTENCY_STDDEV_THRESHOLD = 20.0


def _competency_names(raw):
    if not isinstance(raw, list):
        return []
    names, seen = [], set()
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("skill_name") or item.get("title") or "").strip()
        else:
            name = ""
        key = name.casefold()
        if name and name != "[object Object]" and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def _weighted_average(values):
    """Give newer observations linearly greater weight without discarding history."""
    if not values:
        return None
    weights = range(1, len(values) + 1)
    total_weight = sum(weights)
    return round(sum(value * weight for value, weight in zip(values, weights)) / total_weight, 2)


def analyze_observations(name, observations):
    """Analyze chronological (timestamp, percentage) pairs for one competency."""
    clean = []
    for timestamp, score in observations:
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        if timestamp is None or not 0 <= score <= 100:
            continue
        clean.append((timestamp, score))
    clean.sort(key=lambda item: item[0])
    scores = [score for _, score in clean]
    count = len(scores)
    adaptive_score = _weighted_average(scores)
    mean = round(sum(scores) / count, 2) if count else None
    variance = (sum((score - mean) ** 2 for score in scores) / count) if count else 0
    stddev = round(sqrt(variance), 2) if count else None

    if count < TREND_MIN_OBSERVATIONS:
        trend = "insufficient_data"
        earlier_average = recent_average = difference = None
        confidence = "low"
    else:
        midpoint = count // 2
        earlier = scores[:midpoint]
        recent = scores[midpoint:]
        earlier_average = round(sum(earlier) / len(earlier), 2)
        recent_average = round(sum(recent) / len(recent), 2)
        difference = round(recent_average - earlier_average, 2)
        within_group_variance = (
            sum((value - earlier_average) ** 2 for value in earlier)
            + sum((value - recent_average) ** 2 for value in recent)
        ) / count
        within_group_stddev = sqrt(within_group_variance)
        if within_group_stddev >= INCONSISTENCY_STDDEV_THRESHOLD:
            trend = "inconsistent"
        elif difference >= TREND_DELTA_THRESHOLD:
            trend = "improving"
        elif difference <= -TREND_DELTA_THRESHOLD:
            trend = "declining"
        else:
            trend = "stable"
        confidence = "high" if count >= 8 else "medium"

    if adaptive_score is None:
        level = "unknown"
    elif adaptive_score < 50:
        level = "weak"
    elif adaptive_score >= 80:
        level = "strong"
    else:
        level = "developing"

    if trend == "improving":
        explanation = f"Recent performance is {difference:.1f} points higher than earlier performance."
    elif trend == "declining":
        explanation = f"Recent performance is {abs(difference):.1f} points lower than earlier performance."
    elif trend == "stable":
        explanation = "Earlier and recent performance are broadly consistent."
    elif trend == "inconsistent":
        explanation = "Assessment results vary substantially; more consistent evidence is needed."
    else:
        explanation = f"Only {count} valid assessment observation(s); at least {TREND_MIN_OBSERVATIONS} are needed for a trend."
    return {
        "competency": name,
        "trend": trend,
        "level": level,
        "observations": count,
        "assessment_average": mean,
        "adaptive_score": adaptive_score,
        "earlier_average": earlier_average,
        "recent_average": recent_average,
        "difference": difference,
        "standard_deviation": stddev,
        "confidence": confidence,
        "explanation": explanation,
    }


def build_competency_analytics(user, profile_skills, courses, enrollment_rows=None):
    """Build learner trends and analytics from one chronological Attempt query."""
    course_skill_names = {}
    display_names = {}
    for course in courses:
        names = _competency_names(course.competencies)
        course_skill_names[course.id] = names
        for name in names:
            display_names.setdefault(name.casefold(), name)
    for skill in profile_skills:
        display_names.setdefault(skill.name.casefold(), skill.name)

    observations = defaultdict(list)
    course_scores = defaultdict(list)
    attempts = list(
        Attempt.objects.filter(trainee=user)
        .select_related("assessment")
        .only("id", "score", "submitted_at", "assessment__course_id")
        .order_by("submitted_at", "id")
    )
    valid_attempts = []
    for attempt in attempts:
        timestamp = attempt.submitted_at
        try:
            score = float(attempt.score)
        except (TypeError, ValueError):
            continue
        if timestamp is None or not 0 <= score <= 100:
            continue
        course_id = attempt.assessment.course_id
        valid_attempts.append((attempt, score))
        course_scores[course_id].append(score)
        for name in course_skill_names.get(course_id, []):
            observations[name.casefold()].append((timestamp, score))

    trends = []
    for key, name in sorted(display_names.items(), key=lambda item: item[1].casefold()):
        trends.append(analyze_observations(name, observations.get(key, [])))

    profile_by_key = {skill.name.casefold(): skill for skill in profile_skills}
    adaptive_competencies = []
    for item in trends:
        skill = profile_by_key.get(item["competency"].casefold())
        explicit_score = skill.current_score if skill is not None and skill.scored else None
        assessment_score = item["adaptive_score"]
        if explicit_score is not None:
            # Preserve the learner's explicit value. The blended value is an
            # additional signal for analytics, never written back to the profile.
            adaptive_score = round(explicit_score * 0.6 + (assessment_score or explicit_score) * 0.4, 2)
            score_source = "profile_and_assessments" if assessment_score is not None else "profile"
        else:
            adaptive_score = assessment_score
            score_source = "assessments" if assessment_score is not None else "no_evidence"
        item["profile_score"] = explicit_score
        item["adaptive_score"] = adaptive_score
        item["score_source"] = score_source
        adaptive_competencies.append(item)

    course_averages = {
        str(course_id): round(sum(scores) / len(scores), 2)
        for course_id, scores in course_scores.items() if scores
    }
    scores = [score for _, score in valid_attempts]
    recent_scores = scores[-5:]
    average = round(sum(scores) / len(scores), 2) if scores else None
    recent_average = round(sum(recent_scores) / len(recent_scores), 2) if recent_scores else None
    consistency = None
    if len(scores) >= 2:
        mean = sum(scores) / len(scores)
        consistency = round(sqrt(sum((score - mean) ** 2 for score in scores) / len(scores)), 2)

    ranked = [item for item in adaptive_competencies if item["adaptive_score"] is not None]
    strongest = sorted(ranked, key=lambda item: (-item["adaptive_score"], item["competency"].casefold()))[:3]
    weakest = sorted(ranked, key=lambda item: (item["adaptive_score"], item["competency"].casefold()))[:3]
    enrollments = enrollment_rows if enrollment_rows is not None else list(
        user.enrollments.values("progress", "completed")
    )
    completed = sum(1 for row in enrollments if row["completed"])
    total_enrolled = len(enrollments)

    analytics = {
        "assessment_attempts": len(valid_attempts),
        "average_assessment_score": average,
        "recent_assessment_average": recent_average,
        "score_consistency_stddev": consistency,
        "courses_enrolled": total_enrolled,
        "courses_completed": completed,
        "course_completion_rate": round(100 * completed / total_enrolled, 2) if total_enrolled else 0.0,
        "strongest_competencies": [item["competency"] for item in strongest],
        "weakest_competencies": [item["competency"] for item in weakest],
    }
    return {
        "trends": adaptive_competencies,
        "course_assessment_percent": course_averages,
        "analytics": analytics,
    }
