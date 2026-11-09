# Capacity Connect — Part 2: Adaptive Competency Intelligence

## Scope delivered

Part 2 extends the Part 1 learning-intelligence response with assessment-backed competency trends, adaptive scoring, learning analytics, and learning-path personalization. It reuses the existing `GET /api/ai/learning-intelligence/?limit=1..20` endpoint and adds response fields only. No database model or migration changes are required.

## Assessment evidence

- Evidence comes from `Attempt.score`, `Attempt.submitted_at`, `Attempt.trainee`, and `Attempt.assessment.course`.
- A course contributes its assessment results to the competency names in `Course.competencies`.
- Scores outside 0–100, non-numeric scores, and observations without timestamps are ignored.
- Results are chronological. Repeated attempts are retained as real learning evidence.
- A competency needs at least four valid observations before it can be labelled improving, declining, stable, or inconsistent. Otherwise its trend is `insufficient_data`.

## Trend rules

- Chronological observations are split into earlier and recent halves.
- A change of at least +5 percentage points is `improving`; at most -5 is `declining`; otherwise it is `stable`.
- Large within-period variation (standard deviation >=20) is `inconsistent` and takes precedence over directional classification.
- Evidence confidence is `medium` for 4–7 observations and `high` for 8 or more; insufficient history is `low`.
- Performance level is `weak` (<50), `developing` (50–79.99), or `strong` (>=80).

## Adaptive scoring

Assessment-only competency scores use a recency-weighted average with linearly increasing weights (1, 2, ... n) for chronological attempts. When a learner has an explicit profile score and assessment evidence, the separate adaptive score is 60% profile score + 40% recency-weighted assessment score. If no assessment evidence exists, the explicit score remains the adaptive score.

The stored `User.competencies` JSON is never modified. The adaptive score is used in-memory for the current recommendation request, so skill gaps, recommendation ranking, and learning-path ordering respond to current evidence without overwriting the learner's manually entered value.

## API additions

The existing response retains all Part 1 fields and adds:

- `competency_trends`: per-competency trend, level, observations, assessment average, adaptive score, earlier/recent averages, difference, standard deviation, confidence, source, and explanation.
- `learning_analytics`: valid attempt count, overall and recent assessment averages, score consistency, enrollment/completion counts and rate, strongest competencies, and weakest competencies.
- `adaptive_scoring`: method description and confirmation that explicit profile scores are preserved.

## Performance and compatibility

The recommendation service uses one chronological assessment query, one course-catalog query, and one enrollment query. Query count does not grow with catalog size. Part 1's recommendation ranker, prerequisites, URL, authentication requirements, and legacy response fields remain in place. No new Python or frontend dependencies are required.

## Limitations

- Competency attribution depends on accurate `Course.competencies` tags. Assessment questions do not currently have a competency-level mapping, so a course attempt contributes the same course score to each competency tagged on that course.
- Assignment grades are not included; only quiz `Attempt` records have a consistent percentage score in the current schema.
- No model migration is needed.
