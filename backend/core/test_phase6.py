from unittest.mock import patch

from django.test import TestCase
from django.urls import resolve


class FinalIntegrationSmokeTests(TestCase):
    def test_readiness_endpoint_checks_database_and_returns_ok(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'database': 'ok'})

    @patch('config.urls.connection.cursor', side_effect=RuntimeError('database unavailable'))
    def test_readiness_endpoint_returns_503_when_database_is_unavailable(self, _mock_cursor):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'unhealthy')

    def test_payment_and_trainer_payout_routes_are_registered(self):
        expected = {
            '/api/payments/create-order/': 'paypal_create_order',
            '/api/payments/capture-order/': 'paypal_capture_order',
            '/api/payments/webhook/': 'paypal_webhook',
            '/api/trainer/payouts/': 'trainer_payouts',
            '/api/admin/trainer-payouts/': 'admin_trainer_payouts',
            '/api/admin/webhook-reconciliation-events/': 'admin_webhook_reconciliation_events',
        }
        for route, view_name in expected.items():
            with self.subTest(route=route):
                match = resolve(route)
                self.assertTrue(callable(match.func))
