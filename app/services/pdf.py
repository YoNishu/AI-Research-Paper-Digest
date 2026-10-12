import logging
from pathlib import Path

import httpx
import pymupdf
from azure.storage.blob.aio import BlobServiceClient

from app.config import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


async def download_pdf(pdf_url: str, paper_id: int) -> Path:
    local_path = DATA_DIR / f"paper_{paper_id}.pdf"
    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        resp = await client.get(pdf_url)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)
    size_mb = local_path.stat().st_size / (1024 * 1024)
    logger.info("Downloaded %s (%.1f MB)", local_path.name, size_mb)
    return local_path


def _blob_service() -> BlobServiceClient:
    if settings.azure_blob_connection_string:
        logger.debug("Using connection string for blob storage")
        return BlobServiceClient.from_connection_string(
            settings.azure_blob_connection_string
        )
    # Use managed identity (DefaultAzureCredential)
    from azure.identity.aio import DefaultAzureCredential

    logger.debug("Using DefaultAzureCredential for blob storage account=%s", settings.azure_storage_account_name)
    account_url = f"https://{settings.azure_storage_account_name}.blob.core.windows.net"
    return BlobServiceClient(account_url, credential=DefaultAzureCredential())


async def upload_to_blob(local_path: Path, blob_name: str) -> str:
    async with _blob_service() as bsc:
        container = bsc.get_container_client(settings.azure_blob_container_name)
        blob = container.get_blob_client(blob_name)
        with open(local_path, "rb") as f:
            await blob.upload_blob(f, overwrite=True)
        logger.info("Uploaded blob %s", blob_name)
        return blob.url


async def delete_blob(blob_name: str) -> None:
    try:
        async with _blob_service() as bsc:
            container = bsc.get_container_client(settings.azure_blob_container_name)
            await container.delete_blob(blob_name)
            logger.info("Deleted blob %s", blob_name)
    except Exception:
        logger.warning("Failed to delete blob %s", blob_name, exc_info=True)


def extract_text(pdf_path: Path) -> str:
    doc = pymupdf.open(str(pdf_path))
    pages: list[str] = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text)
    doc.close()
    full_text = "\n\n".join(pages)
    logger.info("Extracted %d chars from %s", len(full_text), pdf_path.name)
    return full_text


def cleanup_local_files(*paths: Path) -> None:
    for p in paths:
        try:
            if p.exists():
                p.unlink()
                logger.debug("Deleted local file %s", p)
        except Exception:
            logger.warning("Failed to delete %s", p, exc_info=True)
