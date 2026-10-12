import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings
from app.db.database import engine
from app.db.models import Base
from app.mcp.server import mcp
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.ui.views import ui_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Research Paper Digest")
    logger.info("Azure OpenAI endpoint: %s", settings.azure_openai_endpoint or "NOT SET")
    logger.info("Azure OpenAI deployment: %s", settings.azure_openai_deployment)
    logger.info("Database: %s", settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url)
    logger.info("Blob container: %s", settings.azure_blob_container_name)
    logger.info("Poll interval: %dh", settings.poll_interval_hours)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")

    start_scheduler()
    logger.info("Application ready")
    yield
    stop_scheduler()
    await engine.dispose()
    logger.info("Application shutdown complete")


app = FastAPI(title="AI Research Paper Digest", lifespan=lifespan)

app.include_router(api_router)
app.include_router(ui_router)
app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")

# Mount MCP server
mcp_app = mcp.http_app(path="/mcp")
app.mount("/mcp", mcp_app)
