# Capacity Connect — Final integration and deployment guide

This guide covers the production-oriented Docker Compose setup added in the final implementation phase. It does not certify the application for production or replace a security review.

## 1. Required infrastructure

- A Linux host with Docker Engine and the Docker Compose plugin.
- A domain name and a trusted HTTPS reverse proxy/load balancer in front of the Compose frontend service.
- A PostgreSQL volume with a tested backup and restore process.
- PayPal REST app credentials and a webhook registered against the **public HTTPS** endpoint.

The Compose frontend listens on host port `APP_PORT` (default `8080`). The frontend container serves the React production build and proxies `/api/`, `/admin/`, and `/healthz/` to Django. Django is run by Gunicorn. Uploaded media and collected Django static files use persistent Docker volumes.

## 2. Configure secrets and origins

Copy `.env.example` to `.env` in the repository root. Replace every placeholder. At minimum configure:

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_ALLOWED_HOSTS=your-domain.example,backend,localhost
POSTGRES_DB=capacity_connect
POSTGRES_USER=capacity_user
POSTGRES_PASSWORD=<long-random-database-password>
APP_PORT=8080
CORS_ALLOWED_ORIGINS=https://your-domain.example
CSRF_TRUSTED_ORIGINS=https://your-domain.example
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_HSTS_SECONDS=31536000
DJANGO_HSTS_PRELOAD=False
PAYPAL_CLIENT_ID=<live-client-id>
PAYPAL_CLIENT_SECRET=<live-client-secret>
PAYPAL_BASE_URL=https://api-m.paypal.com
PAYPAL_WEBHOOK_ID=<live-webhook-id>
PLATFORM_FEE_PERCENT=1
FRONTEND_URL=https://your-domain.example
```

Generate `DJANGO_SECRET_KEY` with `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Use a URL-safe PostgreSQL password (or URL-encode special characters in the database URL). Set `DJANGO_HSTS_PRELOAD=True` only after confirming that the apex domain and every relevant subdomain support HTTPS continuously; leaving it false is the safer default. Use Sandbox credentials and `https://api-m.sandbox.paypal.com` while testing. Never put PayPal secrets in `frontend/.env`, React source, Git, screenshots, or client-side environment variables. The root `.env` is passed to the backend container and is excluded from Docker build contexts by `.dockerignore`.

The frontend build uses a same-origin `/api` base URL, so browser requests pass through Nginx and CORS is normally not involved for the app itself. Keep exact production origins configured anyway for any direct API integrations.

## 3. HTTPS reverse proxy requirement

Terminate TLS at a trusted reverse proxy/load balancer. Forward the original host and set `X-Forwarded-Proto: https` on HTTPS requests. The frontend Nginx config passes this header to Django, and Django trusts it via `SECURE_PROXY_SSL_HEADER`. Do not expose the backend container directly to the public Internet. Do not enable HSTS until HTTPS works correctly for the entire domain and all relevant subdomains.

## 4. Start the deployment

```bash
docker compose config
docker compose up --build -d
docker compose ps
```

The backend container applies migrations and collects static files before starting Gunicorn. The frontend starts after the backend health check succeeds. Verify `https://your-domain.example/healthz/` through the public reverse proxy and confirm that it returns HTTP 200. Django's direct readiness endpoint is `/healthz/`; it checks database connectivity.

Create the first admin account:

```bash
docker compose exec backend python manage.py createsuperuser
```

Useful operational commands:

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose exec backend python manage.py check --deploy
docker compose exec backend python manage.py showmigrations
```

Do not run `docker compose down -v` on a live deployment; it deletes named database and media volumes.

## 5. PayPal configuration

Register the exact public webhook URL in the corresponding PayPal app:

`https://your-domain.example/api/payments/webhook/`

Subscribe to the capture, refund, and dispute event types implemented by the backend. Store the webhook ID returned by the same Sandbox/Live app in `PAYPAL_WEBHOOK_ID`. Sandbox webhook IDs and credentials are not interchangeable with Live. Payouts API access must be enabled for the merchant account before trainer transfers can be sent.

## 6. Final end-to-end verification checklist

Use separate Sandbox buyer, merchant, and trainer accounts where applicable. Do not test with real money until the Sandbox flow, reconciliation, and rollback/recovery procedures have been reviewed.

1. Register/login as a learner and purchase a paid course.
2. Confirm PayPal order creation, approval, capture, payment history, and course enrollment.
3. Repeat capture/webhook delivery and confirm no duplicate enrollment or financial entry.
4. Test a full refund and a partial refund; verify remaining course access and net fee/trainer-share calculations.
5. Deliver a verified webhook, then replay the same event; confirm idempotent processing. Test invalid signature rejection.
6. Create trainer earnings, submit a withdrawal, approve it as admin, and send a Sandbox payout.
7. Verify payout status synchronization for success, pending, denied/failed, and an ambiguous network timeout. Confirm reserved balances are not released while the outcome is unknown.
8. Check trainer/admin permissions by attempting each protected operation with the wrong role.
9. Compare the financial report and reconciliation output with the corresponding PayPal Sandbox transactions.
10. Restart containers and verify that database records, uploads, static assets, and payout history persist.

## 7. Known limitations / human verification

- Automated Django tests use mocked PayPal API responses; they do not prove that PayPal will accept a live transaction or payout.
- A `PAYMENT.CAPTURE.REFUNDED` event marked `PARTIALLY_REFUNDED` currently requires refund-level details/reconciliation; the handler deliberately does not guess an amount. Review and reconcile such events before considering the books final.
- The payout retry strategy relies on reusing a stable `sender_batch_id`. An ambiguous response must remain reserved until the original PayPal batch can be identified and synchronized.
- Browser-based tests, actual external HTTPS termination, PayPal webhook delivery, PayPal Payouts entitlement, email delivery, malware scanning, and backup restoration must be tested in the deployment environment.
- This baseline serves uploaded media from a shared Docker volume. For a horizontally scaled or high-volume service, migrate media to managed object storage/CDN and review upload scanning and access controls.

## 8. Rollback and backup

Before deployment or migration, take a database backup and verify that it can be restored. Keep the previous application image/tag available for rollback. Database schema changes are not automatically reversed by rolling back application code; review migration compatibility before each release.
