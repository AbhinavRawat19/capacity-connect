from django.db.models import Count, Avg
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from rest_framework import generics, status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import User, Course, Enrollment, Assessment, Attempt, QuestionSubmission
from .serializers import UserSerializer, RegisterSerializer, CourseSerializer, EnrollmentSerializer, AssessmentSerializer, AttemptSerializer, QuestionSubmissionSerializer
from .permissions import IsApproved, IsAdminRole, IsTrainerOrAdmin

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all(); serializer_class = RegisterSerializer; permission_classes = [AllowAny]
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data); serializer.is_valid(raise_exception=True); user=serializer.save()
        message = ('Your learner account is ready; you can sign in now.' if user.role == 'trainee' else 'Your trainer request has been submitted. An administrator must approve your account before you can teach.')
        return Response({'message':f'Welcome to CAPACITY CONNECT. {message}','username':user.username,'role':user.role,'is_approved':user.is_approved}, status=status.HTTP_201_CREATED)

@api_view(['GET','PATCH'])
@permission_classes([IsAuthenticated, IsApproved])
def me(request):
    if request.method == 'GET': return Response(UserSerializer(request.user).data)
    allowed = {'first_name','last_name','email','department','bio','competencies'}
    for key,value in request.data.items():
        if key in allowed: setattr(request.user,key,value)
    request.user.save(); return Response(UserSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved])
def become_trainer(request):
    if request.user.is_superuser or request.user.role == 'admin':
        return Response({'detail':'Administrator accounts cannot switch to trainer mode.'},status=400)
    request.user.role='trainer'
    request.user.is_approved=False
    request.user.save(update_fields=['role','is_approved'])
    return Response({'message':'Your trainer request has been submitted. An administrator must approve your account before you can teach.','user':UserSerializer(request.user).data}, status=202)

