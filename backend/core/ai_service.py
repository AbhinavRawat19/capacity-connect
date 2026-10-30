from .models import Course, Enrollment
from .ai_schemas import (
    SkillInput,
    CourseInput,
    LearningIntelligenceRequest,
)
from .learning_intelligence import build_learning_intelligence


def get_learning_recommendations(user, max_recommendations=5):
    raw_competencies = user.competencies or []
    skills = []

    for item in raw_competencies:
        if isinstance(item, str):
            name = item.strip()
            if not name:
                continue

            skill_id = name
            category = None
            current_score = 0.0
            target_score = 100.0

        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if not name:
                continue

            skill_id = str(item.get("id", name))
            category = item.get("category")

            try:
                current_score = float(item.get("current_score", 0))
                target_score = float(item.get("target_score", 100))
            except (TypeError, ValueError):
                continue

            current_score = max(0.0, min(100.0, current_score))
            target_score = max(0.0, min(100.0, target_score))

        else:
            continue

        skills.append(
            SkillInput(
                id=skill_id,
                name=name,
                category=category,
                current_score=current_score,
                target_score=target_score,
            )
        )

    db_courses = Course.objects.filter(
        is_published=True
    ).order_by("id")

    courses = []

    for course in db_courses:
        competencies = course.competencies or []

        target_skills = [
            skill.strip()
            for skill in competencies
            if isinstance(skill, str) and skill.strip()
        ]

        estimated_hours = (
            float(course.duration_hours)
            if course.duration_hours and course.duration_hours > 0
            else None
        )

        courses.append(
            CourseInput(
                id=str(course.id),
                title=course.title,
                category=course.category,
                difficulty=course.level,
                rating=4.0,
                estimated_hours=estimated_hours,
                description=course.description,
                target_skills=target_skills,
            )
        )

    completed_ids = [
        str(course_id)
        for course_id in Enrollment.objects.filter(
            trainee=user,
            completed=True,
        ).values_list("course_id", flat=True)
    ]

    request = LearningIntelligenceRequest(
        learner_id=str(user.id),
        skills=skills,
        courses=courses,
        completed_course_ids=completed_ids,
        max_recommendations=max_recommendations,
    )

    return build_learning_intelligence(request)