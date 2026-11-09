# Capacity Connect - pre-release status

This file replaces the earlier integration report. Every statement below was checked against the code in this archive.

## Changes in this pre-release
- AG Grid: the admin "User management" table (Admin page) is now `frontend/src/AdminUsersGrid.jsx` (ag-grid-community / ag-grid-react 34.3.1, themed to the app's slate/lime palette). Same `/admin/users/` data, same Approve and Change role actions; adds column sorting, per-column filters, quick search and pagination. No other screen uses AG Grid.
- `frontend/package.json` declares AG Grid. **`frontend/package-lock.json` has NOT been regenerated** (no registry access when this was built). Run `npm install` in `frontend/` and commit the lockfile before using `npm ci` or Docker.
- Stale PayPal test corrected (`test_phase3.py::test_capture_refunded_webhook_defers_to_refund_level_event`). The webhook (HTTP 202 `reconciliation_required` for a capture-level REFUNDED event, exact amount applied by the later PAYMENT.REFUND.COMPLETED event) is intentional and is also asserted by two other tests; the old test expected a 200 and a refund synthesized from the capture event, which would double-count money. Webhook code unchanged.
- Authorization fix: a trainer could PATCH an assessment's `course` to another trainer's course. Now 403 (regression test added in `test_ai_api.py`).
- Pydantic errors: this archive contains no virtual environment or compiled extensions; `pydantic` is declared in `backend/requirements.txt`. The earlier errors came from a Windows venv bundled in a previous upload. Install in a fresh venv.
- Removed dead files: `views_current_backup.py`, `views_original_from_git.py`, `learning_intelligence_backup.py`, `App.jsx.backup` (not imported anywhere), and an empty stray `backend/package-lock.json`. Fixed a stray code fence at the end of `.gitignore`.

## Verification status
See the final report delivered with this archive. Not executed in the build environment (no network, Django/Vite/AG Grid not installable): Django checks, migrations check, the Django test suite, `npm install`, `vite build`, runtime check of the grid.

## Final verification steps
```
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test core -v 2
cd ../frontend && npm install && npm run build
```
Then log in as an admin, open Admin > User management and confirm: sorting, filtering, search, pagination, Approve and Change role. Commit the regenerated `frontend/package-lock.json`.
