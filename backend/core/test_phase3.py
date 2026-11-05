from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Course, Payment, PayPalWebhookEvent, Enrollment, Refund
from .views import _payment_net_financials
from django.contrib.auth import get_user_model

User = get_user_model()

class Phase3FinancialManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username='phase3_admin', password='StrongPass123!', role='admin', is_approved=True)
        self.trainer = User.objects.create_user(username='phase3_trainer', password='StrongPass123!', role='trainer', is_approved=True)
        self.learner = User.objects.create_user(username='phase3_learner', password='StrongPass123!', role='trainee', is_approved=True)
        self.course = Course.objects.create(title='Phase 3 Course', description='Test', trainer=self.trainer, price=Decimal('100.00'), currency='USD')
        self.enrollment = Enrollment.objects.create(trainee=self.learner, course=self.course)
        self.payment = Payment.objects.create(learner=self.learner, course=self.course, paypal_order_id='PHASE3-ORDER',
            paypal_capture_id='PHASE3-CAPTURE', gross_amount=Decimal('100.00'), platform_fee=Decimal('1.00'),
            trainer_share=Decimal('99.00'), currency='USD', status='captured')

    @override_settings(PAYPAL_WEBHOOK_ID='sandbox-webhook-id')
    @patch('core.views._paypal_verify_webhook_signature')
    def test_webhook_rejects_invalid_signature(self, paypal_request):
        paypal_request.return_value = {'verification_status': 'FAILURE'}
        response = self.client.post('/api/payments/webhook/', {'id': 'EVT-INVALID', 'event_type': 'PAYMENT.CAPTURE.COMPLETED'}, format='json',
            HTTP_PAYPAL_AUTH_ALGO='SHA256withRSA', HTTP_PAYPAL_CERT_URL='https://api.paypal.com/cert',
            HTTP_PAYPAL_TRANSMISSION_ID='tx-1', HTTP_PAYPAL_TRANSMISSION_SIG='bad-signature',
            HTTP_PAYPAL_TRANSMISSION_TIME='2026-11-03T00:00:00Z')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PayPalWebhookEvent.objects.filter(event_id='EVT-INVALID').exists())

    @override_settings(PAYPAL_WEBHOOK_ID='sandbox-webhook-id')
    @patch('core.views._paypal_verify_webhook_signature')
    def test_verified_webhook_event_is_idempotent(self, paypal_request):
        paypal_request.return_value = {'verification_status': 'SUCCESS'}
        payload = {'id': 'EVT-UNKNOWN-001', 'event_type': 'CUSTOM.EVENT', 'resource': {'id': 'resource-1'}}
        headers = {'HTTP_PAYPAL_AUTH_ALGO': 'SHA256withRSA', 'HTTP_PAYPAL_CERT_URL': 'https://api.paypal.com/cert',
                   'HTTP_PAYPAL_TRANSMISSION_ID': 'tx-2', 'HTTP_PAYPAL_TRANSMISSION_SIG': 'valid-signature',
                   'HTTP_PAYPAL_TRANSMISSION_TIME': '2026-11-03T00:00:00Z'}
        first = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        second = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(PayPalWebhookEvent.objects.filter(event_id='EVT-UNKNOWN-001').count(), 1)

    def test_admin_financial_report_separates_currency_totals(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/admin/financial-report/')
        self.assertEqual(response.status_code, 200)
        usd = next(row for row in response.data['by_currency'] if row['currency'] == 'USD')
        self.assertEqual(Decimal(usd['gross_captured']), Decimal('100.00'))

    def test_non_admin_cannot_access_financial_report(self):
        self.client.force_authenticate(user=self.trainer)
        response = self.client.get('/api/admin/financial-report/')
        self.assertEqual(response.status_code, 403)

    @patch('core.views._paypal_verify_webhook_signature')
    def test_refund_rejects_amount_above_remaining_balance(self, paypal_request):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/admin/payments/{self.payment.id}/refund/', {'amount': '100.01'}, format='json')
        self.assertEqual(response.status_code, 400)
        paypal_request.assert_not_called()


    @override_settings(PAYPAL_WEBHOOK_ID='sandbox-webhook-id')
    @patch('core.views._paypal_verify_webhook_signature')
    def test_verified_partial_refund_webhook_updates_refund_total_once(self, paypal_request):
        paypal_request.return_value = {'verification_status': 'SUCCESS'}
        payload = {
            'id': 'EVT-REFUND-001',
            'event_type': 'PAYMENT.REFUND.COMPLETED',
            'resource': {
                'id': 'REFUND-001',
                'amount': {'value': '25.00', 'currency_code': 'USD'},
                'supplementary_data': {'related_ids': {'capture_id': 'PHASE3-CAPTURE'}},
            },
        }
        headers = {
            'HTTP_PAYPAL_AUTH_ALGO': 'SHA256withRSA',
            'HTTP_PAYPAL_CERT_URL': 'https://api.paypal.com/cert',
            'HTTP_PAYPAL_TRANSMISSION_ID': 'tx-refund-1',
            'HTTP_PAYPAL_TRANSMISSION_SIG': 'valid-signature',
            'HTTP_PAYPAL_TRANSMISSION_TIME': '2026-11-03T00:00:00Z',
        }
        first = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        second = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount, Decimal('25.00'))
        self.assertEqual(self.payment.status, 'captured')
        self.assertEqual(self.payment.refunds.count(), 1)
        self.assertFalse(Enrollment.objects.filter(trainee=self.learner, course=self.course).exists())
        net_amount, net_fee, net_share = _payment_net_financials(self.payment)
        self.assertEqual(net_amount, Decimal('75.00'))
        self.assertEqual(net_fee, Decimal('0.75'))
        self.assertEqual(net_share, Decimal('74.25'))


    @override_settings(PAYPAL_WEBHOOK_ID='sandbox-webhook-id')
    @patch('core.views._paypal_verify_webhook_signature')
    def test_capture_refunded_webhook_marks_payment_refunded_once(self, verify_signature):
        verify_signature.return_value = {'verification_status': 'SUCCESS'}
        payload = {
            'id': 'EVT-CAPTURE-REFUNDED-001',
            'event_type': 'PAYMENT.CAPTURE.REFUNDED',
            'resource': {
                'id': 'PHASE3-CAPTURE',
                'status': 'REFUNDED',
                'amount': {'value': '100.00', 'currency_code': 'USD'},
            },
        }
        headers = {
            'HTTP_PAYPAL_AUTH_ALGO': 'SHA256withRSA',
            'HTTP_PAYPAL_CERT_URL': 'https://api.paypal.com/cert',
            'HTTP_PAYPAL_TRANSMISSION_ID': 'tx-capture-refunded-1',
            'HTTP_PAYPAL_TRANSMISSION_SIG': 'valid-signature',
            'HTTP_PAYPAL_TRANSMISSION_TIME': '2026-11-03T00:00:00Z',
        }
        first = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        second = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount, Decimal('100.00'))
        self.assertEqual(self.payment.status, 'refunded')
        self.assertEqual(self.payment.refunds.count(), 1)
        self.assertFalse(Enrollment.objects.filter(trainee=self.learner, course=self.course).exists())

    @override_settings(PAYPAL_WEBHOOK_ID='sandbox-webhook-id')
    @patch('core.views._paypal_verify_webhook_signature')
    def test_partial_capture_refund_event_is_not_guessed(self, verify_signature):
        verify_signature.return_value = {'verification_status': 'SUCCESS'}
        payload = {
            'id': 'EVT-CAPTURE-PARTIAL-001',
            'event_type': 'PAYMENT.CAPTURE.REFUNDED',
            'resource': {
                'id': 'PHASE3-CAPTURE',
                'status': 'PARTIALLY_REFUNDED',
                'amount': {'value': '100.00', 'currency_code': 'USD'},
            },
        }
        headers = {
            'HTTP_PAYPAL_AUTH_ALGO': 'SHA256withRSA',
            'HTTP_PAYPAL_CERT_URL': 'https://api.paypal.com/cert',
            'HTTP_PAYPAL_TRANSMISSION_ID': 'tx-capture-partial-1',
            'HTTP_PAYPAL_TRANSMISSION_SIG': 'valid-signature',
            'HTTP_PAYPAL_TRANSMISSION_TIME': '2026-11-03T00:00:00Z',
        }
        response = self.client.post('/api/payments/webhook/', payload, format='json', **headers)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data['reconciliation_required'])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount, Decimal('0.00'))
        self.assertEqual(self.payment.status, 'captured')
        self.assertFalse(Enrollment.objects.filter(trainee=self.learner, course=self.course).exists())
        event = PayPalWebhookEvent.objects.get(event_id='EVT-CAPTURE-PARTIAL-001')
        self.assertEqual(event.status, 'reconciliation_required')

    @patch('core.views._paypal_request')
    def test_admin_partial_refund_revokes_access_and_records_amount(self, paypal_request):
        self.client.force_authenticate(user=self.admin)
        paypal_request.return_value = {
            'id': 'PHASE3-REFUND-25',
            'status': 'COMPLETED',
            'amount': {'value': '25.00', 'currency_code': 'USD'},
        }
        response = self.client.post(
            f'/api/admin/payments/{self.payment.id}/refund/',
            {'amount': '25.00', 'reason': 'Partial refund test'}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount, Decimal('25.00'))
        self.assertEqual(self.payment.status, 'captured')
        self.assertFalse(Enrollment.objects.filter(trainee=self.learner, course=self.course).exists())
        self.assertEqual(Refund.objects.get(paypal_refund_id='PHASE3-REFUND-25').amount, Decimal('25.00'))

    def test_student_transaction_dashboard_includes_refund_amount(self):
        self.payment.refunded_amount = Decimal('25.00')
        self.payment.save(update_fields=['refunded_amount'])
        Enrollment.objects.filter(trainee=self.learner, course=self.course).delete()
        Refund.objects.create(payment=self.payment, paypal_refund_id='PHASE3-DASH-REFUND',
                              amount=Decimal('25.00'), currency='USD', status='completed')
        self.client.force_authenticate(user=self.learner)
        response = self.client.get('/api/transactions/')
        self.assertEqual(response.status_code, 200)
        purchase = next(row for row in response.data['items'] if row['payment_id'] == self.payment.id)
        self.assertEqual(purchase['refunded_amount'], '25.00')
        self.assertEqual(len(purchase['refunds']), 1)
        self.assertFalse(purchase['enrollment_active'])

    def test_partially_refunded_payment_cannot_restore_course_access(self):
        self.payment.refunded_amount = Decimal('25.00')
        self.payment.save(update_fields=['refunded_amount'])
        Enrollment.objects.filter(trainee=self.learner, course=self.course).delete()
        self.client.force_authenticate(user=self.learner)
        response = self.client.post(f'/api/courses/{self.course.id}/rejoin/')
        self.assertEqual(response.status_code, 402)
        self.assertFalse(Enrollment.objects.filter(trainee=self.learner, course=self.course).exists())
