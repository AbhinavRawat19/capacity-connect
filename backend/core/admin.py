from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Course, Enrollment, Assessment, Attempt, QuestionSubmission, CourseLesson, Assignment, AssignmentSubmission, CourseDiscussion
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Capacity Connect', {'fields': ('role','department','bio','is_approved','competencies')}),)
    list_display = ('username','email','role','is_approved','is_staff')
    list_filter = ('role','is_approved','is_staff')
admin.site.register(Course)
admin.site.register(Enrollment)
admin.site.register(Assessment)
admin.site.register(Attempt)
admin.site.register(QuestionSubmission)

admin.site.register(CourseLesson)
admin.site.register(Assignment)
admin.site.register(AssignmentSubmission)
admin.site.register(CourseDiscussion)
