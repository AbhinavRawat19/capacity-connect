from decimal import Decimal
from unittest.mock import patch
from urllib.error import HTTPError
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User, Payout, Course, Payment


class Phase5PayoutRecoveryTests(TestCase):
    def setUp(self):
        self.trainer = User.objects.create_user(
            username='phase5_trainer', password='pass12345', role='trainer',
            is_approved=True, paypal_email='phase5@example.com'
        )
        self.admin = User.objects.create_user(
            username='phase5_admin', password='pass12345', role='admin', is_approved=True
        )
        self.course = Course.objects.create(
            title='Phase 5 payout course', description='Payout recovery fixture',
            trainer=self.trainer, price=Decimal('100.00'), currency='USD', is_published=True
        )
        self.learner = User.objects.create_user(
            username='phase5_learner', password='pass12345', is_approved=True
        )
        Payment.objects.create(
            learner=self.learner, course=self.course, paypal_order_id='PHASE5-ORDER',
            paypal_capture_id='PHASE5-CAPTURE', gross_amount=Decimal('100.00'),
            platform_fee=Decimal('1.00'), trainer_share=Decimal('99.00'),
            currency='USD', status='captured'
        )
        self.payout = Payout.objects.create(
            trainer=self.trainer, amount=Decimal('25.00'), currency='USD', status='approved'
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    @patch('core.views._paypal_request')
    def test_ambiguous_timeout_can_be_retried_with_same_idempotency_key(self, paypal_request):
        paypal_request.side_effect = TimeoutError('simulated network timeout')
        first = self.client.post(
            '/api/admin/trainer-payouts/',
            {'payout_id': self.payout.id, 'action': 'process'}, format='json'
        )
        self.assertEqual(first.status_code, 502)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, 'processing')
        self.assertFalse(self.payout.paypal_batch_id)
        stable_id = self.payout.sender_batch_id
        self.assertTrue(stable_id)

        paypal_request.side_effect = None
        paypal_request.return_value = {
            'batch_header': {'payout_batch_id': 'BATCH-RECOVERED-5', 'batch_status': 'PENDING'}
        }
        second = self.client.post(
            '/api/admin/trainer-payouts/',
            {'payout_id': self.payout.id, 'action': 'process'}, format='json'
        )
        self.assertEqual(second.status_code, 202)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.sender_batch_id, stable_id)
        self.assertEqual(self.payout.paypal_batch_id, 'BATCH-RECOVERED-5')
        self.assertEqual(paypal_request.call_args.kwargs['request_id'], stable_id)

    @patch('core.views._paypal_request')
    def test_paypal_conflict_keeps_payout_reserved_for_recovery(self, paypal_request):
        error = HTTPError('https://api-m.sandbox.paypal.com/v1/payments/payouts', 409,
                          'Conflict', {}, None)
        error.read = lambda: b'duplicate sender batch id'
        paypal_request.side_effect = error
        response = self.client.post(
            '/api/admin/trainer-payouts/',
            {'payout_id': self.payout.id, 'action': 'process'}, format='json'
        )
        self.assertEqual(response.status_code, 502)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, 'processing')
        self.assertTrue(self.payout.sender_batch_id)
        self.assertFalse(self.payout.paypal_batch_id)


    @patch('core.views._paypal_request')
    def test_duplicate_sender_batch_conflict_recovers_original_batch_id(self, paypal_request):
        error = HTTPError('https://api-m.sandbox.paypal.com/v1/payments/payouts', 409,
                          'Conflict', {}, None)
        error.read = lambda: (
            b'{"name":"DUPLICATE_BATCH_ID","links":[{"rel":"self",'
            b'"href":"https://api-m.sandbox.paypal.com/v1/payments/payouts/ORIGINAL-BATCH-5"}]}'
        )
        paypal_request.side_effect = error
        response = self.client.post(
            '/api/admin/trainer-payouts/',
            {'payout_id': self.payout.id, 'action': 'process'}, format='json'
        )
        self.assertEqual(response.status_code, 502)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, 'processing')
        self.assertEqual(self.payout.paypal_batch_id, 'ORIGINAL-BATCH-5')

    def test_processing_payout_with_known_batch_cannot_be_submitted_again(self):
        self.payout.status = 'processing'
        self.payout.sender_batch_id = 'CCPAYOUT0000000001'
        self.payout.paypal_batch_id = 'BATCH-ALREADY-SUBMITTED'
        self.payout.save()
        response = self.client.post(
            '/api/admin/trainer-payouts/',
            {'payout_id': self.payout.id, 'action': 'process'}, format='json'
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn('Synchronize', response.data['detail'])

