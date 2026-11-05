# Capacity Connect deployment fixes

Replace/add these files in the existing project:

- Replace `frontend/Dockerfile`
- Add/replace `frontend/nginx.conf`
- Add/replace `frontend/.dockerignore`
- Replace `frontend/package.json`
- Replace `frontend/package-lock.json`

The frontend image is now a multi-stage production build: Vite compiles the app, and Nginx serves `dist/` on port 80. Nginx proxies `/api/`, `/admin/`, and `/healthz/` to the Compose `backend` service and serves the persistent `/static/` and `/media/` volumes.

`VITE_API_BASE_URL` is injected at build time and defaults to `/api`, matching the same-origin Nginx proxy.

The dependency versions are pinned to the exact versions already present in the uploaded lockfile; this avoids floating `latest` versions without silently upgrading the app's dependency graph.

Do not replace `.env`, the database, uploads, or `.git` with anything from this patch. This patch does not include those files.

## Build note

The Dockerfile runs `npm ci`, so the lockfile is authoritative. The image build itself still needs to be run in an environment with Docker and access to the npm image/package registries.
