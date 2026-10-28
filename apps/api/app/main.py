from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db import SessionLocal, init_db
from app.services.hybrid_index import refresh_hybrid_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.prepare_runtime_directories()
    init_db()

    # De BM25-index leeft in het geheugen en overleeft een herstart niet. Zonder
    # deze herbouw is de sparse tak leeg tot de eerste ingest, en degradeert elke
    # vraag stil naar dense-only.
    db = SessionLocal()
    try:
        refresh_hybrid_index(db)
    finally:
        db.close()

    yield


app = FastAPI(title=settings.project_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Next kiest een andere poort zodra 3000 bezet is. Voor een tool die alleen
    # op je eigen machine draait is elke localhost-poort toestaan veiliger dan
    # elke keer de configuratie moeten bijwerken.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
