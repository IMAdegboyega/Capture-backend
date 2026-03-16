# Capture API

REST API backend for the Capture screen recording and video sharing platform. Handles Google OAuth authentication, JWT token management, video metadata persistence, and signed Cloudinary upload flows.

## Tech Stack

- **FastAPI** — async Python web framework
- **SQLAlchemy 2.0 (async)** — ORM with `asyncpg` driver for PostgreSQL
- **PostgreSQL** — hosted on Supabase, accessed via the Transaction pooler
- **Cloudinary SDK** — video/thumbnail storage, processing status, transcript retrieval
- **JWT (python-jose)** — stateless access + refresh token auth
- **slowapi** — rate limiting on mutation endpoints
- **Pydantic v2** — request/response validation with field-level constraints

## Architecture

- **Service layer**: `CloudinaryService` wraps all Cloudinary SDK calls with `asyncio.to_thread()` for non-blocking execution. Auth logic (token creation, Google OAuth exchange, user upsert) lives in `app/services/auth.py`.
- **Async DB**: `AsyncSession` via `asyncpg` with `statement_cache_size=0` required for Supabase Transaction pooler compatibility.
- **Signed upload flow**: The frontend requests signed upload parameters from `/api/videos/upload-url`, uploads directly to Cloudinary client-side, then POSTs metadata to `/api/videos`. The backend never handles the video file itself.
- **Security**: `SecurityHeadersMiddleware` sets `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, and related headers on every response.

## Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment — copy and fill in values
cp .env.example .env
```

### Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
SECRET_KEY=your_secret_key
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:3000/api/auth/callback/google
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
ALLOWED_ORIGINS=http://localhost:3000
```

### Run Migrations & Start Server

```bash
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## API Endpoints

### Auth
| Method | Endpoint             | Description                       | Auth |
|--------|----------------------|-----------------------------------|------|
| POST   | `/api/auth/google`   | Exchange Google auth code for JWT | No   |
| POST   | `/api/auth/refresh`  | Refresh access token              | No   |
| GET    | `/api/auth/me`       | Get current user profile          | Yes  |

### Videos
| Method | Endpoint                            | Description                          | Auth     |
|--------|-------------------------------------|--------------------------------------|----------|
| GET    | `/api/videos`                       | List/search videos (paginated)       | Optional |
| POST   | `/api/videos`                       | Save video metadata after upload     | Yes      |
| GET    | `/api/videos/{video_id}`            | Get single video with user info      | No       |
| DELETE | `/api/videos/{video_id}`            | Delete video (Cloudinary + DB)       | Yes      |
| PATCH  | `/api/videos/{video_id}/views`      | Increment view count                 | No       |
| PATCH  | `/api/videos/{video_id}/visibility` | Toggle public/private                | Yes      |
| GET    | `/api/videos/{video_id}/transcript` | Get AI-generated transcript          | No       |
| GET    | `/api/videos/{video_id}/status`     | Check Cloudinary encoding progress   | Yes      |
| POST   | `/api/videos/upload-url`            | Get signed Cloudinary upload params  | Yes      |
| POST   | `/api/videos/thumbnail-url`         | Get signed thumbnail upload params   | Yes      |
| GET    | `/api/videos/user/{user_id}`        | Get all videos for a user            | Optional |

### Utility
| Method | Endpoint      | Description  |
|--------|---------------|--------------|
| GET    | `/api/health` | Health check |

## Testing

```bash
pytest
```

Tests use `httpx.AsyncClient` with `ASGITransport` — no running server required. The test suite covers auth endpoints, video CRUD authorization, and the health check.
