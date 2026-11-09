"""API tests for Part 3 (AI quiz system) and Part 4 (AI learning assistant).

The AI provider boundary (core.ai_features.chat_completion) is patched, so these tests exercise
the real views, permissions, grading, persistence and prompt assembly without network access.
"""
import io
import json
import os
import urllib.error
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Assessment, Attempt, Course, CourseLesson, Enrollment, QuestionSubmission,
                     TutorConversation, TutorMessage, User)

DESCRIPTION = ('Python basics covering variables, loops and functions, with worked examples '
               'that explain how data flows through a small program.')


def quiz_json(n, answer=1):
    return json.dumps([{
        'question_text': f'Question {i} about Python?',
        'options': [f'a{i}', f'b{i}', f'c{i}', f'd{i}'],
        'correct_answer': answer, 'explanation': f'Explanation {i}.', 'topic': 'Python',
    } for i in range(1, n + 1)])


def make_user(name, role='trainee'):
    return User.objects.create_user(username=name, password='StrongPass123!', role=role, is_approved=True)


class AIBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.trainer = make_user('ai_trainer', 'trainer')
        self.other_trainer = make_user('ai_trainer2', 'trainer')
        self.admin = make_user('ai_admin', 'admin')
        self.learner = make_user('ai_learner')
        self.other_learner = make_user('ai_learner2')
        self.course = Course.objects.create(title='Python 101', description=DESCRIPTION, trainer=self.trainer,
                                            competencies=['Python'])
        self.other_course = Course.objects.create(title='Other', description=DESCRIPTION, trainer=self.other_trainer)
        CourseLesson.objects.create(course=self.course, title='Loops', description='UNIQUE-LESSON-TEXT about for loops.', position=1)
        Enrollment.objects.create(trainee=self.learner, course=self.course)

    def as_user(self, user):
        self.client.force_authenticate(user=user)

    def generate(self, user=None, **extra):
        self.as_user(user or self.trainer)
        body = {'course': self.course.id, 'title': 'Draft', 'difficulty': 'beginner', 'question_count': 2}
        body.update(extra)
        with patch('core.ai_features.chat_completion', return_value=quiz_json(body['question_count'])) as completion:
            response = self.client.post('/api/ai/quizzes/generate/', body, format='json')
        return response, completion


class QuizGenerationTests(AIBase):
    def test_learner_cannot_generate(self):
        response, _ = self.generate(user=self.learner)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_generate(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post('/api/ai/quizzes/generate/', {}, format='json').status_code, 401)

    def test_trainer_cannot_generate_for_another_trainers_course(self):
        response, _ = self.generate(course=self.other_course.id)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_generate_for_any_course(self):
        response, _ = self.generate(user=self.admin, course=self.other_course.id)
        self.assertEqual(response.status_code, 201)

    def test_draft_is_unpublished_uses_platform_schema_and_real_course_content(self):
        response, completion = self.generate(question_count=2, difficulty='advanced', topic='loops')
        self.assertEqual(response.status_code, 201)
        draft = Assessment.objects.get(pk=response.data['assessment']['id'])
        self.assertFalse(draft.is_published)
        self.assertEqual(draft.created_by, self.trainer)
        self.assertEqual([q['id'] for q in draft.questions], ['1', '2'])
        self.assertTrue(all(q['text'] and 'question' not in q for q in draft.questions))
        prompt = completion.call_args[0][0][1]['content']
        self.assertIn('UNIQUE-LESSON-TEXT', prompt)
        self.assertIn('Difficulty: advanced', prompt)
        self.assertIn('loops', prompt)
        # The author sees the answer key in the review response.
        self.assertIn('correct_answer', response.data['assessment']['questions'][0])

    def test_lesson_selection_limits_source_material(self):
        other = CourseLesson.objects.create(course=self.course, title='Classes', description='SECOND-LESSON-TEXT about classes.', position=2)
        response, completion = self.generate(lessons=[other.id])
        self.assertEqual(response.status_code, 201)
        prompt = completion.call_args[0][0][1]['content']
        self.assertIn('SECOND-LESSON-TEXT', prompt)
        self.assertNotIn('UNIQUE-LESSON-TEXT', prompt)

    def test_validation_errors(self):
        self.as_user(self.trainer)
        base = {'course': self.course.id}
        bad_bodies = [
            {**base, 'difficulty': 'expert'}, {**base, 'question_count': 0}, {**base, 'question_count': 21},
            {**base, 'question_count': 'x'}, {**base, 'lessons': 'all'}, {'course': 'nope'}, {},
        ]
        with patch('core.ai_features.chat_completion') as completion:
            for body in bad_bodies:
                response = self.client.post('/api/ai/quizzes/generate/', body, format='json')
                self.assertEqual(response.status_code, 400, body)
        completion.assert_not_called()

    def test_course_without_content_is_rejected(self):
        empty = Course.objects.create(title='Tiny', description='Short.', trainer=self.trainer)
        response, completion = self.generate(course=empty.id)
        self.assertEqual(response.status_code, 400)
        completion.assert_not_called()

    def test_unconfigured_provider_returns_503_not_fake_content(self):
        self.as_user(self.trainer)
        with patch.dict(os.environ, {'AI_API_KEY': ''}):
            response = self.client.post('/api/ai/quizzes/generate/', {'course': self.course.id}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Assessment.objects.filter(course=self.course, is_published=False).exists())

    def test_provider_failure_is_graceful_and_does_not_leak_the_key(self):
        self.as_user(self.trainer)
        error = urllib.error.HTTPError('https://x', 500, 'err', {}, io.BytesIO(b'boom'))
        with patch.dict(os.environ, {'AI_API_KEY': 'sk-very-secret'}), patch('urllib.request.urlopen', side_effect=error):
            response = self.client.post('/api/ai/quizzes/generate/', {'course': self.course.id}, format='json')
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('sk-very-secret', response.content.decode())

    def test_status_endpoint_reports_only_a_boolean(self):
        self.as_user(self.learner)
        with patch.dict(os.environ, {'AI_API_KEY': 'sk-very-secret'}):
            response = self.client.get('/api/ai/status/')
        self.assertEqual(response.data, {'configured': True})


