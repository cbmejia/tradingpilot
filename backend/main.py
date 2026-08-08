# TradePilot AI — FastAPI app entrypoint.
#
# Run with:
#   uvicorn backend.main:app --reload
# Then open http://127.0.0.1:8000/docs to try the API in a browser.
#
# See docs/architecture.md for the full request/orchestration flow. As of
# Milestone 4, only run creation and reading exist — there is no pipeline
# (capture/market data/agent/eval/guardrails) wired in yet.

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import config
from backend.api import routes_health, routes_runs
from database.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Makes sure the database file and its tables exist before the first
    # request arrives -- so a fresh clone works without a manual step.
    init_db()
    yield


app = FastAPI(
    title="TradePilot AI",
    description=(
        "Educational decision-support tool for discretionary forex traders. "
        "This application never places, submits, or simulates a trade."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)
app.include_router(routes_runs.router)
