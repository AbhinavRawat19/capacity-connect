# Capacity Connect — Part 1 + Part 2 integration audit

## Root cause of the crash
`backend/core/ai_service.py` imports and calls `infer_level_prerequisites(courses)` (the Course model has no
prerequisite field, so prerequisites are derived from the Beginner → Intermediate → Advanced ladder inside a
category). `backend/core/learning_intelligence.py` never defined it, so importing `ai_service` raised
`ImportError`, which broke `GET /api/ai/learning-intelligence/` and therefore the whole Learning Intelligence page.
The schema (`ai_schemas.py`) and the frontend already carried the matching contract
(`prerequisites_implied`, `recommendation_type`, `score_breakdown`, `ranking_mode`), but the engine never
produced it.

## Changes
- `learning_intelligence.py`: added `infer_level_prerequisites` (same category, nearest lower level, must share a
  target skill, explicit prerequisites never overwritten, acyclic by construction). Implied prerequisites are
  waived when the learner's average score in the course's skills is >= 60 (declared ones are never waived).
  The learning path honours the same rule. The engine now fills `recommendation_type`
  (`recommended` / `continue` / `popular_fallback`), `score_breakdown` and `ranking_mode`.
  When there is no rating data the rating component is dropped and weights are renormalised.
- `ai_service.py`: stopped passing a made-up `rating=4.0` (it produced a false "Catalog rating: 4/5" reason for
  every course); no longer attaches a misleading "adaptive score from ... 0 assessment attempts" note to skills
  that have no assessments.
- `frontend/src/api.js`: non-JSON error bodies (e.g. an HTML 500 page) are no longer dumped into the UI.
- New tests: `test_learning_intelligence.py` (20 DB-free tests), `test_learning_path_integration.py` (3 DB/API tests).

Not touched: PayPal/payment code, authentication, permissions, models, migrations, settings.
