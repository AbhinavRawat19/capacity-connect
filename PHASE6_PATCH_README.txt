CAPACITY CONNECT — PHASE 6 FINAL INTEGRATION PATCH

Copy the files from this ZIP into the matching paths in your project, overwriting only the listed files:

backend/config/settings.py
backend/config/urls.py
backend/requirements.txt
backend/Dockerfile
backend/core/views.py
backend/core/urls.py
backend/core/test_phase3.py
backend/core/test_phase6.py                 (new)
frontend/Dockerfile
frontend/nginx.conf                         (new)
docker-compose.yml
.dockerignore                               (new)
backend/.dockerignore                       (new)
frontend/.dockerignore                      (new)
.env.example
README.md
DEPLOYMENT.md                               (new)

Do NOT overwrite your actual .env file, database, media folder, .git folder, or node_modules.
No model changes or migrations are included.

After copying, install the updated backend requirements in your existing virtual environment:
  pip install -r backend/requirements.txt

The production Docker Compose setup expects a root .env configured from .env.example. Review DEPLOYMENT.md before running it. HTTPS must be terminated by a trusted external reverse proxy/load balancer; do not expose the backend container directly.

The backend test suite was run against the patched source: 139 tests passed. Django system check passed and makemigrations --check --dry-run reported no model changes. The frontend build could not be completed in this environment because the uploaded node_modules has a missing Linux-native Rolldown binding and npm ci timed out. Docker's clean Linux build uses npm ci from package-lock.json, but that container build has not been executed here. Live PayPal Sandbox/Live transfers and actual webhook delivery remain unverified.
