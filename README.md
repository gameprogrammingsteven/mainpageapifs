# Main Page API

FastAPI starter. Intended to be pulled into `/app/svr`.

## Run

    python -m venv .venv
    . .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn app.main:app --host 0.0.0.0 --port 8000

## Configuration

Copy `.env.example` to `.env` on the server (it's gitignored) and fill in `MONGODB_URI`
(e.g. `mongodb://USER:PASSWORD@127.0.0.1:27017/DBNAME?authSource=admin`). URL-encode special characters in the password.
Real environment variables also work and take precedence.

## Next.js

Set `CORS_ORIGINS` (comma-separated, default `http://localhost:3000`) to the Next.js origin(s).
Alternatively, proxy via a Next.js rewrite (`/toolsapi/v1/:path*` -> `http://127.0.0.1:8000/toolsapi/v1/:path*`) and CORS isn't needed.

## Routes

- `/toolsapi/v1/pad`, `/toolsapi/v1/pad/{id}`, `/toolsapi/v1/files`, `/toolsapi/v1/files/{id}` (pads + temp uploads)
  - Files are stored under `TOOLS_DATA_DIR` (default: `data/` next to `app/`); point it at a writable path on the server.
  - Run a single uvicorn worker (limit checks use an in-process lock).
  - The reverse proxy must set `X-Real-IP $remote_addr` and `client_max_body_size 6m`.

- `GET/POST /toolsapi/v1/todo`
- `GET/PUT/DELETE /toolsapi/v1/todo/{id}`
- `GET /toolsapi/v1/health`
- Docs: `/toolsapi/v1/docs` (also `/redoc`, `/openapi.json` under the same prefix)

Todo routes are rate-limited per client IP (HTTP 429 with `Retry-After`). Tune with env vars
`RATE_LIMIT_READ` (default 120), `RATE_LIMIT_WRITE` (default 20) and `RATE_LIMIT_WINDOW` (seconds, default 60).
It relies on the proxy setting `X-Real-IP` and on a single uvicorn worker.

All routes live under `/toolsapi/v1`. Add new route groups as modules in `app/routers/` and register them on the `api` router in `app/main.py`.
