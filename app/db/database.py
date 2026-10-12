import ssl
import logging
import certifi
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

connect_args: dict = {}
if "azure.com" in settings.database_url:
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    connect_args["ssl"] = ctx
    logger.info("Database: SSL enabled for Azure PostgreSQL")

logger.info("Database engine created — host=%s", settings.database_url.split("@")[-1].split("/")[0] if "@" in settings.database_url else "localhost")
engine = create_async_engine(settings.database_url, connect_args=connect_args)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session
