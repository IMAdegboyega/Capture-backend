# Capture API — FastAPI Backend

Custom Python backend for the Capture screen recording & video sharing platform.  
Replaces the original Next.js server actions with a standalone REST API.

## Tech Stack

- **FastAPI** — async Python web framework
- **SQLAlchemy 2.0** — async ORM with asyncpg driver
- **Alembic** — database migrations
- **python-jose** — JWT authentication
- **httpx** — async HTTP client for Bunny.net APIs
- **slowapi** — rate limiting
- **Pydantic v2** — request/response validation

## Project Structure

```
capture-backend/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Environment settings (pydantic-settings)
│   ├── database.py          # Async SQLAlchemy session
│   ├── models.py            # SQLAlchemy ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── routers/
│   │   ├── auth.py          # Google OAuth + JWT endpoints
│   │   └── videos.py        # Video CRUD, search, pagination
│   ├── services/
│   │   ├── auth.py          # Token creation, Google OAuth, user mgmt
│   │   └── bunny.py         # Bunny.net Stream/Storage/CDN service
│   └── middleware/
│       └── rate_limit.py    # slowapi rate limiter
├── migrations/              # Alembic migrations
├── requirements.txt
├── alembic.ini
└── .env.example
```

## Setup

```bash
# 1. Clone & enter
cd capture-backend

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your actual credentials

# 5. Run migrations (if connecting to a fresh DB)
alembic revision --autogenerate -m "initial"
alembic upgrade head

# 6. Start the server
uvicorn app.main:app --reload --port 8000
```

## API Endpoints

### Auth
| Method | Endpoint             | Description                          | Auth |
|--------|----------------------|--------------------------------------|------|
| POST   | `/api/auth/google`   | Exchange Google auth code for JWT    | No   |
| POST   | `/api/auth/refresh`  | Refresh access token                 | No   |
| GET    | `/api/auth/me`       | Get current user profile             | Yes  |

### Videos
| Method | Endpoint                         | Description                        | Auth     |
|--------|----------------------------------|------------------------------------|----------|
| GET    | `/api/videos`                    | List/search videos (paginated)     | Optional |
| POST   | `/api/videos`                    | Save video details to DB           | Yes      |
| GET    | `/api/videos/{video_id}`         | Get single video                   | No       |
| DELETE | `/api/videos/{video_id}`         | Delete video (Bunny + DB)          | Yes      |
| PATCH  | `/api/videos/{video_id}/views`   | Increment view count               | No       |
| PATCH  | `/api/videos/{video_id}/visibility` | Toggle public/private           | Yes      |
| GET    | `/api/videos/{video_id}/transcript` | Get AI transcript              | No       |
| GET    | `/api/videos/{video_id}/status`  | Check encoding progress            | Yes      |
| POST   | `/api/videos/upload-url`         | Get Bunny upload URL               | Yes      |
| POST   | `/api/videos/thumbnail-url`      | Get thumbnail upload URL           | Yes      |
| GET    | `/api/videos/user/{user_id}`     | Get all videos for a user          | Optional |

### Utility
| Method | Endpoint        | Description  |
|--------|-----------------|--------------|
| GET    | `/api/health`   | Health check |

## Query Parameters

**GET /api/videos**
- `query` — search term (fuzzy title match)
- `filter` — sort: `Most Viewed`, `Least Viewed`, `Oldest First`, `Most Recent`
- `page` — page number (default: 1)
- `page_size` — items per page (default: 8, max: 50)

**GET /api/videos/user/{user_id}**
- `query` — search term
- `filter` — sort order

## Notes

- The database schema is fully compatible with the existing Drizzle/Xata tables — no migration needed if connecting to the same DB.
- For Xata specifically, swap the DATABASE_URL driver from `postgresql+asyncpg://` to point at your Xata Postgres endpoint.
- Video/thumbnail file uploads still happen client-side directly to Bunny.net — the backend only provides the signed URLs and persists metadata.
