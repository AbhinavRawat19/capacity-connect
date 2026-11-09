from django.db.models import Count

from .models import Course, Enrollment
from .competency_analytics import build_competency_analytics
from .ai_schemas import (
    SkillInput,
    CourseInput,
    EnrollmentState,
    LearningIntelligenceRequest,
)
from .learning_intelligence import build_learning_intelligence, infer_level_prerequisites

MAX_COURSE_HOURS = 1000  # CourseInput.estimated_hours upper bound


def _skill_name(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("name") or item.get("skill_name") or item.get("title") or "").strip()
    return ""


def _clamp_score(value, default):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def parse_profile_skills(raw_competencies):
    """Turn the free-form User.competencies JSON into SkillInput objects.

    Tolerates a missing/non-list value, blank names, case-insensitive
    duplicates (first one wins) and non-numeric scores. A skill with no usable
    current_score is kept as an *unscored* skill (assumed 0, flagged
    scored=False) instead of being dropped or crashing the endpoint.
    """
    if not isinstance(raw_competencies, list):
        return []
    skills, seen = [], set()
    for item in raw_competencies:
        name = _skill_name(item)
        if not name or name.casefold() in seen or name == "[object Object]":
            continue
        seen.add(name.casefold())

        if isinstance(item, dict):
            has_score = item.get("current_score") not in (None, "")
            current = _clamp_score(item.get("current_score"), None) if has_score else None
            scored = current is not None
            skills.append(SkillInput(
                id=str(item.get("id", name)),
                name=name,
                category=item.get("category"),
                current_score=current if scored else 0.0,
                target_score=_clamp_score(item.get("target_score", 100), 100.0),
                scored=scored,
            ))
        elif isinstance(item, str):
            skills.append(SkillInput(
                id=name, name=name, category=None,
                current_score=0.0, target_score=100.0, scored=False,
            ))
    return skills


def _apply_assessment_evidence(skills, courses, assessment_percent):
    """Upgrade unscored profile skills using the learner's real assessment results.

    A skill the learner merely listed becomes a measured skill when they have
    assessment attempts in a course that targets that skill. Scores the learner
    entered explicitly are never overwritten.
    """
    by_name = {s.name.casefold(): s for s in skills if not s.scored}
    contributions = {}
    for course in sorted(courses, key=lambda c: c.id):
        percent = assessment_percent.get(course.id)
        if percent is None:
            continue
        for target in course.target_skills:
            key = target.casefold()
            if key in by_name:
                contributions.setdefault(key, []).append((course.title, percent))
    for key, items in contributions.items():
        skill = by_name[key]
        skill.current_score = round(sum(p for _, p in items) / len(items), 1)
        skill.scored = True
        skill.evidence = "Assessment average from: " + ", ".join(title for title, _ in items)


def get_learning_recommendations(user, max_recommendations=5):
    skills = parse_profile_skills(user.competencies)

    # Enrollment count is the platform's available popularity signal.
    # Annotating it keeps recommendation ranking current without a separate ML catalog.
    db_courses = Course.objects.filter(
        is_published=True
    ).annotate(popularity_count=Count("enrollments")).order_by("id")

    courses = []

    for course in db_courses:
        competencies = course.competencies or []

        target_skills = []
        for skill in competencies if isinstance(competencies, list) else []:
            name = _skill_name(skill)
            if name and name != "[object Object]":
                target_skills.append(name)

        estimated_hours = (
            float(course.duration_hours)
            if course.duration_hours and 0 < course.duration_hours <= MAX_COURSE_HOURS
            else None
        )

        courses.append(
            CourseInput(
                id=str(course.id),
                title=(course.title or "").strip()[:200] or f"Course {course.id}",
                category=course.category,
                difficulty=course.level,
                # The platform has no course ratings. 0 means "no rating data": the ranker
                # drops the rating component and shows no rating, rather than inventing one.
                rating=0.0,
                popularity_count=course.popularity_count,
                estimated_hours=estimated_hours,
                duration=f"{estimated_hours:g} hours" if estimated_hours else None,
                description=course.description,
                target_skills=target_skills,
            )
        )

    # The Course model has no prerequisite field, so derive implied ones from the
    # level ladder inside each category (see infer_level_prerequisites).
    infer_level_prerequisites(courses)

    # Learning history: three small queries, independent of catalog size.
    enrollments = list(Enrollment.objects.filter(trainee=user).values("course_id", "progress", "completed"))
    competency_data = build_competency_analytics(
        user, skills, list(db_courses), enrollment_rows=enrollments
    )
    assessment_percent = competency_data["course_assessment_percent"]

    states = [
        EnrollmentState(
            course_id=str(row["course_id"]),
            progress=max(0, min(100, row["progress"] or 0)),
            completed=bool(row["completed"]),
            assessment_percent=assessment_percent.get(str(row["course_id"])),
        )
        for row in enrollments
    ]
    completed_ids = [s.course_id for s in states if s.completed]

    _apply_assessment_evidence(skills, courses, assessment_percent)
    adaptive_by_name = {
        item["competency"].casefold(): item
        for item in competency_data["trends"]
    }
    for skill in skills:
        evidence = adaptive_by_name.get(skill.name.casefold())
        if evidence and evidence.get("adaptive_score") is not None:
            # This is an in-memory score for this recommendation request only.
            # The User.competencies JSON (including explicit profile scores) is
            # never written or mutated. Explicit scores are blended with
            # assessment evidence by the analytics service.
            skill.current_score = evidence["adaptive_score"]
            skill.scored = True
            if evidence["observations"]:
                skill.evidence = (
                    f"Adaptive score from {evidence['score_source']} using "
                    f"{evidence['observations']} assessment attempts; trend: {evidence['trend']}."
                )

    # Interests: the learner's department plus the categories they are studying.
    enrolled_ids = {s.course_id for s in states}
    interests = [c.category for c in courses if c.id in enrolled_ids and c.category]
    if user.department:
        interests.append(user.department)

    request = LearningIntelligenceRequest(
        learner_id=str(user.id),
        skills=skills,
        courses=courses,
        completed_course_ids=completed_ids,
        enrollments=states,
        interests=list(dict.fromkeys(interests)),
        max_recommendations=max_recommendations,
    )

    result = build_learning_intelligence(request)
    result.competency_trends = competency_data["trends"]
    result.learning_analytics = competency_data["analytics"]
    result.adaptive_scoring = {
        "method": "recency_weighted_assessment_average",
        "description": "Assessment observations receive linearly increasing weights over time. Explicit profile scores are preserved; a separate blended analytics score uses 60% profile score and 40% assessment score when both exist.",
        "explicit_profile_scores_preserved": True,
    }
    return result
