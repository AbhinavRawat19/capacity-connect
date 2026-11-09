"""Request/response contracts for Capacity Connect Learning Intelligence."""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


class SkillInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=120)
    category: Optional[str] = None
    current_score: float = Field(ge=0, le=100)
    target_score: float = Field(ge=0, le=100)
    # False when the learner only listed the skill name (no proficiency score was
    # recorded), so current_score is an assumed 0 rather than a measurement.
    scored: bool = True
    # Optional human-readable note about where current_score came from.
    evidence: Optional[str] = None


class CourseInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    category: Optional[str] = None
    difficulty: Optional[str] = "Beginner"
    rating: float = Field(default=4.0, ge=0, le=5)
    popularity_count: int = Field(default=0, ge=0)
    duration: Optional[str] = None
    estimated_hours: Optional[float] = Field(default=None, gt=0, le=1000)
    description: Optional[str] = None
    gap_targeted: Optional[str] = None
    target_skills: List[str] = Field(default_factory=list)
    target_skill_ids: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    # True when `prerequisites` were inferred from the level ladder inside a
    # category rather than declared by the trainer; such prerequisites can be
    # waived when the learner shows enough proficiency in the course's skills.
    prerequisites_implied: bool = False


class EnrollmentState(BaseModel):
    """A learner's progress in one course (learning history)."""
    model_config = ConfigDict(extra="ignore")

    course_id: str = Field(min_length=1, max_length=120)
    progress: int = Field(default=0, ge=0, le=100)
    completed: bool = False
    # Mean assessment percentage the learner achieved in this course, if any.
    assessment_percent: Optional[float] = Field(default=None, ge=0, le=100)


class LearningIntelligenceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    learner_id: Optional[str] = None
    skills: List[SkillInput] = Field(default_factory=list)
    courses: List[CourseInput] = Field(default_factory=list)
    completed_course_ids: List[str] = Field(default_factory=list)
    # Optional richer history/profile signals; all default to "not provided".
    enrollments: List[EnrollmentState] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    max_recommendations: int = Field(default=5, ge=1, le=20)

    @field_validator("skills")
    @classmethod
    def skill_names_must_be_unique(cls, skills):
        names = [s.name.strip().casefold() for s in skills]
        if len(names) != len(set(names)):
            raise ValueError("Skill names must be unique within a learner profile")
        return skills

    @field_validator("courses")
    @classmethod
    def course_ids_must_be_unique(cls, courses):
        ids = [c.id for c in courses]
        if len(ids) != len(set(ids)):
            raise ValueError("Course IDs must be unique within the course catalog")
        return courses


class SkillGapResult(BaseModel):
    skill_id: Optional[str] = None
    skill_name: str
    category: Optional[str] = None
    current_score: float
    target_score: float
    gap: float
    priority: str


class CourseRecommendation(BaseModel):
    course_id: str
    title: str
    score: float
    priority: str
    matched_skills: List[str]
    reasons: List[str]
    difficulty: Optional[str] = None
    duration: Optional[str] = None
    prerequisites: List[str] = Field(default_factory=list)
    unmet_prerequisites: List[str] = Field(default_factory=list)
    # "recommended" | "continue" | "prerequisite_building" | "popular_fallback"
    recommendation_type: str = "recommended"
    # Titles of blocked courses this recommendation unlocks (prerequisite_building).
    unlocks: List[str] = Field(default_factory=list)
    # Per-component contribution to `score` (points out of 100), for transparency.
    score_breakdown: Dict[str, float] = Field(default_factory=dict)


class LearningPathStep(BaseModel):
    position: int
    course_id: str
    title: str
    reason: str
    addresses_skills: List[str] = Field(default_factory=list)


class LearningIntelligenceResponse(BaseModel):
    learner_id: Optional[str] = None
    overall_competency_score: float
    skills_analyzed: int
    total_gaps_identified: int
    skill_gaps: List[SkillGapResult]
    recommendations: List[CourseRecommendation]
    learning_path: List[LearningPathStep]
    method: str
    notes: List[str] = Field(default_factory=list)
    # "personalized" or "popularity" - which ranking path produced the list.
    ranking_mode: str = "personalized"
    # Assessment-backed adaptive competency and learning analytics.
    competency_trends: List[Dict] = Field(default_factory=list)
    learning_analytics: Dict = Field(default_factory=dict)
    adaptive_scoring: Dict = Field(default_factory=dict)
