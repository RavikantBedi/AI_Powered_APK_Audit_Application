"""FastAPI entry point for the modular agent platform."""
import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401 — registers tables with Base
from app.database import Base, engine
from app.routes import admin, cleanup, clients, knowledge, webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

Base.metadata.create_all(bind=engine)

# Mini-migration: create_all doesn't add columns to existing tables, so add
# columns introduced after Stage 1 to older dev databases. Replace with real
# migrations (Alembic) when moving to Postgres.
from sqlalchemy import text  # noqa: E402

with engine.connect() as conn:
    for ddl in (
        "ALTER TABLE conversations ADD COLUMN lead_status VARCHAR",
        "ALTER TABLE conversations ADD COLUMN lead_answers JSON",
    ):
        try:
            conn.execute(text(ddl))
            conn.commit()
        except Exception:
            pass  # column already exists

app = FastAPI(title="AI Agency Platform")

app.include_router(webhook.router)
app.include_router(clients.router)
app.include_router(cleanup.router)
app.include_router(admin.router)
app.include_router(knowledge.router)
app.mount("/widget", StaticFiles(directory="static", html=True), name="widget")


@app.get("/admin", include_in_schema=False)
def admin_page():
    from fastapi.responses import FileResponse
    return FileResponse("static/admin.html")


@app.on_event("startup")
def start_scheduler():
    from app.scheduler import start
    start()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/widget/")


@app.get("/health")
def health():
    return {"status": "ok"}
