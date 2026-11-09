from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.api.v1.indices import router as indices_router
from app.core.database import SessionLocal
from app.models.index import Index, IndexProviderMapping
from app.api.v1.providers import router as providers_router
from app.api.v1.cycles import cycles_router



from app.api.exception_handlers import (
    api_service_exception_handler,
)
from app.services.api_errors import APIServiceError
from app.api.v1.market import router as market_router
from app.api.v1.indicators import router as indicators_router
from app.api.v1.structure import router as structure_router
from app.api.v1.multi_timeframe import router as multi_timeframe_router



DEFAULT_INDICES = [
    {
        "code": "NIFTY50",
        "name": "NIFTY 50",
        "exchange": "NSE",
        "category": "market_index",
        "description": "NSE broad-market benchmark index.",
        "display_order": 1,
    },
    {
        "code": "BANKNIFTY",
        "name": "BANK NIFTY",
        "exchange": "NSE",
        "category": "market_index",
        "description": "NSE banking sector index.",
        "display_order": 2,
    },
    {
        "code": "SENSEX",
        "name": "SENSEX",
        "exchange": "BSE",
        "category": "market_index",
        "description": "BSE benchmark index.",
        "display_order": 3,
    },
    {
        "code": "FINNIFTY",
        "name": "FINNIFTY",
        "exchange": "NSE",
        "category": "market_index",
        "description": "NSE Financial Services index.",
        "display_order": 4,
    },
    {
        "code": "MIDCPNIFTY",
        "name": "NIFTY Midcap Select",
        "exchange": "NSE",
        "category": "market_index",
        "description": "NSE Midcap Select index.",
        "display_order": 5,
    },
    {
        "code": "INDIA_VIX",
        "name": "India VIX",
        "exchange": "NSE",
        "category": "volatility_index",
        "description": "India volatility index.",
        "display_order": 6,
    },
]


def initialize_database():
    """Seed missing default indices. Schema creation is managed by Alembic."""

    with SessionLocal() as db:
        try:
            existing_codes = set(
                db.scalars(select(Index.code)).all()
            )

            missing_indices = [
                Index(**item)
                for item in DEFAULT_INDICES
                if item["code"] not in existing_codes
            ]

            if missing_indices:
                db.add_all(missing_indices)
                db.commit()

        except Exception:
            db.rollback()
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Market Cycle Tracker",
    description=(
        "Daily, weekly and monthly market-cycle "
        "analysis for Indian indices."
    ),
    version="1.2.0",
    lifespan=lifespan,
)

app.add_exception_handler(
    APIServiceError,
    api_service_exception_handler,
)

app.include_router(
    indices_router,
    prefix="/api/v1",
)

app.include_router(
    market_router, 
    prefix="/api/v1",
    )

app.include_router(
    providers_router,
    prefix="/api/v1",
)

app.include_router(
    structure_router, 
    prefix="/api/v1",
)

app.include_router(
    indicators_router,
    prefix="/api/v1",
)

app.include_router(
    multi_timeframe_router,
    prefix="/api/v1",
)

app.include_router(
    cycles_router, 
    prefix="/api/v1",
)

@app.get("/")
def root():
    return {
        "application": "Market Cycle Tracker",
        "version": "1.2.0",
        "status": "running",
    }


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "healthy",
        "application": "Market Cycle Tracker",
    }

