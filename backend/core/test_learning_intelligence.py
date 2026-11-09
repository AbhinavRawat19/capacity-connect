"""Part 1 recommendation-engine tests (no database required)."""
from django.test import SimpleTestCase

from .ai_schemas import CourseInput, EnrollmentState, LearningIntelligenceRequest, SkillInput
from .learning_intelligence import (
    _build_learning_path,
    build_learning_intelligence,
    infer_level_prerequisites,
    precision_at_k,
    recall_at_k,
)


def course(cid, title, level="beginner", category="Programming", skills=("Python",), **extra):
    return CourseInput(
        id=str(cid), title=title, difficulty=level, category=category,
        target_skills=list(skills), **extra,
    )


def skill(name="Python", current=20, target=100, scored=True):
    return SkillInput(id=name, name=name, current_score=current, target_score=target, scored=scored)


class InferLevelPrerequisitesTests(SimpleTestCase):
    def test_builds_a_level_ladder_within_a_category(self):
        courses = [
            course(1, "Python Basics", "beginner"),
            course(2, "Python Intermediate", "intermediate"),
            course(3, "Python Advanced", "advanced"),
        ]
        result = infer_level_prerequisites(courses)
        self.assertIs(result, courses)
        by_id = {c.id: c for c in courses}
        self.assertEqual(by_id["1"].prerequisites, [])
        self.assertFalse(by_id["1"].prerequisites_implied)
        self.assertEqual(by_id["2"].prerequisites, ["1"])
        self.assertEqual(by_id["3"].prerequisites, ["2"])
        self.assertTrue(by_id["2"].prerequisites_implied)
        self.assertTrue(by_id["3"].prerequisites_implied)

    def test_levels_are_case_insensitive(self):
        courses = [course(1, "A", "Beginner"), course(2, "B", "ADVANCED")]
        infer_level_prerequisites(courses)
        self.assertEqual(courses[1].prerequisites, ["1"])

    def test_advanced_falls_back_to_beginner_when_no_intermediate_exists(self):
        courses = [course(1, "A", "beginner"), course(3, "C", "advanced")]
        infer_level_prerequisites(courses)
        self.assertEqual(courses[1].prerequisites, ["1"])

    def test_other_categories_and_unrelated_skills_do_not_block(self):
        courses = [
            course(1, "Cooking", "beginner", category="Food", skills=("Python",)),
            course(2, "SQL Basics", "beginner", skills=("SQL",)),
            course(3, "Python Intermediate", "intermediate"),
        ]
        infer_level_prerequisites(courses)
        self.assertEqual(courses[2].prerequisites, [])
        self.assertFalse(courses[2].prerequisites_implied)

    def test_course_without_target_skills_or_with_unknown_level_is_untouched(self):
        courses = [
            course(1, "A", "beginner"),
            course(2, "No skills", "intermediate", skills=()),
            course(3, "Odd level", "expert"),
            CourseInput(id="4", title="No level", difficulty=None, target_skills=["Python"]),
        ]
        infer_level_prerequisites(courses)
        self.assertEqual([c.prerequisites for c in courses], [[], [], [], []])

    def test_declared_prerequisites_are_never_overwritten(self):
        declared = course(2, "Intermediate", "intermediate", prerequisites=["99"])
        courses = [course(1, "Basics", "beginner"), declared]
        infer_level_prerequisites(courses)
        self.assertEqual(declared.prerequisites, ["99"])
        self.assertFalse(declared.prerequisites_implied)

    def test_multiple_same_level_prerequisites_are_sorted_and_idempotent(self):
        courses = [course(5, "B2", "beginner"), course(4, "B1", "beginner"), course(9, "I", "intermediate")]
        infer_level_prerequisites(courses)
        self.assertEqual(courses[2].prerequisites, ["4", "5"])
        infer_level_prerequisites(courses)
        self.assertEqual(courses[2].prerequisites, ["4", "5"])

    def test_empty_catalog(self):
        self.assertEqual(infer_level_prerequisites([]), [])


