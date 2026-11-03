from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import User, Course, CourseLesson, Assessment, Assignment, QuestionSubmission

class Command(BaseCommand):
    help = 'Add sample courses, lessons, quizzes, assignments, and approved questions for local testing.'

    def handle(self, *args, **options):
        trainer, created = User.objects.get_or_create(
            username='demo_trainer',
            defaults={'email':'trainer@example.com','first_name':'Demo','last_name':'Trainer','role':'trainer','department':'Computer Science','bio':'Sample trainer account for local testing.','is_approved':True,'is_staff':False},
        )
        if created:
            trainer.set_password('DemoTrainer123!')
            trainer.save()
        else:
            changed = False
            if trainer.role != 'trainer': trainer.role='trainer'; changed=True
            if not trainer.is_approved: trainer.is_approved=True; changed=True
            if changed: trainer.save()

        course_specs = [
            {'title':'Python Programming: Zero to One','category':'Programming','level':'beginner','duration_hours':6,'description':'Learn variables, data types, conditionals, loops, functions, and lists through practical examples.','competencies':['Python','Programming fundamentals'],'price':'19.99','currency':'USD'},
            {'title':'Cybersecurity Fundamentals','category':'Cybersecurity','level':'beginner','duration_hours':4,'description':'Explore the CIA triad, common threats, authentication, safe networking, and basic security hygiene.','competencies':['Cybersecurity','Networking','Security basics'],'price':'29.99','currency':'USD'},
            {'title':'SQL and Database Essentials','category':'Database','level':'beginner','duration_hours':5,'description':'Practice relational database concepts, SELECT queries, filtering, sorting, and joins.','competencies':['SQL','Databases'],'price':'0.00','currency':'USD'},
        ]
        courses=[]
        for spec in course_specs:
            course, _ = Course.objects.update_or_create(title=spec['title'], defaults={**spec,'trainer':trainer,'is_published':True})
            courses.append(course)

        lesson_specs = [
            (0,'Getting started with Python','Understand the interpreter, variables, and basic data types.','https://www.youtube.com/watch?v=kqtD5dpn9C8',12),
            (0,'Conditions and loops','Use if/else, for loops, and while loops to control program flow.','https://www.youtube.com/watch?v=6iF8Xb7Z3wQ',18),
            (1,'The CIA triad','Understand confidentiality, integrity, and availability.','https://www.youtube.com/watch?v=ooJSgsB5fIE',10),
            (1,'Passwords and MFA','Learn safer password practices and multi-factor authentication.','https://www.youtube.com/watch?v=0A5XG9XzY1I',9),
            (2,'Your first SQL query','Retrieve rows with SELECT and filter with WHERE.','https://www.youtube.com/watch?v=HXV3zeQKqGY',15),
        ]
        for idx,title,description,url,duration in lesson_specs:
            CourseLesson.objects.get_or_create(course=courses[idx],title=title,defaults={'description':description,'video_url':url,'duration_minutes':duration,'position':CourseLesson.objects.filter(course=courses[idx]).count()+1,'is_preview':True})

        quiz_specs = [
            (0,'Python Basics Quiz','Check your understanding of Python fundamentals.',[
                {'id':'py1','text':'Which keyword defines a function in Python?','options':['func','def','function','lambda'], 'correct_answer':1,'explanation':'The def keyword defines a named function.'},
                {'id':'py2','text':'What is the result of 3 // 2 in Python?','options':['1.5','2','1','0'], 'correct_answer':2,'explanation':'// performs floor division, so 3 // 2 is 1.'},
                {'id':'py3','text':'Which type stores a sequence of mutable items?','options':['tuple','str','list','int'], 'correct_answer':2,'explanation':'Lists are ordered and mutable.'},
            ]),
            (1,'Cybersecurity Fundamentals Quiz','Practice basic security concepts.',[
                {'id':'cy1','text':'What does the C in the CIA triad stand for?','options':['Control','Confidentiality','Compliance','Connectivity'], 'correct_answer':1,'explanation':'Confidentiality means information is only accessible to authorized parties.'},
                {'id':'cy2','text':'Which is the strongest account protection among these choices?','options':['Reuse one password','Use your birthday','Use a unique password and MFA','Share passwords with friends'], 'correct_answer':2,'explanation':'A unique password plus multi-factor authentication adds protection.'},
                {'id':'cy3','text':'What is phishing?','options':['A database backup','A social-engineering attempt to trick people','A type of CPU','A secure encryption standard'], 'correct_answer':1,'explanation':'Phishing uses deceptive messages or sites to steal information or prompt unsafe actions.'},
            ]),
            (2,'SQL Starter Quiz','Review SELECT, WHERE, and ordering.',[
                {'id':'sql1','text':'Which SQL statement retrieves data?','options':['GET','FETCH ALL','SELECT','OPEN'], 'correct_answer':2,'explanation':'SELECT retrieves data from one or more tables.'},
                {'id':'sql2','text':'Which clause filters rows?','options':['WHERE','ORDER BY','GROUP BY','FROM'], 'correct_answer':0,'explanation':'WHERE filters rows based on a condition.'},
                {'id':'sql3','text':'Which clause sorts query results?','options':['SORT','ORDER BY','ARRANGE','RANK'], 'correct_answer':1,'explanation':'ORDER BY sorts results by one or more columns.'},
            ]),
        ]
        # Keep demo assessments deterministic and mirror every assessment question into the approved Question Bank.
        lesson_by_course = {course.id: list(CourseLesson.objects.filter(course=course).order_by('position')) for course in courses}
        for idx,title,instructions,questions in quiz_specs:
            linked_questions = []
            for q in questions:
                bank_item = QuestionSubmission.objects.filter(question_text__iexact=q['text'], course=courses[idx]).first()
                if bank_item is None:
                    bank_item = QuestionSubmission.objects.create(
                        submitted_by=trainer, course=courses[idx],
                        lesson=lesson_by_course[courses[idx].id][0] if lesson_by_course[courses[idx].id] else None,
                        question_text=q['text'], options=q['options'], correct_answer=q['correct_answer'],
                        explanation=q.get('explanation',''), topic=courses[idx].category, difficulty='beginner',
                        status='approved', reviewed_by=trainer, reviewed_at=timezone.now(), published_at=timezone.now())
                else:
                    bank_item.options=q['options']; bank_item.correct_answer=q['correct_answer']; bank_item.explanation=q.get('explanation','')
                    bank_item.status='approved'; bank_item.reviewed_by=trainer; bank_item.reviewed_at=bank_item.reviewed_at or timezone.now(); bank_item.published_at=bank_item.published_at or timezone.now()
                    if not bank_item.lesson and lesson_by_course[courses[idx].id]: bank_item.lesson=lesson_by_course[courses[idx].id][0]
                    bank_item.save()
                linked = dict(q)
                linked['question_bank_id'] = bank_item.id
                linked_questions.append(linked)
            assessment, _ = Assessment.objects.get_or_create(course=courses[idx], title=title, defaults={'instructions':instructions,'duration_minutes':10,'created_by':trainer,'is_published':True})
            assessment.instructions=instructions; assessment.duration_minutes=10; assessment.questions=linked_questions; assessment.created_by=trainer; assessment.is_published=True
            assessment.save()

        assignment_specs = [
            (0,'Build a CLI Calculator','Write a Python command-line calculator supporting addition, subtraction, multiplication, and division. Validate input and handle division by zero.',100),
            (1,'Personal Security Checklist','Create a one-page checklist with at least eight practical steps to secure personal accounts and devices. Explain why any three steps matter.',100),
            (2,'Design a Small Library Database','Design tables for books and members. Submit table columns, primary keys, and five example SQL queries using SELECT and WHERE.',100),
        ]
        for idx,title,instructions,max_score in assignment_specs:
            Assignment.objects.get_or_create(course=courses[idx],title=title,defaults={'instructions':instructions,'max_score':max_score,'due_at':timezone.now()+timedelta(days=14),'created_by':trainer,'is_published':True})

        questions = [
            ('What is the output of print(type([]).__name__)?',['tuple','list','dict','set'],1,'An empty list is still an object of type list.','Python basics','beginner'),
            ('Which security principle means granting only the access needed for a task?',['Open access','Least privilege','Public by default','Single sign-on'],1,'Least privilege limits permissions to what is necessary.','Cybersecurity','beginner'),
            ('Which SQL keyword removes duplicate rows from query results?',['UNIQUE','DISTINCT','DIFFERENT','ONLY'],1,'SELECT DISTINCT returns unique rows for the selected columns.','SQL','beginner'),
        ]
        lesson_lookup = { (lesson.course_id, lesson.title): lesson for lesson in CourseLesson.objects.filter(course__in=courses) }
        question_links = [(courses[0], 'Getting started with Python'), (courses[1], 'The CIA triad'), (courses[2], 'Your first SQL query')]
        for (text,opts,answer,explanation,topic,difficulty),(course,lesson_title) in zip(questions, question_links):
            lesson = lesson_lookup.get((course.id, lesson_title))
            item, created = QuestionSubmission.objects.get_or_create(question_text=text,submitted_by=trainer,defaults={'course':course,'lesson':lesson,'options':opts,'correct_answer':answer,'explanation':explanation,'topic':topic,'difficulty':difficulty,'status':'approved','reviewed_by':trainer,'reviewed_at':timezone.now(),'published_at':timezone.now()})
            if not created and (item.course_id != course.id or item.lesson_id != (lesson.id if lesson else None)):
                item.course=course; item.lesson=lesson; item.save(update_fields=['course','lesson'])

        self.stdout.write(self.style.SUCCESS('Demo data is ready: assessment questions are synchronized to the approved Question Bank; courses, lessons, quizzes, and assignments are up to date.'))
        self.stdout.write('Sample trainer username: demo_trainer')
        self.stdout.write('Sample trainer password (only if newly created): DemoTrainer123!')
