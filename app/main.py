import os

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from app import db
from app.routers import todo, tools


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    yield
    await db.close()


PREFIX = "/toolsapi/v1"

app = FastAPI(
    title="Main Page API",
    lifespan=lifespan,
    docs_url=f"{PREFIX}/docs",
    redoc_url=f"{PREFIX}/redoc",
    openapi_url=f"{PREFIX}/openapi.json",
)

# Comma-separated origins of the Next.js app, e.g. "https://example.com,http://localhost:3000"
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Pad-Updated"],
)

api = APIRouter(prefix=PREFIX)
api.include_router(todo.router)
api.include_router(tools.router)
app.include_router(api)


@app.get(f"{PREFIX}/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