class RecommendationEngineTests(SimpleTestCase):
    def ladder(self):
        courses = [
            course(1, "Python Basics", "beginner"),
            course(2, "Python Intermediate", "intermediate"),
        ]
        return infer_level_prerequisites(courses)

    def request(self, skills, courses, **extra):
        return LearningIntelligenceRequest(learner_id="1", skills=skills, courses=courses, **extra)

    def test_unmet_implied_prerequisite_is_reported_and_ordered_first_in_path(self):
        result = build_learning_intelligence(self.request([skill(current=20)], self.ladder(), max_recommendations=20))
        rec = next(r for r in result.recommendations if r.course_id == "2")
        self.assertEqual(rec.unmet_prerequisites, ["1"])
        order = [step.course_id for step in result.learning_path]
        self.assertLess(order.index("1"), order.index("2"))

    def test_prerequisite_course_is_pulled_into_path_even_if_not_recommended(self):
        courses = self.ladder()
        recs = build_learning_intelligence(self.request([skill(current=20)], courses, max_recommendations=20)).recommendations
        only_intermediate = [r for r in recs if r.course_id == "2"]
        path = _build_learning_path(only_intermediate, courses, [], [skill(current=20)])
        self.assertEqual([s.course_id for s in path], ["1", "2"])
        self.assertIn("Prerequisite", path[0].reason)

    def test_proficient_learner_waives_implied_prerequisite(self):
        courses = self.ladder()
        result = build_learning_intelligence(self.request([skill(current=75)], courses, max_recommendations=20))
        rec = next(r for r in result.recommendations if r.course_id == "2")
        self.assertEqual(rec.unmet_prerequisites, [])
        only_intermediate = [r for r in result.recommendations if r.course_id == "2"]
        path = _build_learning_path(only_intermediate, courses, [], [skill(current=75)])
        self.assertEqual([s.course_id for s in path], ["2"])

    def test_declared_prerequisites_are_not_waived_by_proficiency(self):
        courses = [
            course(1, "Basics", "beginner"),
            course(2, "Intermediate", "intermediate", prerequisites=["1"]),
        ]
        result = build_learning_intelligence(self.request([skill(current=95)], courses, max_recommendations=20))
        rec = next(r for r in result.recommendations if r.course_id == "2")
        self.assertEqual(rec.unmet_prerequisites, ["1"])

    def test_completed_prerequisite_is_not_unmet_and_completed_course_not_recommended(self):
        result = build_learning_intelligence(
            self.request([skill(current=20)], self.ladder(), completed_course_ids=["1"], max_recommendations=20)
        )
        self.assertNotIn("1", [r.course_id for r in result.recommendations])
        rec = next(r for r in result.recommendations if r.course_id == "2")
        self.assertEqual(rec.unmet_prerequisites, [])

    def test_prerequisite_cycle_does_not_hang_or_duplicate(self):
        courses = [course(1, "A", prerequisites=["2"]), course(2, "B", prerequisites=["1"])]
        result = build_learning_intelligence(self.request([skill()], courses, max_recommendations=20))
        ids = [step.course_id for step in result.learning_path]
        self.assertEqual(sorted(ids), ["1", "2"])

    def test_no_invented_rating_when_catalog_has_no_ratings(self):
        result = build_learning_intelligence(self.request([skill(current=0)], [course(1, "Python Basics", rating=0.0)]))
        rec = result.recommendations[0]
        self.assertFalse(any("rating" in reason.lower() for reason in rec.reasons))
        self.assertNotIn("rating", rec.score_breakdown)
        self.assertLessEqual(rec.score, 100)
        self.assertAlmostEqual(sum(rec.score_breakdown.values()), rec.score, delta=0.05)

    def test_real_rating_is_used_and_shown(self):
        result = build_learning_intelligence(self.request([skill(current=0)], [course(1, "Python Basics", rating=4.0)]))
        rec = result.recommendations[0]
        self.assertTrue(any("rating" in reason.lower() for reason in rec.reasons))
        self.assertIn("rating", rec.score_breakdown)
        self.assertEqual(rec.recommendation_type, "recommended")

    def test_ranking_mode_reflects_personalization(self):
        personalised = build_learning_intelligence(self.request([skill()], [course(1, "Python Basics")]))
        self.assertEqual(personalised.ranking_mode, "personalized")
        popular = build_learning_intelligence(self.request([], [course(1, "Python Basics", popularity_count=3)]))
        self.assertEqual(popular.ranking_mode, "popularity")
        self.assertEqual(popular.recommendations[0].recommendation_type, "popular_fallback")

    def test_in_progress_course_is_marked_continue(self):
        courses = [course(1, "Python Basics")]
        result = build_learning_intelligence(self.request(
            [skill()], courses, enrollments=[EnrollmentState(course_id="1", progress=40)]
        ))
        rec = result.recommendations[0]
        self.assertEqual(rec.recommendation_type, "continue")
        self.assertIn("40%", rec.reasons[0])

    def test_empty_inputs_are_safe(self):
        result = build_learning_intelligence(self.request([], []))
        self.assertEqual(result.recommendations, [])
        self.assertEqual(result.learning_path, [])
        self.assertEqual(result.overall_competency_score, 0.0)


class EvaluationMetricTests(SimpleTestCase):
    def test_precision_and_recall(self):
        self.assertEqual(precision_at_k(["a", "b", "c"], ["a", "c"], 2), 0.5)
        self.assertEqual(recall_at_k(["a", "b", "c"], ["a", "c"], 2), 0.5)
        self.assertEqual(precision_at_k([], ["a"], 3), 0.0)
        with self.assertRaises(ValueError):
            precision_at_k(["a"], ["a"], 0)