class CourseViewSet(viewsets.ModelViewSet):
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    def get_queryset(self):
        qs=Course.objects.select_related('trainer').annotate(enrollment_count=Count('enrollments')).order_by('-created_at')
        user=self.request.user
        if user.role == 'trainer' and self.action in ['update','partial_update','destroy']:
            return qs.filter(trainer=user)
        if user.role == 'trainee': return qs.filter(is_published=True)
        return qs
    def get_permissions(self):
        if self.action in ['create']: return [IsAuthenticated(), IsApproved(), IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        trainer = None if self.request.user.role == 'admin' or self.request.user.is_superuser else self.request.user
        serializer.save(trainer=trainer)
    def update(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role != 'admin' and not request.user.is_superuser and obj.trainer_id != request.user.id: return Response({'detail':'You can only edit your own courses.'},status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role != 'admin' and not request.user.is_superuser and obj.trainer_id != request.user.id: return Response({'detail':'You can only delete your own courses.'},status=403)
        return super().destroy(request,*args,**kwargs)
    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        if request.user.role == 'admin' or request.user.is_superuser: return Response({'detail':'Admin accounts do not need to enroll in courses.'},status=403)
        course=self.get_object()
        enrollment, created=Enrollment.objects.get_or_create(trainee=request.user,course=course)
        return Response({'message':'Enrolled successfully.' if created else 'You are already enrolled.','enrollment_id':enrollment.id},status=201 if created else 200)

class MyEnrollmentsView(generics.ListAPIView):
    serializer_class=EnrollmentSerializer; permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self): return Enrollment.objects.filter(trainee=self.request.user).select_related('course','course__trainer')

class AssessmentViewSet(viewsets.ModelViewSet):
    serializer_class=AssessmentSerializer; permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self):
        qs=Assessment.objects.select_related('course','created_by').order_by('-created_at')
        user=self.request.user
        if user.role == 'trainee': return qs.filter(is_published=True,course__enrollments__trainee=user).distinct()
        if user.role == 'trainer':
            from django.db.models import Q
            return qs.filter(Q(course__trainer=user) | Q(is_published=True,course__enrollments__trainee=user)).distinct()
        return qs
    def get_permissions(self):
        if self.action in ['create','update','partial_update','destroy']: return [IsAuthenticated(),IsApproved(),IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        course=serializer.validated_data['course']; user=self.request.user
        if user.role=='trainer' and course.trainer_id != user.id: raise PermissionError('Trainers can only create assessments for their own courses.')
        serializer.save(created_by=user)
    def create(self, request, *args, **kwargs):
        try: return super().create(request,*args,**kwargs)
        except PermissionError as e: return Response({'detail':str(e)},status=403)
    def update(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You cannot edit this assessment.'},status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You cannot delete this assessment.'},status=403)
        return super().destroy(request,*args,**kwargs)
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        assessment=self.get_object(); user=request.user
        if user.role=='admin' or user.is_superuser: return Response({'detail':'Admin accounts do not take learner assessments.'},status=403)
        if assessment.deadline and timezone.now()>assessment.deadline: return Response({'detail':'The deadline for this assessment has passed.'},status=400)
        if Attempt.objects.filter(trainee=user,assessment=assessment).exists(): return Response({'detail':'You have already submitted this assessment.'},status=409)
        answers=request.data.get('answers')
        if not isinstance(answers,dict): return Response({'detail':'Answers must be an object mapping question IDs to option indexes.'},status=400)
        questions = assessment.questions or []
        if not questions:
            return Response({'detail':'This assessment has no questions yet.'},status=400)
        # Grade answers inside Django. Correct answers are option indexes; string
        # comparison also supports indexes submitted as strings by HTML forms.
        results=[]
        correct_answers=0
        for index, question in enumerate(questions):
            question_id=str(question.get('id', index+1))
            expected=question.get('correct_answer')
            submitted=answers.get(question_id, answers.get(str(index+1)))
            is_correct=(submitted is not None and expected is not None and str(submitted)==str(expected))
            if is_correct:
                correct_answers += 1
            results.append({'question_id':question_id,'correct':is_correct})
        total_questions=len(questions)
        score=round(correct_answers/total_questions*100,2)
        result={'total_questions':total_questions,'correct_answers':correct_answers,'score':score,'results':results}
        raw_timings=request.data.get('question_timings', {})
        if not isinstance(raw_timings, dict):
            return Response({'detail':'question_timings must map question IDs to elapsed milliseconds.'},status=400)
        # Ignore malformed, negative, or implausibly large client timing values. The server
        # calculates all points; the browser never submits a score.
        timings={}
        for key,value in raw_timings.items():
            try: elapsed=max(0,min(int(value),600000))
            except (TypeError,ValueError): continue
            timings[str(key)]=elapsed
        question_results={str(item['question_id']):bool(item['correct']) for item in result.get('results',[])}
        points=0
        for index, question in enumerate(assessment.questions):
            qid=str(question.get('id',index+1))
            if question_results.get(qid,False):
                elapsed=timings.get(qid,timings.get(str(index+1),600000))
                # 10 points for a correct answer, plus at most 5 speed bonus points.
                speed_bonus=max(0,5-min(5,elapsed//6000))
                points += 10 + speed_bonus
        attempt=Attempt.objects.create(trainee=user,assessment=assessment,answers=answers,score=result['score'],total_questions=result['total_questions'],question_timings=timings,question_results=question_results,points=points)
        enrollment=Enrollment.objects.filter(trainee=user,course=assessment.course).first()
        if enrollment:
            attempts=Attempt.objects.filter(trainee=user,assessment__course=assessment.course).count()
            total=Assessment.objects.filter(course=assessment.course,is_published=True).count()
            enrollment.progress=min(100,round(attempts/max(total,1)*100)); enrollment.save(update_fields=['progress'])
        return Response({'message':'Assessment submitted.','attempt':AttemptSerializer(attempt).data,'correct_answers':result['correct_answers'],'score_percent':result['score'],'points_earned':points},status=201)

class AttemptView(generics.ListAPIView):
    serializer_class=AttemptSerializer; permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self):
        qs=Attempt.objects.select_related('trainee','assessment','assessment__course')
        user=self.request.user
        if user.role=='trainee': return qs.filter(trainee=user)
        if user.role=='trainer':
            from django.db.models import Q
            return qs.filter(Q(trainee=user) | Q(assessment__course__trainer=user)).distinct()
        return qs


class QuestionSubmissionViewSet(viewsets.ModelViewSet):
    serializer_class = QuestionSubmissionSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    http_method_names = ['get','post','put','patch','delete','head','options']

    def get_queryset(self):
        user=self.request.user
        qs=QuestionSubmission.objects.select_related('submitted_by','reviewed_by')
        if user.is_superuser or user.role == 'admin':
            status_filter=self.request.query_params.get('status')
            return qs.filter(status=status_filter) if status_filter in ['pending','approved','rejected','revision'] else qs
        if user.role == 'trainer':
            qs = qs.filter(course__trainer=user)
            status_filter=self.request.query_params.get('status')
            return qs.filter(status=status_filter) if status_filter in ['pending','approved','rejected','revision'] else qs
        # Students can view the published question bank and their own submissions only.
        return qs.filter(models_q_for_student(user))

    def update(self, request, *args, **kwargs):
        submission = self.get_object()
        if request.user.role not in ['trainer', 'admin'] and not request.user.is_superuser:
            if submission.submitted_by_id != request.user.id or submission.status not in ['pending', 'revision']:
                return Response({'detail':'You can edit only your own questions while they are pending or need revision.'}, status=403)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        submission = self.get_object()
        if request.user.role not in ['trainer', 'admin'] and not request.user.is_superuser:
            if submission.submitted_by_id != request.user.id or submission.status not in ['pending', 'revision']:
                return Response({'detail':'You can delete only your own questions while they are pending or need revision.'}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='grade-practice')
    def grade_practice(self, request):
        answers = request.data.get('answers')
        if not isinstance(answers, dict) or not answers:
            return Response({'detail':'answers must be a non-empty object of question IDs to option indexes.'}, status=400)
        ids = [int(k) for k in answers if str(k).isdigit()]
        qs = QuestionSubmission.objects.filter(id__in=ids, status='approved')
        by_id = {str(q.id): q for q in qs}
        if len(by_id) != len(answers):
            return Response({'detail':'One or more questions are unavailable.'}, status=400)
        results = []
        correct = 0
        for qid, submitted in answers.items():
            q = by_id[str(qid)]
            is_correct = str(submitted) == str(q.correct_answer)
            correct += int(is_correct)
            results.append({'id': q.id, 'correct': is_correct, 'correct_answer': q.correct_answer, 'options': q.options, 'explanation': q.explanation})
        return Response({'correct': correct, 'total': len(results), 'results': results})

    def create(self, request, *args, **kwargs):
        if request.user.role != 'trainee':
            return Response({'detail':'Only trainees can submit community questions.'},status=403)
        serializer=self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized=' '.join(serializer.validated_data['question_text'].lower().split())
        for existing in QuestionSubmission.objects.filter(status__in=['pending','approved']).only('question_text'):
            if ' '.join(existing.question_text.lower().split()) == normalized:
                return Response({'detail':'A matching question is already pending review or published.'},status=400)
        course_id=serializer.validated_data.get('course').id if serializer.validated_data.get('course') else None
        lesson=serializer.validated_data.get('lesson')
        if lesson and course_id and lesson.course_id != course_id:
            return Response({'detail':'Selected lecture must belong to the selected course.'},status=400)
        if lesson and not course_id:
            serializer.validated_data['course']=lesson.course
        serializer.save(submitted_by=request.user)
        return Response({'message':'Question submitted for trainer review.','submission':serializer.data},status=201)

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        if request.user.role not in ['trainer','admin'] and not request.user.is_superuser:
            return Response({'detail':'Only trainers and administrators can review questions.'},status=403)
        submission=self.get_object()
        if request.user.role == 'trainer' and not request.user.is_superuser and submission.course_id and submission.course.trainer_id != request.user.id:
            return Response({'detail':'You can review questions only for your own courses.'}, status=403)
        decision=request.data.get('status')
        if decision not in ['approved','rejected','revision']:
            return Response({'detail':'status must be approved, rejected, or revision.'},status=400)
        feedback=str(request.data.get('review_feedback','')).strip()[:2000]
        submission.status=decision
        submission.review_feedback=feedback
        submission.reviewed_by=request.user
        submission.reviewed_at=timezone.now()
        submission.published_at=timezone.now() if decision=='approved' else None
        submission.save(update_fields=['status','review_feedback','reviewed_by','reviewed_at','published_at'])
        return Response({'message':'Question approved and published.' if decision=='approved' else 'Review decision saved.','submission':self.get_serializer(submission).data})


def models_q_for_student(user):
    from django.db.models import Q
    return Q(status='approved') | Q(submitted_by=user)


@api_view(['GET'])
@permission_classes([IsAuthenticated,IsApproved])
def leaderboard(request):
    # Only learners compete; trainers/admins must never appear in learner rankings.
    attempts=Attempt.objects.select_related('trainee','assessment','assessment__course').filter(score__gte=0, trainee__role='trainee')
    totals={}
    for attempt in attempts:
        row=totals.setdefault(attempt.trainee_id,{'user_id':attempt.trainee_id,'username':attempt.trainee.get_full_name() or attempt.trainee.username,'points':0,'correct_answers':0,'attempts':0})
        row['points']+=attempt.points
        row['correct_answers']+=sum(1 for correct in (attempt.question_results or {}).values() if correct)
        row['attempts']+=1
    # Reward useful community contributions: each approved question adds five points.
    approved_counts={}
    for submission in QuestionSubmission.objects.filter(status='approved', submitted_by__role='trainee').select_related('submitted_by'):
        uid=submission.submitted_by_id
        approved_counts[uid]=approved_counts.get(uid,0)+1
        if uid not in totals:
            totals[uid]={'user_id':uid,'username':submission.submitted_by.get_full_name() or submission.submitted_by.username,'points':0,'correct_answers':0,'attempts':0}
    for uid,row in totals.items():
        row['approved_contributions']=approved_counts.get(uid,0)
        row['contribution_points']=row['approved_contributions']*5
        row['points']+=row['contribution_points']
    global_rows=sorted(totals.values(),key=lambda row:(-row['points'],-row['correct_answers'],row['username'].lower()))
    for rank,row in enumerate(global_rows,1): row['rank']=rank
    per_question=[]
    # Keys include assessment ID as question IDs may be reused across assessments.
    for attempt in attempts:
        questions=attempt.assessment.questions or []
        for index,question in enumerate(questions):
            qid=str(question.get('id',index+1))
            if not (attempt.question_results or {}).get(qid,False): continue
            elapsed=(attempt.question_timings or {}).get(qid,(attempt.question_timings or {}).get(str(index+1),600000))
            try: elapsed=int(elapsed)
            except (TypeError,ValueError): elapsed=600000
            per_question.append({'question_key':f"{attempt.assessment_id}:{qid}",'question_id':qid,'assessment_id':attempt.assessment_id,'assessment_title':attempt.assessment.title,'course_title':attempt.assessment.course.title,'question_text':question.get('text','Question'),'student':attempt.trainee.get_full_name() or attempt.trainee.username,'user_id':attempt.trainee_id,'elapsed_ms':elapsed,'points':10+max(0,5-min(5,elapsed//6000)),'submitted_at':attempt.submitted_at})
    per_question.sort(key=lambda row:(row['question_key'],-row['points'],row['elapsed_ms'],row['submitted_at']))
    grouped={}
    for row in per_question:
        group=grouped.setdefault(row['question_key'],{'question_key':row['question_key'],'question_id':row['question_id'],'assessment_id':row['assessment_id'],'assessment_title':row['assessment_title'],'course_title':row['course_title'],'question_text':row['question_text'],'entries':[]})
        if len(group['entries'])<10:
            group['entries'].append({k:row[k] for k in ['student','user_id','elapsed_ms','points','submitted_at']})
    return Response({'global':global_rows[:100],'per_question':list(grouped.values())})

@api_view(['GET'])
@permission_classes([IsAuthenticated,IsApproved,IsAdminRole])
def admin_overview(request):
    return Response({'users':User.objects.count(),'pending_users':User.objects.filter(is_approved=False).count(),'trainees':User.objects.filter(role='trainee').count(),'trainers':User.objects.filter(role='trainer').count(),'courses':Course.objects.count(),'assessments':Assessment.objects.count(),'attempts':Attempt.objects.count(),'average_score':round(Attempt.objects.aggregate(avg=Avg('score'))['avg'] or 0,1)})

class AdminUsersView(generics.ListAPIView):
    serializer_class=UserSerializer; permission_classes=[IsAuthenticated,IsApproved,IsAdminRole]
    def get_queryset(self):
        qs=User.objects.all().order_by('-date_joined')
        status_param=self.request.query_params.get('status')
        if status_param=='pending': qs=qs.filter(is_approved=False)
        elif status_param=='approved': qs=qs.filter(is_approved=True)
        return qs

@api_view(['POST'])
@permission_classes([IsAuthenticated,IsApproved,IsAdminRole])
def approve_user(request, user_id):
    try: user=User.objects.get(pk=user_id)
    except User.DoesNotExist: return Response({'detail':'User not found.'},status=404)
    if user.is_superuser: return Response({'detail':'Superuser is already approved.'},status=400)
    user.is_approved=True
    if request.data.get('role') in ['trainee','trainer']: user.role=request.data['role']
    user.save(update_fields=['is_approved','role'])
    return Response({'message':f'{user.username} approved.','user':UserSerializer(user).data})

@api_view(['POST'])
@permission_classes([IsAuthenticated,IsApproved,IsAdminRole])
def update_user_role(request,user_id):
    try: user=User.objects.get(pk=user_id)
    except User.DoesNotExist: return Response({'detail':'User not found.'},status=404)
    role=request.data.get('role')
    if role not in ['trainee','trainer','admin']: return Response({'detail':'Invalid role.'},status=400)
    if user.is_superuser: return Response({'detail':'Cannot change a superuser role here.'},status=400)
    user.role=role; user.save(update_fields=['role'])
    return Response(UserSerializer(user).data)

# Open learning platform: lectures, assignments, and course discussions.
from .models import CourseLesson, Assignment, AssignmentSubmission, CourseDiscussion
from .serializers import CourseLessonSerializer, AssignmentSerializer, AssignmentSubmissionSerializer, CourseDiscussionSerializer

class CourseLessonViewSet(viewsets.ModelViewSet):
    serializer_class = CourseLessonSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    def get_queryset(self):
        qs = CourseLesson.objects.select_related('course','course__trainer').all()
        course_id = self.request.query_params.get('course')
        if course_id: qs = qs.filter(course_id=course_id)
        user = self.request.user
        if user.role == 'admin' or user.is_superuser: return qs
        # Trainers can also learn: show their own course content plus previews/enrolled courses.
        from django.db.models import Q
        if user.role == 'trainer': return qs.filter(Q(course__trainer=user) | Q(is_preview=True) | Q(course__enrollments__trainee=user)).distinct()
        return qs.filter(Q(is_preview=True) | Q(course__enrollments__trainee=user)).distinct()
    def get_permissions(self):
        if self.action in ['create','update','partial_update','destroy']:
            return [IsAuthenticated(), IsApproved(), IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        course = serializer.validated_data['course']
        if self.request.user.role == 'trainer' and course.trainer_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can only add lectures to your own courses.')
        serializer.save()
    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        if request.user.role == 'trainer' and obj.course.trainer_id != request.user.id:
            return Response({'detail':'You can only edit lectures in your own courses.'}, status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if request.user.role == 'trainer' and obj.course.trainer_id != request.user.id:
            return Response({'detail':'You can only delete lectures in your own courses.'}, status=403)
        return super().destroy(request,*args,**kwargs)

class AssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = AssignmentSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    def get_queryset(self):
        qs = Assignment.objects.select_related('course','course__trainer','created_by').annotate(submission_count=Count('submissions'))
        course_id=self.request.query_params.get('course')
        if course_id: qs=qs.filter(course_id=course_id)
        user = self.request.user
        if user.role == 'admin' or user.is_superuser: return qs
        if user.role == 'trainer':
            from django.db.models import Q
            return qs.filter(Q(course__trainer=user) | Q(is_published=True,course__enrollments__trainee=user)).distinct()
        return qs.filter(is_published=True, course__enrollments__trainee=user).distinct()
    def get_permissions(self):
        if self.action in ['create','update','partial_update','destroy']:
            return [IsAuthenticated(), IsApproved(), IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        course=serializer.validated_data['course']; user=self.request.user
        if user.role=='trainer' and course.trainer_id != user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can only create assignments for your own courses.')
        serializer.save(created_by=user)
    def update(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You can only edit your own assignments.'},status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You can only delete your own assignments.'},status=403)
        return super().destroy(request,*args,**kwargs)
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        assignment=self.get_object(); user=request.user
        if user.role=='admin' or user.is_superuser: return Response({'detail':'Admin accounts do not submit learner assignments.'},status=403)
        if not Enrollment.objects.filter(trainee=user,course=assignment.course).exists(): return Response({'detail':'Enroll in this course before submitting.'},status=403)
        if assignment.due_at and timezone.now()>assignment.due_at: return Response({'detail':'The submission deadline has passed.'},status=400)
        if AssignmentSubmission.objects.filter(assignment=assignment,learner=user).exists(): return Response({'detail':'You have already submitted this assignment.'},status=409)
        serializer=AssignmentSubmissionSerializer(data=request.data,context={'request':request})
        serializer.is_valid(raise_exception=True)
        serializer.save(assignment=assignment,learner=user)
        return Response({'message':'Assignment submitted successfully.','submission':serializer.data},status=201)
    @action(detail=True, methods=['get'])
    def submissions(self, request, pk=None):
        assignment=self.get_object()
        if request.user.role not in ['trainer','admin'] and not request.user.is_superuser: return Response({'detail':'Only trainers can review submissions.'},status=403)
        if request.user.role=='trainer' and assignment.course.trainer_id != request.user.id: return Response({'detail':'You cannot review this assignment.'},status=403)
        qs=assignment.submissions.select_related('learner')
        return Response(AssignmentSubmissionSerializer(qs,many=True,context={'request':request}).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved, IsTrainerOrAdmin])
def review_assignment_submission(request, submission_id):
    try: sub=AssignmentSubmission.objects.select_related('assignment__course').get(pk=submission_id)
    except AssignmentSubmission.DoesNotExist: return Response({'detail':'Submission not found.'},status=404)
    if request.user.role=='trainer' and sub.assignment.course.trainer_id != request.user.id:
        return Response({'detail':'You can only grade submissions for your own courses.'},status=403)
    score=request.data.get('score')
    try: score=int(score)
    except (TypeError,ValueError): return Response({'detail':'Score must be a whole number.'},status=400)
    if score < 0 or score > sub.assignment.max_score: return Response({'detail':f'Score must be between 0 and {sub.assignment.max_score}.'},status=400)
    sub.score=score; sub.feedback=str(request.data.get('feedback',''))[:5000]
    sub.status='revision' if request.data.get('request_revision') else 'reviewed'
    sub.reviewed_at=timezone.now(); sub.save(update_fields=['score','feedback','status','reviewed_at'])
    return Response({'message':'Feedback saved.','submission':AssignmentSubmissionSerializer(sub,context={'request':request}).data})

class AssignmentSubmissionListView(generics.ListAPIView):
    serializer_class=AssignmentSubmissionSerializer
    permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self):
        user=self.request.user
        qs=AssignmentSubmission.objects.select_related('assignment','assignment__course','learner')
        if user.role=='trainee': return qs.filter(learner=user)
        if user.role=='trainer': return qs.filter(assignment__course__trainer=user)
        return qs

class CourseDiscussionViewSet(viewsets.ModelViewSet):
    serializer_class=CourseDiscussionSerializer
    permission_classes=[IsAuthenticated,IsApproved]
    http_method_names=['get','post','delete','head','options']
    def get_queryset(self):
        qs=CourseDiscussion.objects.select_related('course','author','course__trainer')
        course_id=self.request.query_params.get('course')
        if course_id: qs=qs.filter(course_id=course_id)
        user=self.request.user
        if user.role=='admin' or user.is_superuser: return qs
        if user.role=='trainer':
            from django.db.models import Q
            return qs.filter(Q(course__trainer=user) | Q(course__enrollments__trainee=user)).distinct()
        return qs.filter(course__enrollments__trainee=user).distinct()
    def create(self, request, *args, **kwargs):
        course_id=request.data.get('course')
        course=Course.objects.filter(pk=course_id).first()
        if not course: return Response({'detail':'Course not found.'},status=404)
        is_owner=course.trainer_id==request.user.id
        is_enrolled=Enrollment.objects.filter(course_id=course_id,trainee=request.user).exists()
        if not is_enrolled and not is_owner and request.user.role!='admin' and not request.user.is_superuser:
            return Response({'detail':'Enroll in the course to join its discussion.'},status=403)
        serializer=self.get_serializer(data=request.data); serializer.is_valid(raise_exception=True); serializer.save(author=request.user)
        return Response(serializer.data,status=201)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        is_admin = request.user.role == 'admin' or request.user.is_superuser
        is_course_trainer = obj.course.trainer_id == request.user.id
        if obj.author_id != request.user.id and not is_admin and not is_course_trainer:
            return Response({'detail':'You can delete your own posts, or moderate posts in your own course.'},status=403)
        obj.delete(); return Response(status=204)
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved])
def learning_intelligence(request):
    from rest_framework.exceptions import ValidationError
    from .ai_service import get_learning_recommendations

    try:
        max_recommendations = int(request.query_params.get('limit', 5))
    except (TypeError, ValueError):
        raise ValidationError({
            'limit': 'Must be an integer between 1 and 20.'
        })

    if not 1 <= max_recommendations <= 20:
        raise ValidationError({
            'limit': 'Must be between 1 and 20.'
        })

    result = get_learning_recommendations(
        request.user,
        max_recommendations=max_recommendations
    )

    return Response(result.model_dump())