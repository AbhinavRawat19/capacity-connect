"""Create a realistic, repeatable dataset for testing Capacity Connect as learner/trainer/admin.

Run from backend/: python manage.py seed_student_data
Demo password for all accounts created/managed by this command: DemoPass123!
This command is additive and idempotent for the records it creates; it does not delete data.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    User, Course, Enrollment, CourseLesson, Assessment, Attempt,
    Assignment, AssignmentSubmission, QuestionSubmission, CourseDiscussion,
)

PASSWORD = "DemoPass123!"


class Command(BaseCommand):
    help = "Seed learner, trainer, course, quiz, assignment, discussion and question-bank demo data."

    def upsert_user(self, username, *, role, email, first_name, last_name,
                    department, bio, competencies, approved=True, staff=False):
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email, "first_name": first_name, "last_name": last_name,
                "role": role, "department": department, "bio": bio,
                "competencies": competencies, "is_approved": approved,
                "is_staff": staff,
            },
        )
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.department = department
        user.bio = bio
        user.competencies = competencies
        user.is_approved = approved
        user.is_staff = staff
        user.set_password(PASSWORD)
        user.save()
        return user

    def handle(self, *args, **options):
        now = timezone.now()
        admin = self.upsert_user(
            "demo_admin", role="admin", email="admin.demo@example.com",
            first_name="Avery", last_name="Admin", department="Platform Operations",
            bio="Demo administrator for testing account management and platform oversight.",
            competencies=["Platform administration", "Learning analytics"], approved=True, staff=True,
        )
        trainer1 = self.upsert_user(
            "demo_trainer", role="trainer", email="trainer@example.com",
            first_name="Morgan", last_name="Sharma", department="Computer Science",
            bio="Teaches programming, databases and practical cybersecurity.",
            competencies=["Python", "SQL", "Cybersecurity", "Networking"], approved=True,
        )
        trainer2 = self.upsert_user(
            "demo_trainer2", role="trainer", email="trainer2.demo@example.com",
            first_name="Jordan", last_name="Verma", department="Data and Analytics",
            bio="Teaches data analysis, statistics and responsible data handling.",
            competencies=["Python", "Data Analysis", "Statistics", "SQL"], approved=True,
        )
        pending_trainer = self.upsert_user(
            "demo_pending_trainer", role="trainer", email="pending.trainer@example.com",
            first_name="Taylor", last_name="Pending", department="Cybersecurity",
            bio="Trainer account intentionally left unapproved to test the approval workflow.",
            competencies=["Cybersecurity", "Networking"], approved=False,
        )

        learner_specs = [
            ("student_aarav", "Aarav", "Mehta", "Python", ["Python", "Programming fundamentals"], "beginner"),
            ("student_isha", "Isha", "Rao", "Cybersecurity", ["Cybersecurity", "Networking", "Linux"], "intermediate"),
            ("student_riya", "Riya", "Singh", "Data Analytics", ["Python", "Data Analysis", "Statistics", "SQL"], "intermediate"),
            ("student_karan", "Karan", "Das", "Database Systems", ["SQL", "Databases", "Python"], "beginner"),
            ("student_ananya", "Ananya", "Joshi", "Computer Science", ["Python", "Cybersecurity", "SQL", "Communication"], "advanced"),
            ("student_dev", "Dev", "Kumar", "Computer Science", ["Programming fundamentals", "Networking"], "beginner"),
        ]
        learners = {}
        for username, first, last, dept, skills, _level in learner_specs:
            learners[username] = self.upsert_user(
                username, role="trainee", email=f"{username}@example.com",
                first_name=first, last_name=last, department=dept,
                bio=f"Demo learner profile for testing Capacity Connect features. Interests: {', '.join(skills)}.",
                competencies=[{"name": skill, "current_score": score, "target_score": 80}
                              for skill, score in zip(skills, [45, 60, 72, 35])],
                approved=True,
            )

        course_specs = [
            ("Python Programming: Zero to One", "Programming", "beginner", 8,
             "Build confidence with Python syntax, functions, collections and small programs.",
             ["Python", "Programming fundamentals"], trainer1),
            ("Cybersecurity Fundamentals", "Cybersecurity", "beginner", 6,
             "Learn security principles, account protection, networking basics and threat awareness.",
             ["Cybersecurity", "Networking", "Linux"], trainer1),
            ("SQL and Database Essentials", "Database", "beginner", 7,
             "Learn relational data, SELECT queries, filtering, joins and data integrity.",
             ["SQL", "Databases"], trainer1),
            ("Practical Data Analysis with Python", "Data Analytics", "intermediate", 10,
             "Use Python to clean, explore and communicate insights from structured data.",
             ["Python", "Data Analysis", "Statistics", "SQL"], trainer2),
        ]
        courses = {}
        for title, category, level, hours, description, competencies, trainer in course_specs:
            course, _ = Course.objects.get_or_create(title=title, defaults={
                "category": category, "level": level, "duration_hours": hours,
                "description": description, "competencies": competencies,
                "trainer": trainer, "is_published": True,
            })
            changed = False
            for field, value in {"category": category, "level": level, "duration_hours": hours,
                                 "description": description, "competencies": competencies,
                                 "trainer": trainer, "is_published": True}.items():
                if getattr(course, field) != value:
                    setattr(course, field, value); changed = True
            if changed:
                course.save()
            courses[title] = course

        lesson_specs = {
            "Python Programming: Zero to One": [
                ("Variables and data types", "Work with strings, numbers, booleans and type conversion.", 1, 15),
                ("Conditions and loops", "Use branching and iteration to solve small problems.", 2, 20),
                ("Functions and collections", "Write reusable functions and work with lists and dictionaries.", 3, 25),
            ],
            "Cybersecurity Fundamentals": [
                ("The CIA triad", "Confidentiality, integrity and availability in practical systems.", 1, 12),
                ("Passwords and MFA", "Protect accounts with unique passwords and multi-factor authentication.", 2, 14),
                ("Recognizing phishing", "Spot deceptive messages, links and social-engineering attempts.", 3, 18),
            ],
            "SQL and Database Essentials": [
                ("Relational database basics", "Tables, rows, columns, primary keys and foreign keys.", 1, 16),
                ("SELECT and WHERE", "Retrieve and filter data using SQL queries.", 2, 20),
                ("JOIN and aggregation", "Combine related tables and summarize results.", 3, 25),
            ],
            "Practical Data Analysis with Python": [
                ("Preparing a dataset", "Identify missing values and inconsistent records.", 1, 20),
                ("Exploratory analysis", "Summarize distributions, compare groups and test assumptions.", 2, 25),
                ("Communicating findings", "Turn evidence into a clear and responsible data story.", 3, 20),
            ],
        }
        lessons = {}
        for title, specs in lesson_specs.items():
            course = courses[title]
            for lesson_title, description, position, duration in specs:
                lesson, _ = CourseLesson.objects.get_or_create(
                    course=course, title=lesson_title,
                    defaults={"description": description, "position": position,
                              "duration_minutes": duration, "is_preview": position == 1,
                              "video_url": ""},
                )
                lessons[(title, lesson_title)] = lesson

        quiz_specs = {
            "Python Programming: Zero to One": ("Python Fundamentals Check", [
                {"id": "py1", "text": "Which keyword defines a named function in Python?", "options": ["func", "def", "function", "method"], "correct_answer": 1, "explanation": "The def keyword defines a function."},
                {"id": "py2", "text": "What is the result of 7 // 2?", "options": ["3.5", "4", "3", "2"], "correct_answer": 2, "explanation": "Floor division returns the integer quotient 3."},
                {"id": "py3", "text": "Which collection is mutable?", "options": ["tuple", "str", "list", "frozenset"], "correct_answer": 2, "explanation": "Lists can be changed after creation."},
                {"id": "py4", "text": "What does len([4, 5, 6]) return?", "options": ["2", "3", "4", "6"], "correct_answer": 1, "explanation": "The list contains three items."},
            ]),
            "Cybersecurity Fundamentals": ("Cybersecurity Essentials Check", [
                {"id": "cy1", "text": "What does confidentiality protect?", "options": ["Only uptime", "Information from unauthorized access", "Screen brightness", "Network speed"], "correct_answer": 1, "explanation": "Confidentiality restricts information access to authorized parties."},
                {"id": "cy2", "text": "Which is the strongest account practice?", "options": ["Reuse passwords", "Use a unique password and MFA", "Share passwords", "Use your birthday"], "correct_answer": 1, "explanation": "Unique passwords and MFA reduce account compromise risk."},
                {"id": "cy3", "text": "Phishing is primarily an attempt to…", "options": ["Improve backups", "Trick people into unsafe actions or revealing information", "Compress files", "Patch software"], "correct_answer": 1, "explanation": "Phishing uses deceptive communications to manipulate victims."},
                {"id": "cy4", "text": "What does least privilege mean?", "options": ["Everyone is an admin", "Give only the access needed", "Disable all logs", "Share one account"], "correct_answer": 1, "explanation": "Users should receive only the permissions needed for their tasks."},
            ]),
            "SQL and Database Essentials": ("SQL Skills Check", [
                {"id": "sql1", "text": "Which statement retrieves rows?", "options": ["SELECT", "PUSH", "FETCHTABLE", "OPEN"], "correct_answer": 0, "explanation": "SELECT queries data from tables or views."},
                {"id": "sql2", "text": "Which clause filters rows?", "options": ["ORDER BY", "WHERE", "GROUP BY", "JOIN"], "correct_answer": 1, "explanation": "WHERE filters rows based on a condition."},
                {"id": "sql3", "text": "What is a primary key used for?", "options": ["Styling a table", "Uniquely identifying each row", "Sorting every query", "Encrypting the database"], "correct_answer": 1, "explanation": "A primary key uniquely identifies a row."},
                {"id": "sql4", "text": "Which clause sorts query results?", "options": ["SORT", "ORDER BY", "ARRANGE", "RANK BY"], "correct_answer": 1, "explanation": "ORDER BY sorts the returned rows."},
            ]),
            "Practical Data Analysis with Python": ("Data Analysis Check", [
                {"id": "da1", "text": "What should you do before analyzing a dataset?", "options": ["Ignore missing values", "Inspect quality and structure", "Delete all columns", "Assume it is correct"], "correct_answer": 1, "explanation": "Data quality checks help prevent misleading conclusions."},
                {"id": "da2", "text": "Which statistic is less sensitive to extreme outliers?", "options": ["Mean", "Median", "Maximum", "Range"], "correct_answer": 1, "explanation": "The median is robust to extreme values."},
                {"id": "da3", "text": "Correlation alone proves causation.", "options": ["Always true", "False", "Only for large data", "Only for charts"], "correct_answer": 1, "explanation": "Correlation alone does not establish a causal relationship."},
                {"id": "da4", "text": "A good chart should primarily…", "options": ["Hide uncertainty", "Make the evidence understandable", "Use as many colors as possible", "Omit labels"], "correct_answer": 1, "explanation": "Clear labels and appropriate encodings help people interpret evidence."},
            ]),
        }
        assessments = {}
        for title, (quiz_title, questions) in quiz_specs.items():
            assessment, _ = Assessment.objects.get_or_create(
                course=courses[title], title=quiz_title,
                defaults={"instructions": "Choose the best answer for each question. Demo quiz data is provided for feature testing.",
                          "deadline": now + timedelta(days=30), "duration_minutes": 15,
                          "questions": questions, "created_by": courses[title].trainer,
                          "is_published": True},
            )
            assessments[title] = assessment

        assignment_specs = {
            "Python Programming: Zero to One": ("Mini project: CLI calculator", "Build a command-line calculator. Validate inputs and handle division by zero.", 100),
            "Cybersecurity Fundamentals": ("Personal security checklist", "Write a checklist of at least eight steps to protect accounts and devices. Explain three of your choices.", 100),
            "SQL and Database Essentials": ("Design a small library database", "Propose tables for books and members, identify keys, and write five SQL queries.", 100),
            "Practical Data Analysis with Python": ("Data quality mini-report", "Describe how you would inspect missing values, outliers and potential bias before analysis.", 100),
        }
        assignments = {}
        for title, (assignment_title, instructions, max_score) in assignment_specs.items():
            assignment, _ = Assignment.objects.get_or_create(
                course=courses[title], title=assignment_title,
                defaults={"instructions": instructions, "due_at": now + timedelta(days=21),
                          "max_score": max_score, "is_published": True,
                          "created_by": courses[title].trainer},
            )
            assignments[title] = assignment

        # Enrollments deliberately cover untouched, in-progress and completed states.
        enrollment_plan = {
            "student_aarav": [("Python Programming: Zero to One", 35, False), ("SQL and Database Essentials", 0, False)],
            "student_isha": [("Cybersecurity Fundamentals", 100, True), ("Python Programming: Zero to One", 65, False)],
            "student_riya": [("Practical Data Analysis with Python", 70, False), ("SQL and Database Essentials", 100, True)],
            "student_karan": [("SQL and Database Essentials", 20, False)],
            "student_ananya": [("Python Programming: Zero to One", 100, True), ("Cybersecurity Fundamentals", 100, True), ("Practical Data Analysis with Python", 45, False)],
            "student_dev": [("Cybersecurity Fundamentals", 0, False)],
        }
        enrollments = {}
        for username, plan in enrollment_plan.items():
            learner = learners[username]
            for title, progress, completed in plan:
                enrollment, _ = Enrollment.objects.get_or_create(
                    trainee=learner, course=courses[title],
                    defaults={"progress": progress, "completed": completed},
                )
                if enrollment.progress != progress or enrollment.completed != completed:
                    enrollment.progress = progress; enrollment.completed = completed
                    enrollment.save(update_fields=["progress", "completed"])
                enrollments[(username, title)] = enrollment

        # Seed submitted quiz attempts with varied results for history, dashboards and leaderboards.
        attempt_plan = [
            ("student_aarav", "Python Programming: Zero to One", 3),
            ("student_isha", "Cybersecurity Fundamentals", 4),
            ("student_isha", "Python Programming: Zero to One", 2),
            ("student_riya", "Practical Data Analysis with Python", 3),
            ("student_riya", "SQL and Database Essentials", 4),
            ("student_karan", "SQL and Database Essentials", 2),
            ("student_ananya", "Python Programming: Zero to One", 4),
            ("student_ananya", "Cybersecurity Fundamentals", 3),
        ]
        for username, title, correct_count in attempt_plan:
            assessment = assessments[title]
            questions = assessment.questions or []
            answers, results = {}, {}
            for index, question in enumerate(questions):
                correct = index < correct_count
                chosen = question.get("correct_answer", 0) if correct else (question.get("correct_answer", 0) + 1) % max(1, len(question.get("options", [])))
                answers[str(question.get("id", index))] = chosen
                results[str(question.get("id", index))] = correct
            Attempt.objects.update_or_create(
                trainee=learners[username], assessment=assessment,
                defaults={"answers": answers,
                          "score": round(correct_count / len(questions) * 100, 2) if questions else 0,
                          "total_questions": len(questions), "question_timings": {},
                          "question_results": results, "points": correct_count * 10},
            )


        # Assignment submissions cover submitted, reviewed and revision-requested states.
        submission_plan = [
            ("student_aarav", "Python Programming: Zero to One", "I implemented arithmetic operations and input validation.", "submitted", None, ""),
            ("student_isha", "Cybersecurity Fundamentals", "I enabled MFA, used unique passwords, updated devices and reviewed account sessions.", "reviewed", 88, "Clear, practical checklist. Add a short explanation of recovery codes."),
            ("student_riya", "Practical Data Analysis with Python", "I would inspect missingness, ranges, duplicates and sampling bias before modeling.", "revision", 62, "Please add a concrete example of how you would handle missing values."),
            ("student_karan", "SQL and Database Essentials", "Books(book_id, title) and Members(member_id, name) use primary keys.", "submitted", None, ""),
            ("student_ananya", "Cybersecurity Fundamentals", "My checklist covers MFA, password managers, updates, backups and phishing awareness.", "reviewed", 95, "Strong submission with actionable steps."),
        ]
        for username, title, response, status, score, feedback in submission_plan:
            sub, _ = AssignmentSubmission.objects.get_or_create(
                assignment=assignments[title], learner=learners[username],
                defaults={"response_text": response, "status": status, "score": score,
                          "feedback": feedback, "reviewed_at": now if status != "submitted" else None},
            )

        # Question bank covers the review queue and author feedback states.
        question_plan = [
            ("student_aarav", "What is the output of len([2, 4, 6])?", ["2", "3", "4", "6"], 1, "The list has three elements.", "Python", "beginner", "pending", "", "Python Programming: Zero to One", "Variables and data types"),
            ("student_isha", "Which control adds a second verification step at login?", ["MFA", "Plain HTTP", "Shared account", "Open Wi-Fi"], 0, "MFA asks for an additional verification factor.", "Cybersecurity", "beginner", "approved", "Good question.", "Cybersecurity Fundamentals", "Passwords and MFA"),
            ("student_riya", "Which measure is robust to a very large outlier?", ["Mean", "Median", "Maximum", "Sum"], 1, "The median is less affected by extreme values.", "Data Analysis", "intermediate", "revision", "Clarify the context in the question.", "Practical Data Analysis with Python", "Exploratory analysis"),
            ("student_karan", "Which SQL clause filters rows?", ["WHERE", "ORDER BY", "SELECT", "JOIN"], 0, "WHERE filters records based on a condition.", "SQL", "beginner", "rejected", "This overlaps with an existing question; please submit a more original one.", "SQL and Database Essentials", "SELECT and WHERE"),
            ("student_ananya", "What does least privilege recommend?", ["Give everyone admin rights", "Grant only required permissions", "Disable authentication", "Share credentials"], 1, "Least privilege limits access to what is needed.", "Cybersecurity", "intermediate", "approved", "Clear and useful.", "Cybersecurity Fundamentals", "The CIA triad"),
            ("student_dev", "What does a primary key do in a relational table?", ["Uniquely identifies a row", "Encrypts all rows", "Sorts all columns", "Creates a backup"], 0, "A primary key uniquely identifies a row.", "Databases", "beginner", "pending", "", "SQL and Database Essentials", "Relational database basics"),
        ]
        for username, question_text, opts, answer, explanation, topic, difficulty, status, feedback, course_title, lesson_title in question_plan:
            defaults = {
                "course": courses[course_title], "lesson": lessons[(course_title, lesson_title)],
                "options": opts, "correct_answer": answer, "explanation": explanation,
                "topic": topic, "difficulty": difficulty, "status": status,
                "review_feedback": feedback,
                "reviewed_by": trainer1 if status in ("approved", "rejected", "revision") else None,
                "reviewed_at": now if status in ("approved", "rejected", "revision") else None,
                "published_at": now if status == "approved" else None,
            }
            QuestionSubmission.objects.get_or_create(
                submitted_by=learners[username], question_text=question_text,
                defaults=defaults,
            )

        discussion_posts = [
            ("student_aarav", "Python Programming: Zero to One", "I found functions easier to understand after writing a small calculator. Any advice for testing edge cases?"),
            ("student_isha", "Cybersecurity Fundamentals", "For the security checklist, should we include backup codes as well as MFA?"),
            ("student_riya", "Practical Data Analysis with Python", "How do you decide whether an outlier is an error or a meaningful observation?"),
            ("student_ananya", "Cybersecurity Fundamentals", "A password manager plus MFA is a useful baseline; remember to protect recovery methods too."),
        ]
        for username, title, body in discussion_posts:
            CourseDiscussion.objects.get_or_create(
                course=courses[title], author=learners[username], body=body,
            )

        self.stdout.write(self.style.SUCCESS("Capacity Connect student demo data is ready."))
        self.stdout.write("Demo accounts (password for all: DemoPass123!)")
        self.stdout.write("  Admin:   demo_admin")
        self.stdout.write("  Trainer: demo_trainer  |  demo_trainer2")
        self.stdout.write("  Pending trainer (approval workflow): demo_pending_trainer")
        self.stdout.write("  Learners: student_aarav, student_isha, student_riya, student_karan, student_ananya, student_dev")
        self.stdout.write("Created/ensured: 4 courses, 12 lessons, 4 quizzes, 4 assignments, varied enrollments/attempts/submissions, question-bank review states and discussions.")
