import io
import json
import os
import urllib.error
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase

from .ai_features import AIProviderError, chat_completion, generate_quiz_questions


def question(n=1, answer=0):
    return {
        'question_text': f'What is concept {n}?',
        'options': [f'A{n}', f'B{n}', f'C{n}', f'D{n}'],
        'correct_answer': answer, 'explanation': f'Because {n}.', 'topic': 'Programming',
    }


class QuizGenerationValidationTests(SimpleTestCase):
    @patch('core.ai_features.chat_completion')
    def test_valid_questions_use_platform_assessment_schema(self, completion):
        completion.return_value = json.dumps([question(1)])
        result = generate_quiz_questions('Variables store values.', 'Variables', 'beginner', 1)
        # The learner UI, grader and question-bank sync all read "text".
        self.assertEqual(result[0]['text'], 'What is concept 1?')
        self.assertEqual(result[0]['correct_answer'], 0)
        self.assertEqual(len(result[0]['options']), 4)

    @patch('core.ai_features.chat_completion')
    def test_markdown_fenced_json_is_accepted(self, completion):
        completion.return_value = '```json\n' + json.dumps([question(1)]) + '\n```'
        self.assertEqual(len(generate_quiz_questions('Source', '', 'beginner', 1)), 1)

    @patch('core.ai_features.chat_completion')
    def test_invalid_json_is_rejected_after_one_retry(self, completion):
        completion.return_value = 'not json'
        with self.assertRaises(AIProviderError):
            generate_quiz_questions('Source material', '', 'beginner', 1)
        self.assertEqual(completion.call_count, 2)

    @patch('core.ai_features.chat_completion')
    def test_retry_recovers_from_one_bad_response(self, completion):
        completion.side_effect = ['not json', json.dumps([question(1)])]
        self.assertEqual(len(generate_quiz_questions('Source', '', 'beginner', 1)), 1)

    @patch('core.ai_features.chat_completion')
    def test_wrong_question_count_is_rejected(self, completion):
        completion.return_value = '[]'
        with self.assertRaises(AIProviderError):
            generate_quiz_questions('Source material', '', 'beginner', 1)

    @patch('core.ai_features.chat_completion')
    def test_invalid_answer_index_is_rejected(self, completion):
        bad = question(1, answer=4)
        completion.return_value = json.dumps([bad])
        with self.assertRaises(AIProviderError):
            generate_quiz_questions('Source material', '', 'beginner', 1)

    @patch('core.ai_features.chat_completion')
    def test_duplicate_options_and_questions_are_rejected(self, completion):
        dup_options = question(1)
        dup_options['options'] = ['same', 'same', 'x', 'y']
        completion.return_value = json.dumps([dup_options])
        with self.assertRaises(AIProviderError):
            generate_quiz_questions('Source', '', 'beginner', 1)
        completion.return_value = json.dumps([question(1), question(1)])
        with self.assertRaises(AIProviderError):
            generate_quiz_questions('Source', '', 'beginner', 2)

    @patch('core.ai_features.chat_completion')
    def test_difficulty_and_topic_reach_the_prompt(self, completion):
        completion.return_value = json.dumps([question(1)])
        generate_quiz_questions('Source text here', 'recursion', 'advanced', 1)
        prompt = completion.call_args[0][0][1]['content']
        self.assertIn('Difficulty: advanced', prompt)
        self.assertIn('recursion', prompt)
        self.assertIn('Source text here', prompt)


class ChatCompletionProviderTests(SimpleTestCase):
    def test_missing_key_raises_configuration_error_without_network(self):
        with patch.dict(os.environ, {'AI_API_KEY': ''}), patch('urllib.request.urlopen') as urlopen:
            with self.assertRaises(AIProviderError) as ctx:
                chat_completion([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(ctx.exception.status_code, 503)
        urlopen.assert_not_called()

    def test_non_http_base_url_is_refused(self):
        with patch.dict(os.environ, {'AI_API_KEY': 'k', 'AI_BASE_URL': 'file:///etc'}), patch('urllib.request.urlopen') as urlopen:
            with self.assertRaises(AIProviderError):
                chat_completion([{'role': 'user', 'content': 'hi'}])
        urlopen.assert_not_called()

    def test_success_returns_message_content_and_sends_bearer_key(self):
        response = MagicMock()
        response.read.return_value = json.dumps({'choices': [{'message': {'content': ' hello '}}]}).encode()
        response.__enter__.return_value = response
        with patch.dict(os.environ, {'AI_API_KEY': 'sk-test', 'AI_BASE_URL': 'https://example.test/v1'}), \
                patch('urllib.request.urlopen', return_value=response) as urlopen:
            self.assertEqual(chat_completion([{'role': 'user', 'content': 'hi'}]), 'hello')
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://example.test/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer sk-test')

    def test_http_errors_map_to_safe_messages_without_leaking_the_key(self):
        for code, expected_status in ((401, 502), (429, 503), (500, 502)):
            error = urllib.error.HTTPError('https://x', code, 'err', {}, io.BytesIO(b'{"error": "sk-secret echoed"}'))
            with patch.dict(os.environ, {'AI_API_KEY': 'sk-secret'}), patch('urllib.request.urlopen', side_effect=error):
                with self.assertRaises(AIProviderError) as ctx:
                    chat_completion([{'role': 'user', 'content': 'hi'}])
            self.assertEqual(ctx.exception.status_code, expected_status)
            self.assertNotIn('sk-secret', str(ctx.exception))

    def test_network_failure_and_malformed_body_are_reported(self):
        with patch.dict(os.environ, {'AI_API_KEY': 'k'}), \
                patch('urllib.request.urlopen', side_effect=urllib.error.URLError('down')):
            with self.assertRaises(AIProviderError):
                chat_completion([{'role': 'user', 'content': 'hi'}])
        response = MagicMock()
        response.read.return_value = b'{"choices": []}'
        response.__enter__.return_value = response
        with patch.dict(os.environ, {'AI_API_KEY': 'k'}), patch('urllib.request.urlopen', return_value=response):
            with self.assertRaises(AIProviderError):
                chat_completion([{'role': 'user', 'content': 'hi'}])
