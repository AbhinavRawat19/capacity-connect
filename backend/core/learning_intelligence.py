"""Explainable learning-intelligence baseline for Capacity Connect.

This module intentionally uses a transparent hybrid scoring baseline, not a
claimed trained ML model. It can be evaluated and replaced/augmented by a
learned recommender once enough real learner-interaction data exists.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from .ai_schemas import (
    CourseInput,
    CourseRecommendation,
    LearningIntelligenceRequest,
    LearningIntelligenceResponse,
    LearningPathStep,
    SkillGapResult,
)

STOP_WORDS = {
    "a", "an", "and", "are", "basics", "by", "for", "from", "in", "intro",
    "introduction", "of", "on", "the", "to", "with", "course", "fundamentals",
    "essentials", "level", "mastery", "applied", "practice",
}


def _normalise(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _tokens(value: str | None) -> set[str]:
    return {t for t in _normalise(value).split() if t and t not in STOP_WORDS}


def _priority(gap: float) -> str:
    if gap >= 30:
        return "High"
    if gap >= 15:
        return "Medium"
    if gap > 0:
        return "Low"
    return "Mastered"


def _course_match(skill, course: CourseInput) -> tuple[float, str | None]:
    """Return a relevance score in [0, 1] and a human-readable match reason."""
    skill_name = _normalise(skill.name)
    skill_id = (skill.id or "").casefold()
    target_ids = {x.casefold() for x in course.target_skill_ids}
    if skill_id and skill_id in target_ids:
        return 1.0, f"Explicitly mapped to skill ID '{skill.id}'."

    targets = [_normalise(x) for x in course.target_skills]
    gap_targeted = _normalise(course.gap_targeted)
    if skill_name and (skill_name in targets or gap_targeted == skill_name):
        return 1.0, f"Directly targets {skill.name}."
    if skill_id and gap_targeted == _normalise(skill_id):
        return 1.0, f"Directly targets skill ID '{skill.id}'."

    target_tokens = set().union(*(_tokens(x) for x in targets)) if targets else set()
    if target_tokens and _tokens(skill.name).issubset(target_tokens):
        return 0.92, f"Target-skill tags cover {skill.name}."

    title_tokens = _tokens(course.title)
    description_tokens = _tokens(course.description)
    gap_tokens = _tokens(course.gap_targeted)
    skill_tokens = _tokens(skill.name)
    if skill_tokens and skill_tokens.issubset(title_tokens | gap_tokens):
        return 0.88, f"Course title or target label matches {skill.name}."
    overlap = len(skill_tokens & (title_tokens | description_tokens | gap_tokens))
    coverage = overlap / max(1, len(skill_tokens))
    if coverage >= 0.75:
        return 0.72, f"Course content has strong keyword overlap with {skill.name}."
    if coverage >= 0.5:
        return 0.52, f"Course content has partial keyword overlap with {skill.name}."

    if skill.category and course.category and _normalise(skill.category) == _normalise(course.category):
        return 0.20, f"Course shares the '{skill.category}' category; skill match is broad."
    return 0.0, None


def _gap_results(request: LearningIntelligenceRequest) -> list[SkillGapResult]:
    results = []
    for skill in request.skills:
        gap = round(max(0.0, skill.target_score - skill.current_score), 2)
        results.append(SkillGapResult(
            skill_id=skill.id,
            skill_name=skill.name,
            category=skill.category,
            current_score=round(skill.current_score, 2),
            target_score=round(skill.target_score, 2),
            gap=gap,
            priority=_priority(gap),
        ))
    return sorted(results, key=lambda x: (-x.gap, x.skill_name.casefold()))


def _recommend(request: LearningIntelligenceRequest, gaps: list[SkillGapResult]) -> list[CourseRecommendation]:
    skill_by_name = {s.name.casefold(): s for s in request.skills}
    completed = set(request.completed_course_ids)
    eligible_courses = [c for c in request.courses if c.id not in completed]

    def matches_for(course: CourseInput) -> list[tuple[float, SkillGapResult, str]]:
        matches = []
        for gap in gaps:
            if gap.gap <= 0:
                continue
            skill = skill_by_name[gap.skill_name.casefold()]
            match_score, match_reason = _course_match(skill, course)
            if match_reason and match_score >= 0.5:
                matches.append((match_score, gap, match_reason))
        return matches

    # If the learner has no usable skills/gaps, or no course matches the gaps,
    # recommend by actual enrollment popularity instead of returning an empty or
    # alphabetically arbitrary list. New courses are eligible immediately; ties
    # are resolved by title for deterministic output.
    has_personalized_match = any(matches_for(course) for course in eligible_courses)
    if not request.skills or not any(g.gap > 0 for g in gaps) or not has_personalized_match:
        popular = sorted(
            eligible_courses,
            key=lambda c: (-c.popularity_count, c.title.casefold(), c.id),
        )
        results = []
        for rank, course in enumerate(popular[:request.max_recommendations]):
            score = round(60.0 - rank * (20.0 / max(1, min(len(popular), request.max_recommendations))), 2)
            reason = (
                f"Popular course: {course.popularity_count} learner enrollment(s)."
                if course.popularity_count != 1
                else "Popular course: 1 learner enrollment."
            )
            if course.popularity_count == 0:
                reason = "Recommended from the available published catalog; popularity data is not available yet."
            unmet = [p for p in course.prerequisites if p not in completed]
            results.append(CourseRecommendation(
                course_id=course.id,
                title=course.title,
                score=score,
                priority="Low",
                matched_skills=[],
                reasons=[reason, "Popularity fallback is used because there is not enough skill-match data for reliable personalization."],
                difficulty=course.difficulty,
                duration=course.duration,
                prerequisites=course.prerequisites,
                unmet_prerequisites=unmet,
            ))
        return results

    candidates: list[CourseRecommendation] = []
    max_popularity = max((c.popularity_count for c in eligible_courses), default=0)
    for course in eligible_courses:
        matches = matches_for(course)
        if not matches:
            # Keep untagged/new courses discoverable below personalized matches.
            popularity_bonus = 5.0 * course.popularity_count / max(1, max_popularity)
            candidates.append(CourseRecommendation(
                course_id=course.id, title=course.title,
                score=round(20.0 + popularity_bonus, 2), priority="Low", matched_skills=[],
                reasons=["Available published course; competency tags do not yet match your profile.",
                         f"Enrollment popularity: {course.popularity_count} learner(s)."],
                difficulty=course.difficulty, duration=course.duration,
                prerequisites=course.prerequisites,
                unmet_prerequisites=[p for p in course.prerequisites if p not in completed],
            ))
            continue

        matches.sort(key=lambda x: (x[0], x[1].gap), reverse=True)
        best_match, best_gap, best_reason = matches[0]
        additional_coverage = min(0.10, 0.025 * (len(matches) - 1))
        gap_weight = min(1.0, best_gap.gap / 50.0)
        rating_weight = course.rating / 5.0
        score = min(1.0, 0.65 * best_match + 0.25 * gap_weight + 0.10 * rating_weight + additional_coverage)
        reasons = [best_reason, f"{best_gap.priority} priority: {best_gap.skill_name} has a {best_gap.gap:g}-point gap."]
        if len(matches) > 1:
            covered = [m[1].skill_name for m in matches]
            reasons.append("Also addresses: " + ", ".join(covered[1:]) + ".")
        if course.rating:
            reasons.append(f"Catalog rating: {course.rating:g}/5.")
        if course.popularity_count:
            reasons.append(f"Enrollment popularity: {course.popularity_count} learner(s).")
        unmet = [p for p in course.prerequisites if p not in completed]
        candidates.append(CourseRecommendation(
            course_id=course.id, title=course.title, score=round(score * 100, 2),
            priority=best_gap.priority, matched_skills=[m[1].skill_name for m in matches],
            reasons=reasons, difficulty=course.difficulty, duration=course.duration,
            prerequisites=course.prerequisites, unmet_prerequisites=unmet,
        ))

    priority_order = {"High": 0, "Medium": 1, "Low": 2, "Mastered": 3}
    candidates.sort(key=lambda r: (
        -r.score,
        priority_order.get(r.priority, 4),
        r.title.casefold(),
    ))
    return candidates[:request.max_recommendations]


def _build_learning_path(
    recommendations: Sequence[CourseRecommendation],
    courses: Sequence[CourseInput],
    completed_ids: Iterable[str],
) -> list[LearningPathStep]:
    """Create a prerequisite-aware path, avoiding duplicates and dependency cycles."""
    catalog = {c.id: c for c in courses}
    completed = set(completed_ids)
    by_recommendation = {r.course_id: r for r in recommendations}
    ordered_ids: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    notes_for: dict[str, str] = {}

    def visit(course_id: str, root_id: str) -> None:
        if course_id in completed or course_id in visited:
            return
        if course_id in visiting:  # Break a malformed prerequisite cycle safely.
            return
        course = catalog.get(course_id)
        if course is None:
            return
        visiting.add(course_id)
        for prerequisite_id in course.prerequisites:
            if prerequisite_id not in completed:
                visit(prerequisite_id, root_id)
                if prerequisite_id in catalog and prerequisite_id not in completed:
                    notes_for.setdefault(prerequisite_id, f"Prerequisite for {catalog[root_id].title}.")
        visiting.remove(course_id)
        visited.add(course_id)
        ordered_ids.append(course_id)
        if course_id == root_id:
            notes_for.setdefault(course_id, "Recommended based on the learner's highest-priority skill gaps.")
        else:
            notes_for.setdefault(course_id, "Prerequisite required before a recommended course.")

    for rec in recommendations:
        visit(rec.course_id, rec.course_id)

    path: list[LearningPathStep] = []
    for index, course_id in enumerate(ordered_ids, start=1):
        course = catalog[course_id]
        rec = by_recommendation.get(course_id)
        path.append(LearningPathStep(
            position=index,
            course_id=course_id,
            title=course.title,
            reason=notes_for.get(course_id, "Recommended learning step."),
            addresses_skills=rec.matched_skills if rec else [],
        ))
    return path


def build_learning_intelligence(request: LearningIntelligenceRequest) -> LearningIntelligenceResponse:
    gaps = _gap_results(request)
    recommendations = _recommend(request, gaps)
    path = _build_learning_path(recommendations, request.courses, request.completed_course_ids)

    notes = [
        "Recommendations use an explainable, content-based scoring baseline; this is not a trained ML model.",
        "Scores rank courses within the supplied catalog and are not probabilities of learner success.",
    ]
    if not request.skills:
        notes.append("No learner skills were supplied; recommendations use enrollment popularity as a fallback.")
    elif not request.courses:
        notes.append("No course catalog was supplied, so course recommendations and the learning path are empty.")
    if request.courses and (not request.skills or not any(g.gap > 0 for g in gaps)):
        notes.append("Personalization data is insufficient, so published courses are ranked by enrollment popularity.")
    elif request.courses and not any(rec.matched_skills for rec in recommendations):
        notes.append("No course matched the learner's unmet skill gaps; recommendations use enrollment popularity as a fallback.")

    overall = round(sum(s.current_score for s in request.skills) / len(request.skills), 2) if request.skills else 0.0
    return LearningIntelligenceResponse(
        learner_id=request.learner_id,
        overall_competency_score=overall,
        skills_analyzed=len(request.skills),
        total_gaps_identified=sum(1 for gap in gaps if gap.gap > 0),
        skill_gaps=gaps,
        recommendations=recommendations,
        learning_path=path,
        method="explainable_content_based_baseline",
        notes=notes,
    )


def precision_at_k(recommended_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Offline evaluation helper: fraction of top-k recommendations marked relevant."""
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = set(relevant_ids)
    top_k = list(recommended_ids[:k])
    if not top_k:
        return 0.0
    return round(sum(1 for course_id in top_k if course_id in relevant) / len(top_k), 4)


def recall_at_k(recommended_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Offline evaluation helper: fraction of known relevant items recovered in top-k."""
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top_k = set(recommended_ids[:k])
    return round(len(top_k & relevant) / len(relevant), 4)
