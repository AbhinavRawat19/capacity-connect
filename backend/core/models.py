from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = [('trainee','Trainee'),('trainer','Trainer'),('admin','Admin')]
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default='trainee')
    department = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    is_approved = models.BooleanField(default=False)
    competencies = models.JSONField(default=list, blank=True)
    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = 'admin'; self.is_approved = True
        super().save(*args, **kwargs)

class Course(models.Model):
    LEVELS = [('beginner','Beginner'),('intermediate','Intermediate'),('advanced','Advanced')]
    title = models.CharField(max_length=180)
    description = models.TextField()
    category = models.CharField(max_length=100, default='General')
    level = models.CharField(max_length=20, choices=LEVELS, default='beginner')
    duration_hours = models.PositiveIntegerField(default=2)
    competencies = models.JSONField(default=list, blank=True)
    resource_url = models.URLField(blank=True)
    trainer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='courses')
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=True)
    def __str__(self): return self.title

class Enrollment(models.Model):
    trainee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    progress = models.PositiveSmallIntegerField(default=0)
    completed = models.BooleanField(default=False)
    class Meta:
        unique_together = ('trainee','course')

class Assessment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='assessments')
    title = models.CharField(max_length=180)
    instructions = models.TextField(blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=20)
    questions = models.JSONField(default=list)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assessments_created')
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=True)
    def __str__(self): return self.title

class Attempt(models.Model):
    trainee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attempts')
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='attempts')
    answers = models.JSONField(default=dict)
    score = models.FloatField(default=0)
    total_questions = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)
    # Per-question elapsed time in milliseconds, keyed by question ID.
    question_timings = models.JSONField(default=dict, blank=True)
    # Correctness by question ID, stored so leaderboards don't need to re-grade old attempts.
    question_results = models.JSONField(default=dict, blank=True)
    points = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['-submitted_at']

class QuestionSubmission(models.Model):
    STATUS_CHOICES = [('pending','Pending review'),('approved','Approved'),('rejected','Rejected'),('revision','Revision requested')]
    DIFFICULTIES = [('beginner','Beginner'),('intermediate','Intermediate'),('advanced','Advanced')]
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='question_submissions')
    course = models.ForeignKey('Course', on_delete=models.CASCADE, null=True, blank=True, related_name='question_bank_items')
    lesson = models.ForeignKey('CourseLesson', on_delete=models.SET_NULL, null=True, blank=True, related_name='question_bank_items')
    question_text = models.TextField()
    options = models.JSONField(default=list)
    correct_answer = models.PositiveSmallIntegerField()
    explanation = models.TextField(blank=True)
    topic = models.CharField(max_length=120, default='General')
    difficulty = models.CharField(max_length=20, choices=DIFFICULTIES, default='beginner')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    review_feedback = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='question_reviews')
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-submitted_at']
    def __str__(self): return f'{self.topic}: {self.question_text[:70]}'

class QuestionPracticeRecord(models.Model):
    """Latest practice result and one-time points for a learner/question pair."""
    trainee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='question_practice_records')
    question = models.ForeignKey(QuestionSubmission, on_delete=models.CASCADE, related_name='practice_records')
    submitted_answer = models.PositiveSmallIntegerField()
    is_correct = models.BooleanField(default=False)
    points_earned = models.PositiveIntegerField(default=0)
    first_correct_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['trainee', 'question'], name='unique_learner_question_practice')]
        ordering = ['-updated_at']


class CourseLesson(models.Model):
    """A lecture or resource inside a free course."""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1)
    video_url = models.URLField(blank=True)
    video_file = models.FileField(upload_to='lectures/%Y/%m/', blank=True, null=True)
    resource_file = models.FileField(upload_to='resources/%Y/%m/', blank=True, null=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    is_preview = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.course.title} — {self.title}'


class Assignment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='assignments')
    title = models.CharField(max_length=180)
    instructions = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    max_score = models.PositiveIntegerField(default=100)
    attachment = models.FileField(upload_to='assignments/%Y/%m/', blank=True, null=True)
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_assignments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_at', '-created_at']

    def __str__(self):
        return self.title


class AssignmentSubmission(models.Model):
    STATUS_CHOICES = [('submitted','Submitted'), ('reviewed','Reviewed'), ('revision','Revision requested')]
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='submissions')
    learner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assignment_submissions')
    response_text = models.TextField(blank=True)
    submission_url = models.URLField(blank=True)
    attachment = models.FileField(upload_to='assignment_submissions/%Y/%m/', blank=True, null=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='submitted')
    score = models.PositiveIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']
        constraints = [models.UniqueConstraint(fields=['assignment','learner'], name='unique_assignment_submission_per_learner')]

    def __str__(self):
        return f'{self.learner.username} — {self.assignment.title}'


class CourseDiscussion(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='discussion_posts')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_discussions')
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
