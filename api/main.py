"""FastAPI application factory for the College Academic AI Agent.

Start the development server with:

    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

The ``app`` instance is also the entry point for production ASGI servers
(e.g. gunicorn with uvicorn workers).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import admin, auth, chat, timetable


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ARG001
    """Run startup and shutdown logic.

    At startup: nothing yet (DB engine is created lazily in db/session.py).
    At shutdown: dispose of the connection pool cleanly.
    """
    yield
    # Import here to avoid circular imports at module level.
    from db.session import engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="MITS Academic AI Agent API",
        description=(
            "REST API for the MITS Gwalior academic intelligence platform. "
            "Provides authenticated access to timetables, syllabi, calendars "
            "and the AI agent chat interface."
        ),
        version="0.5.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Allow the React frontend (port 3000 in dev) and any configured origin.
    # In production, restrict this to your actual domain.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    application.include_router(auth.router, prefix="/api/v1")
    application.include_router(timetable.router, prefix="/api/v1")
    application.include_router(chat.router, prefix="/api/v1")
    application.include_router(admin.router, prefix="/api/v1")

    # Static pages served at /app/
    application.mount("/app", StaticFiles(directory="static", html=True), name="static")

    @application.get("/health", tags=["meta"], summary="Health check")
    async def health():
        """Return 200 OK — used by load balancers and container orchestrators."""
        return {"status": "ok", "version": application.version}

    return application


app = create_app()
