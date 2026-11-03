from rest_framework import serializers
from .models import User, Course, Enrollment, Assessment, Attempt, QuestionSubmission, CourseLesson, Assignment, AssignmentSubmission, CourseDiscussion, Payment

class UserSerializer(serializers.ModelSerializer):
    paypal_email = serializers.EmailField(required=False, allow_blank=True)

    def validate_competencies(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Competencies must be a list.')
        for index, item in enumerate(value):
            if isinstance(item, str):
                if not item.strip():
                    raise serializers.ValidationError({index: 'Skill names cannot be empty.'})
                continue
            if not isinstance(item, dict):
                raise serializers.ValidationError({index: 'Each competency must be a skill name or an object.'})
            name = item.get('name') or item.get('skill_name') or item.get('title')
            if not isinstance(name, str) or not name.strip():
                raise serializers.ValidationError({index: 'Each competency object must include a skill name.'})
            if 'current_score' in item:
                try:
                    score = float(item['current_score'])
                except (TypeError, ValueError):
                    raise serializers.ValidationError({index: 'current_score must be a number between 0 and 100.'})
                if not 0 <= score <= 100:
                    raise serializers.ValidationError({index: 'current_score must be between 0 and 100.'})
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and (user.id == instance.id or user.is_superuser or getattr(user, 'role', '') == 'admin')):
            data['paypal_email'] = ''
        return data
    class Meta:
        model = User
        fields = ['id','username','first_name','last_name','email','role','department','bio','is_approved','competencies','paypal_email','date_joined']
        read_only_fields = ['id','is_approved','date_joined']
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    class Meta:
        model = User
        fields = ['username','email','password','first_name','last_name','role','department']
    def validate_role(self, value):
        if value == 'admin': raise serializers.ValidationError('Admin accounts can only be created by an administrator.')
        return value
    def create(self, validated_data):
        # Learners are approved automatically; trainer accounts must be approved by an admin.
        requested_role = validated_data.get('role', 'trainee')
        user = User.objects.create_user(**validated_data, is_approved=(requested_role == 'trainee'))
        return user
class CourseSerializer(serializers.ModelSerializer):
    trainer_name = serializers.SerializerMethodField()
    enrolled = serializers.SerializerMethodField()
    previously_paid = serializers.SerializerMethodField()
    enrollment_count = serializers.IntegerField(read_only=True)
    class Meta:
        model = Course
        fields = ['id','title','description','category','level','duration_hours','competencies','resource_url','trainer','trainer_name','created_at','is_published','enrolled','previously_paid','enrollment_count','price','currency']
        read_only_fields = ['trainer','created_at','trainer_name','enrolled','enrollment_count']
    def validate_price(self, value):
        if value < 0: raise serializers.ValidationError('Price cannot be negative.')
        return value
    def validate_currency(self, value):
        value = value.upper()
        if value != 'USD': raise serializers.ValidationError('Only USD is supported in this prototype.')
        return value
    def get_trainer_name(self,obj): return obj.trainer.get_full_name() or obj.trainer.username if obj.trainer else 'Unassigned'
    def get_enrolled(self,obj):
        user = self.context['request'].user
        return obj.enrollments.filter(trainee=user).exists() if user.is_authenticated else False
    def get_previously_paid(self,obj):
        user = self.context['request'].user
        if not user.is_authenticated or getattr(user, 'role', '') != 'trainee':
            return False
        return Payment.objects.filter(learner=user, course=obj, status='captured').exists()
class EnrollmentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    course = CourseSerializer(read_only=True)
    class Meta:
        model = Enrollment
        fields = ['id','course','course_title','enrolled_at','progress','completed']
class AssessmentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    question_count = serializers.SerializerMethodField()
    class Meta:
        model = Assessment
        fields = ['id','course','course_title','title','instructions','deadline','duration_minutes','questions','created_by','created_at','is_published','question_count']
        read_only_fields = ['created_by','created_at','question_count']
    def get_question_count(self,obj): return len(obj.questions or [])
    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            can_see_answers = request.user.is_superuser or request.user.role == 'admin' or (request.user.role == 'trainer' and instance.course.trainer_id == request.user.id)
            if not can_see_answers:
                data['questions'] = [{k:v for k,v in q.items() if k != 'correct_answer'} for q in (instance.questions or [])]
        return data
class AttemptSerializer(serializers.ModelSerializer):
    assessment_title = serializers.CharField(source='assessment.title', read_only=True)
    course_title = serializers.CharField(source='assessment.course.title', read_only=True)
    trainee_name = serializers.SerializerMethodField()
    class Meta:
        model = Attempt
        fields = ['id','assessment','assessment_title','course_title','trainee','trainee_name','answers','score','total_questions','submitted_at','question_timings','question_results','points']
        read_only_fields = ['id','trainee','score','total_questions','submitted_at','assessment_title','course_title','trainee_name']
    def get_trainee_name(self,obj): return obj.trainee.get_full_name() or obj.trainee.username


class QuestionSubmissionSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    class Meta:
        model = QuestionSubmission
        fields = ['id','submitted_by','submitted_by_name','course','lesson','question_text','options','correct_answer','explanation','topic','difficulty','status','review_feedback','reviewed_by','reviewed_by_name','submitted_at','reviewed_at','published_at']
        read_only_fields = ['id','submitted_by','submitted_by_name','status','review_feedback','reviewed_by','reviewed_by_name','submitted_at','reviewed_at','published_at']
    def get_submitted_by_name(self,obj):
        return obj.submitted_by.get_full_name() or obj.submitted_by.username
    def get_reviewed_by_name(self,obj):
        return (obj.reviewed_by.get_full_name() or obj.reviewed_by.username) if obj.reviewed_by else None
    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        privileged = bool(user and user.is_authenticated and (user.is_superuser or user.role in ('trainer', 'admin')))
        own_unpublished = bool(user and user.is_authenticated and instance.submitted_by_id == user.id and instance.status != 'approved')
        if not (privileged or own_unpublished):
            data.pop('correct_answer', None)
        return data
    def validate_options(self, value):
        if not isinstance(value,list) or len(value) != 4 or any(not str(x).strip() for x in value):
            raise serializers.ValidationError('Provide exactly four non-empty answer options.')
        return value
    def validate(self, attrs):
        answer = attrs.get('correct_answer', getattr(self.instance,'correct_answer',None))
        options = attrs.get('options', getattr(self.instance,'options',[]))
        if answer is not None and (answer < 0 or answer >= len(options)):
            raise serializers.ValidationError({'correct_answer':'Correct answer must match one of the four options (0–3).'})
        return attrs


class CourseLessonSerializer(serializers.ModelSerializer):
    video_file_url = serializers.SerializerMethodField()
    resource_file_url = serializers.SerializerMethodField()
    class Meta:
        model = CourseLesson
        fields = ['id','course','title','description','position','video_url','video_file','video_file_url','resource_file','resource_file_url','duration_minutes','is_preview','created_at']
        read_only_fields = ['id','created_at','video_file_url','resource_file_url']
    def get_video_file_url(self,obj):
        request=self.context.get('request')
        return request.build_absolute_uri(obj.video_file.url) if obj.video_file and request else (obj.video_file.url if obj.video_file else None)
    def get_resource_file_url(self,obj):
        request=self.context.get('request')
        return request.build_absolute_uri(obj.resource_file.url) if obj.resource_file and request else (obj.resource_file.url if obj.resource_file else None)

class AssignmentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    trainer_name = serializers.SerializerMethodField()
    submission_count = serializers.IntegerField(read_only=True)
    attachment_url = serializers.SerializerMethodField()
    my_submission = serializers.SerializerMethodField()
    class Meta:
        model = Assignment
        fields = ['id','course','course_title','title','instructions','due_at','max_score','attachment','attachment_url','is_published','created_by','trainer_name','created_at','submission_count','my_submission']
        read_only_fields = ['created_by','created_at','submission_count','trainer_name','attachment_url','my_submission']
    def get_trainer_name(self,obj):
        return (obj.course.trainer.get_full_name() or obj.course.trainer.username) if obj.course.trainer else 'CAPACITY CONNECT'
    def get_attachment_url(self,obj):
        request=self.context.get('request')
        return request.build_absolute_uri(obj.attachment.url) if obj.attachment and request else (obj.attachment.url if obj.attachment else None)
    def get_my_submission(self,obj):
        request=self.context.get('request')
        if not request or not request.user.is_authenticated or request.user.role=='admin' or request.user.is_superuser: return None
        sub=obj.submissions.filter(learner=request.user).first()
        return AssignmentSubmissionSerializer(sub,context=self.context).data if sub else None

class AssignmentSubmissionSerializer(serializers.ModelSerializer):
    learner_name = serializers.SerializerMethodField()
    assignment_title = serializers.CharField(source='assignment.title', read_only=True)
    assignment_max_score = serializers.IntegerField(source='assignment.max_score', read_only=True)
    attachment_url = serializers.SerializerMethodField()
    class Meta:
        model = AssignmentSubmission
        fields = ['id','assignment','assignment_title','assignment_max_score','learner','learner_name','response_text','submission_url','attachment','attachment_url','status','score','feedback','submitted_at','reviewed_at']
        read_only_fields = ['id','assignment','learner','learner_name','status','score','feedback','submitted_at','reviewed_at','attachment_url','assignment_title','assignment_max_score']
    def get_learner_name(self,obj): return obj.learner.get_full_name() or obj.learner.username
    def get_attachment_url(self,obj):
        request=self.context.get('request')
        return request.build_absolute_uri(obj.attachment.url) if obj.attachment and request else (obj.attachment.url if obj.attachment else None)
    def validate(self, attrs):
        response=(attrs.get('response_text') or '').strip()
        url=(attrs.get('submission_url') or '').strip()
        attachment=attrs.get('attachment')
        if not response and not url and not attachment:
            raise serializers.ValidationError('Provide a written response, a link, or an attachment.')
        return attrs

class CourseDiscussionSerializer(serializers.ModelSerializer):

    author_name = serializers.SerializerMethodField()
    author_role = serializers.CharField(source='author.role', read_only=True)

    class Meta:
        model = CourseDiscussion
        fields = [
            'id',
            'course',
            'author',
            'author_name',
            'author_role',
            'body',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'author',
            'author_name',
            'author_role',
            'created_at',
            'updated_at'
        ]

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username
