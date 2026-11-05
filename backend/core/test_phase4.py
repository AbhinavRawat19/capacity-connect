from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from .models import User, Course, Payment, Payout, Refund


class TrainerPayoutWorkflowTests(TestCase):
    def setUp(self):
        self.trainer = User.objects.create_user(
            username='trainer_phase4', password='pass12345', role='trainer',
            is_approved=True, paypal_email='trainer@example.com'
        )
        self.admin = User.objects.create_user(
            username='admin_phase4', password='pass12345', role='admin', is_approved=True
        )
        self.course = Course.objects.create(
            title='Paid course', description='Course for payout tests', trainer=self.trainer,
            price=Decimal('100.00'), currency='USD', is_published=True
        )
        self.payment = Payment.objects.create(
            learner=User.objects.create_user(username='learner_phase4', password='pass12345', is_approved=True),
            course=self.course, paypal_order_id='ORDER-PHASE4-1', paypal_capture_id='CAPTURE-PHASE4-1',
            gross_amount=Decimal('100.00'), platform_fee=Decimal('1.00'), trainer_share=Decimal('99.00'),
            currency='USD', status='captured'
        )
        self.client = APIClient()

    def test_trainer_sees_available_earnings_and_requests_payout(self):
        self.client.force_authenticate(self.trainer)
        response = self.client.get('/api/trainer/payouts/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['balances'][0]['available'], '99.00')
        response = self.client.post('/api/trainer/payouts/', {'amount': '50.00', 'currency': 'USD'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Payout.objects.get().status, 'pending')

    def test_trainer_cannot_request_more_than_available_balance(self):
        self.client.force_authenticate(self.trainer)
        response = self.client.post('/api/trainer/payouts/', {'amount': '100.00', 'currency': 'USD'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Payout.objects.exists())

    def test_pending_request_reserves_balance(self):
        Payout.objects.create(trainer=self.trainer, amount=Decimal('60.00'), currency='USD')
        self.client.force_authenticate(self.trainer)
        response = self.client.get('/api/trainer/payouts/')
        self.assertEqual(response.data['balances'][0]['available'], '39.00')

    def test_admin_can_approve_and_reject_pending_requests(self):
        payout = Payout.objects.create(trainer=self.trainer, amount=Decimal('25.00'), currency='USD')
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/admin/trainer-payouts/', {'payout_id': payout.id, 'action': 'approve'}, format='json')
        self.assertEqual(response.status_code, 200)
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'approved')

        second = Payout.objects.create(trainer=self.trainer, amount=Decimal('10.00'), currency='USD')
        response = self.client.post('/api/admin/trainer-payouts/', {'payout_id': second.id, 'action': 'reject', 'reason': 'Verification required'}, format='json')
        self.assertEqual(response.status_code, 200)
        second.refresh_from_db()
        self.assertEqual(second.status, 'rejected')

    @patch('core.views._paypal_request')
    def test_admin_processes_approved_payout_once_with_stable_batch_id(self, paypal_request):
        payout = Payout.objects.create(trainer=self.trainer, amount=Decimal('25.00'), currency='USD', status='approved')
        paypal_request.return_value = {'batch_header': {'payout_batch_id': 'PAYPAL-BATCH-1', 'batch_status': 'PENDING'}}
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/admin/trainer-payouts/', {'payout_id': payout.id, 'action': 'process'}, format='json')
        self.assertEqual(response.status_code, 202)
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'processing')
        self.assertEqual(payout.paypal_batch_id, 'PAYPAL-BATCH-1')
        self.assertTrue(payout.sender_batch_id)
        self.assertEqual(paypal_request.call_args.kwargs['request_id'], payout.sender_batch_id)

    def test_trainee_cannot_access_trainer_payouts(self):
        learner = User.objects.get(username='learner_phase4')
        self.client.force_authenticate(learner)
        response = self.client.get('/api/trainer/payouts/')
        self.assertEqual(response.status_code, 403)


    def test_partial_refund_recalculates_trainer_share_after_platform_fee(self):
        self.payment.refunded_amount = Decimal('25.00')
        self.payment.save(update_fields=['refunded_amount'])
        Refund.objects.create(
            payment=self.payment, paypal_refund_id='PHASE4-PARTIAL-25',
            amount=Decimal('25.00'), currency='USD', status='completed'
        )
        self.client.force_authenticate(self.trainer)
        response = self.client.get('/api/trainer/payouts/')
        self.assertEqual(response.status_code, 200)
        balance = response.data['balances'][0]
        # $100 gross - $25 refund = $75 net; 1% fee = $0.75; trainer gets $74.25.
        self.assertEqual(balance['gross_sales'], '100.00')
        self.assertEqual(balance['refunded'], '25.00')
        self.assertEqual(balance['net_sales'], '75.00')
        self.assertEqual(balance['platform_fee'], '0.75')
        self.assertEqual(balance['earned'], '74.25')
        self.assertEqual(balance['available'], '74.25')

    def test_trainer_ledger_keeps_refunded_purchase_and_shows_net_share(self):
        self.payment.refunded_amount = Decimal('25.00')
        self.payment.save(update_fields=['refunded_amount'])
        Refund.objects.create(
            payment=self.payment, paypal_refund_id='PHASE4-LEDGER-25',
            amount=Decimal('25.00'), currency='USD', status='completed'
        )
        self.client.force_authenticate(self.trainer)
        response = self.client.get('/api/transactions/')
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data['items'] if item['payment_id'] == self.payment.id)
        self.assertEqual(row['refunded_amount'], '25.00')
        self.assertEqual(row['platform_fee'], '0.75')
        self.assertEqual(row['trainer_share'], '74.25')
        self.assertFalse(row['enrollment_active'])

    def test_completed_payout_after_refund_creates_visible_adjustment_due(self):
        self.payment.refunded_amount = Decimal('25.00')
        self.payment.save(update_fields=['refunded_amount'])
        Payout.objects.create(
            trainer=self.trainer, amount=Decimal('99.00'), currency='USD', status='completed'
        )
        self.client.force_authenticate(self.trainer)
        response = self.client.get('/api/trainer/payouts/')
        balance = response.data['balances'][0]
        self.assertEqual(balance['earned'], '74.25')
        self.assertEqual(balance['paid'], '99.00')
        self.assertEqual(balance['available'], '0.00')
        self.assertEqual(balance['adjustment_due'], '24.75')

    @patch('core.views._paypal_request')
    def test_approved_payout_is_not_sent_if_refund_reduced_entitlement(self, paypal_request):
        self.payment.refunded_amount = Decimal('25.00')
        self.payment.save(update_fields=['refunded_amount'])
        payout = Payout.objects.create(
            trainer=self.trainer, amount=Decimal('99.00'), currency='USD', status='approved'
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            '/api/admin/trainer-payouts/',
            {'payout_id': payout.id, 'action': 'process'}, format='json'
        )
        self.assertEqual(response.status_code, 409)
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'failed')
        self.assertIn('refunds reduced', payout.failure_reason)
        paypal_request.assert_not_called()
