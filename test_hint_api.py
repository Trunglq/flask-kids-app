import unittest
from unittest.mock import patch, MagicMock
from app import app, call_xai_api
import re

class TestHintAPI(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self.default_question = "Tính: 5 + 3"
        self.default_grade = "3"
        self.default_subject = "math"

    @patch('app.call_xai_api')
    def test_first_hint_returns_one(self, mock_call_xai_api):
        # Mock API to return 5 hints
        mock_call_xai_api.return_value = [
            "Hint 1", "Hint 2", "Hint 3", "Hint 4", "Hint 5"
        ]
        # Simulate POST with action=ask
        response = self.app.post('/kids', data={
            'action': 'ask',
            'question': self.default_question,
            'grade': self.default_grade,
            'subject': self.default_subject
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # Only first hint should be shown
        self.assertIn("Hint 1", html)
        self.assertNotIn("Hint 2", html)

    @patch('app.call_xai_api')
    def test_explain_more_returns_next_hint(self, mock_call_xai_api):
        # Mock API to return 5 hints
        mock_call_xai_api.return_value = [
            "Hint 1", "Hint 2", "Hint 3", "Hint 4", "Hint 5"
        ]
        with self.app as client:
            # First, ask the question
            client.post('/kids', data={
                'action': 'ask',
                'question': self.default_question,
                'grade': self.default_grade,
                'subject': self.default_subject
            }, follow_redirects=True)
            # Then, simulate pressing "Gợi ý thêm" (explain_more)
            response = client.post('/kids', data={
                'action': 'explain_more',
                'question': self.default_question,
                'grade': self.default_grade,
                'subject': self.default_subject
            }, follow_redirects=True)
            html = response.get_data(as_text=True)
            expected_hint = "Hint 2"
            expected_prefix = "Gợi ý 2: Hint 2"
            self.assertTrue((expected_hint in html) or (expected_prefix in html),
                            f"Neither '{expected_hint}' nor '{expected_prefix}' found in HTML! Actual HTML: {html}")

    @patch('app.call_xai_api')
    def test_hint_sequence(self, mock_call_xai_api):
        # Mock API to return 5 hints
        mock_call_xai_api.return_value = [
            "Hint 1", "Hint 2", "Hint 3", "Hint 4", "Hint 5"
        ]
        with self.app as client:
            # Ask and then repeatedly press "Gợi ý thêm"
            client.post('/kids', data={
                'action': 'ask',
                'question': self.default_question,
                'grade': self.default_grade,
                'subject': self.default_subject
            }, follow_redirects=True)
            for i in range(5):
                response = client.post('/kids', data={
                    'action': 'explain_more',
                    'question': self.default_question,
                    'grade': self.default_grade,
                    'subject': self.default_subject
                }, follow_redirects=True)
                html = response.get_data(as_text=True)
                expected_hint = f"Hint {min(i+2,5)}"
                expected_prefix = f"Gợi ý {min(i+2,5)}: {expected_hint}"
                pattern = re.compile(rf"Gợi ý\\s*{min(i+2,5)}:?\\s*{re.escape(expected_hint)}", re.UNICODE)
                self.assertTrue(pattern.search(html) or expected_hint in html,
                                f"Neither '{expected_hint}' nor pattern '{pattern.pattern}' found in HTML! Actual HTML: {html}")

if __name__ == '__main__':
    unittest.main()