class QuizLifecycleSecurityTests(AIBase):
    def publish_generated_quiz(self):
        response, _ = self.generate(question_count=2)
        quiz_id = response.data['assessment']['id']
        self.as_user(self.trainer)
        patched = self.client.patch(f'/api/assessments/{quiz_id}/', {'is_published': True}, format='json')
        self.assertEqual(patched.status_code, 200)
        return Assessment.objects.get(pk=quiz_id)

    def test_trainer_cannot_move_assessment_into_another_trainers_course(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.trainer)
        response = self.client.patch(f'/api/assessments/{quiz.id}/', {'course': self.other_course.id}, format='json')
        self.assertEqual(response.status_code, 403)
        quiz.refresh_from_db()
        self.assertEqual(quiz.course_id, self.course.id)

    def test_learner_cannot_see_unpublished_draft(self):
        response, _ = self.generate()
        self.as_user(self.learner)
        self.assertEqual(self.client.get(f"/api/assessments/{response.data['assessment']['id']}/").status_code, 404)

    def test_published_quiz_hides_answer_key_explanations_and_bank_links_from_learner(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.learner)
        data = self.client.get(f'/api/assessments/{quiz.id}/').data
        for q in data['questions']:
            self.assertTrue(q['text'])
            for hidden in ('correct_answer', 'explanation', 'question_bank_id'):
                self.assertNotIn(hidden, q)

    def test_server_grades_and_client_score_is_ignored(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.learner)
        response = self.client.post(f'/api/assessments/{quiz.id}/submit/', {
            'answers': {'1': 3, '2': 3, 'bogus': 1}, 'score': 100, 'score_percent': 100, 'points': 9999,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['score_percent'], 0)
        attempt = Attempt.objects.get(trainee=self.learner, assessment=quiz)
        self.assertEqual(attempt.score, 0)
        self.assertEqual(attempt.points, 0)
        self.assertNotIn('bogus', attempt.answers)

    def test_results_reveal_answers_and_explanations_only_after_submission(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.learner)
        response = self.client.post(f'/api/assessments/{quiz.id}/submit/', {'answers': {'1': 1, '2': '0'}}, format='json')
        self.assertEqual(response.data['correct_answers'], 1)
        review = {r['question_id']: r for r in response.data['review']}
        self.assertTrue(review['1']['correct'])
        self.assertFalse(review['2']['correct'])
        self.assertEqual(review['2']['correct_answer'], 1)
        self.assertTrue(review['2']['explanation'])

    def test_unpublished_draft_cannot_be_submitted_even_by_its_trainer(self):
        response, _ = self.generate()
        self.as_user(self.trainer)
        result = self.client.post(f"/api/assessments/{response.data['assessment']['id']}/submit/", {'answers': {'1': 1}}, format='json')
        self.assertEqual(result.status_code, 400)

    def test_withdrawn_learner_cannot_open_or_submit_quiz(self):
        quiz = self.publish_generated_quiz()
        Enrollment.objects.filter(trainee=self.learner).delete()
        self.as_user(self.learner)
        self.assertEqual(self.client.get(f'/api/assessments/{quiz.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/assessments/{quiz.id}/submit/', {'answers': {'1': 1}}, format='json').status_code, 404)

    def test_attempts_are_private_to_the_learner_and_course_trainer(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.learner)
        self.client.post(f'/api/assessments/{quiz.id}/submit/', {'answers': {'1': 1, '2': 1}}, format='json')
        self.as_user(self.other_learner)
        self.assertEqual(self.client.get('/api/attempts/').data, [])
        self.as_user(self.other_trainer)
        self.assertEqual(self.client.get('/api/attempts/').data, [])
        self.as_user(self.trainer)
        self.assertEqual(len(self.client.get('/api/attempts/').data), 1)

    def test_quiz_result_feeds_competency_analytics(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.learner)
        self.client.post(f'/api/assessments/{quiz.id}/submit/', {'answers': {'1': 1, '2': 1}}, format='json')
        data = self.client.get('/api/ai/learning-intelligence/').data
        python = next(t for t in data['competency_trends'] if t['competency'] == 'Python')
        self.assertEqual(python['observations'], 1)
        self.assertEqual(python['assessment_average'], 100.0)

    def test_question_bank_does_not_leak_quiz_answers_before_the_quiz_is_taken(self):
        quiz = self.publish_generated_quiz()
        self.as_user(self.trainer)
        linked = self.client.get(f'/api/assessments/{quiz.id}/').data['questions'][0]['question_bank_id']
        self.assertTrue(QuestionSubmission.objects.filter(pk=linked, status='approved').exists())
        self.as_user(self.learner)
        listed = [row['id'] for row in self.client.get('/api/question-submissions/').data]
        self.assertNotIn(linked, listed)
        probe = self.client.post('/api/question-submissions/grade-practice/', {'answers': {str(linked): 1}}, format='json')
        self.assertEqual(probe.status_code, 400)
        self.assertNotIn('correct_answer', probe.content.decode())
        # After the learner has attempted the quiz, practice on its questions unlocks.
        self.client.post(f'/api/assessments/{quiz.id}/submit/', {'answers': {'1': 1, '2': 1}}, format='json')
        unlocked = self.client.post('/api/question-submissions/grade-practice/', {'answers': {str(linked): 1}}, format='json')
        self.assertEqual(unlocked.status_code, 200)

    def test_malformed_questions_are_rejected_on_create(self):
        self.as_user(self.trainer)
        bad = {'course': self.course.id, 'title': 'Bad', 'questions': [
            {'id': 'q1', 'text': 'Q?', 'options': ['A', 'B'], 'correct_answer': 5}]}
        self.assertEqual(self.client.post('/api/assessments/', bad, format='json').status_code, 400)


class TutorTests(AIBase):
    def create_conversation(self, user=None, **body):
        self.as_user(user or self.learner)
        return self.client.post('/api/ai/tutor/conversations/', body, format='json')

    def send(self, conversation_id, text='Explain loops', user=None, reply='Here is an explanation.'):
        self.as_user(user or self.learner)
        with patch('core.ai_features.chat_completion', return_value=reply) as completion:
            response = self.client.post(f'/api/ai/tutor/conversations/{conversation_id}/messages/', {'message': text}, format='json')
        return response, completion

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get('/api/ai/tutor/conversations/').status_code, 401)

    def test_conversation_and_messages_persist_for_the_owner(self):
        created = self.create_conversation()
        self.assertEqual(created.status_code, 201)
        response, _ = self.send(created.data['id'])
        self.assertEqual(response.status_code, 201)
        conversation = TutorConversation.objects.get(pk=created.data['id'])
        self.assertEqual(conversation.user, self.learner)
        self.assertEqual(list(conversation.messages.values_list('role', flat=True)), ['user', 'assistant'])
        self.assertEqual(conversation.title, 'Explain loops')
        detail = self.client.get(f"/api/ai/tutor/conversations/{created.data['id']}/")
        self.assertEqual([m['content'] for m in detail.data['messages']], ['Explain loops', 'Here is an explanation.'])

    def test_other_users_cannot_read_write_or_delete_a_conversation(self):
        cid = self.create_conversation().data['id']
        self.send(cid)
        self.as_user(self.other_learner)
        self.assertEqual(self.client.get(f'/api/ai/tutor/conversations/{cid}/').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/ai/tutor/conversations/{cid}/').status_code, 404)
        response, completion = self.send(cid, user=self.other_learner)
        self.assertEqual(response.status_code, 404)
        completion.assert_not_called()
        self.assertEqual(self.client.get('/api/ai/tutor/conversations/').data, [])
        self.as_user(self.admin)
        self.assertEqual(self.client.get(f'/api/ai/tutor/conversations/{cid}/').status_code, 404)
        self.assertEqual(TutorMessage.objects.filter(conversation_id=cid).count(), 2)

    def test_course_context_requires_enrollment(self):
        denied = self.create_conversation(user=self.other_learner, course=self.course.id)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.create_conversation(course=self.course.id).status_code, 201)

    def test_prompt_uses_course_competency_and_quiz_data_and_history(self):
        self.learner.competencies = [{'name': 'Python', 'current_score': 55}]
        self.learner.save()
        quiz = Assessment.objects.create(course=self.course, title='Loops quiz', created_by=self.trainer, questions=[
            {'id': '1', 'text': 'What does a for loop do?', 'options': ['a', 'b', 'c', 'd'], 'correct_answer': 0}])
        Attempt.objects.create(trainee=self.learner, assessment=quiz, score=40, total_questions=1, question_results={'1': False})
        cid = self.create_conversation(course=self.course.id).data['id']
        self.send(cid, text='first question', reply='first answer')
        response, completion = self.send(cid, text='second question')
        self.assertEqual(response.status_code, 201)
        messages = completion.call_args[0][0]
        system = messages[0]['content']
        self.assertIn('UNIQUE-LESSON-TEXT', system)          # course/lesson context
        self.assertIn('Python', system)                       # competency information
        self.assertIn('Loops quiz', system)                   # quiz performance
        self.assertIn('What does a for loop do?', system)     # missed question
        self.assertEqual([m['content'] for m in messages[1:]], ['first question', 'first answer', 'second question'])

    def test_prompt_never_contains_another_learners_data(self):
        quiz = Assessment.objects.create(course=self.course, title='Private quiz', created_by=self.trainer, questions=[
            {'id': '1', 'text': 'Q?', 'options': ['a', 'b'], 'correct_answer': 0}])
        Enrollment.objects.create(trainee=self.other_learner, course=self.course)
        Attempt.objects.create(trainee=self.other_learner, assessment=quiz, score=12, total_questions=1)
        cid = self.create_conversation(course=self.course.id).data['id']
        _, completion = self.send(cid)
        self.assertNotIn('Private quiz', completion.call_args[0][0][0]['content'])

    def test_withdrawn_learner_loses_course_context(self):
        cid = self.create_conversation(course=self.course.id).data['id']
        Enrollment.objects.filter(trainee=self.learner, course=self.course).delete()
        response, completion = self.send(cid)
        self.assertEqual(response.status_code, 403)
        completion.assert_not_called()
        self.assertEqual(TutorMessage.objects.filter(conversation_id=cid).count(), 0)

    def test_general_conversation_includes_no_course_material(self):
        cid = self.create_conversation().data['id']
        _, completion = self.send(cid)
        self.assertNotIn('UNIQUE-LESSON-TEXT', completion.call_args[0][0][0]['content'])

    def test_provider_failure_returns_error_and_stores_nothing(self):
        cid = self.create_conversation().data['id']
        self.as_user(self.learner)
        error = urllib.error.HTTPError('https://x', 401, 'err', {}, io.BytesIO(b'bad key sk-very-secret'))
        with patch.dict(os.environ, {'AI_API_KEY': 'sk-very-secret'}), patch('urllib.request.urlopen', side_effect=error):
            response = self.client.post(f'/api/ai/tutor/conversations/{cid}/messages/', {'message': 'hi'}, format='json')
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('sk-very-secret', response.content.decode())
        self.assertEqual(TutorMessage.objects.filter(conversation_id=cid).count(), 0)

    def test_unconfigured_provider_returns_503_without_canned_reply(self):
        cid = self.create_conversation().data['id']
        self.as_user(self.learner)
        with patch.dict(os.environ, {'AI_API_KEY': ''}):
            response = self.client.post(f'/api/ai/tutor/conversations/{cid}/messages/', {'message': 'hi'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(TutorMessage.objects.filter(conversation_id=cid).count(), 0)

    def test_message_validation(self):
        cid = self.create_conversation().data['id']
        self.as_user(self.learner)
        for text in ('', '   ', 'x' * 6001):
            self.assertEqual(self.client.post(f'/api/ai/tutor/conversations/{cid}/messages/', {'message': text}, format='json').status_code, 400)

    def test_owner_can_delete_conversation(self):
        cid = self.create_conversation().data['id']
        self.send(cid)
        self.assertEqual(self.client.delete(f'/api/ai/tutor/conversations/{cid}/').status_code, 204)
        self.assertFalse(TutorMessage.objects.filter(conversation_id=cid).exists())
