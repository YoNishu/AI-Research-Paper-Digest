import asyncio
import logging
import re
from pathlib import Path

import arxiv
import feedparser
import yaml

from app.config import settings
from app.db import crud

logger = logging.getLogger(__name__)

ARXIV_RSS_BASE = "https://rss.arxiv.org/rss"


def load_categories_from_yaml() -> list[dict]:
    path = Path(settings.categories_file)
    if not path.exists():
        logger.warning("Categories file %s not found", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("categories", [])


async def sync_categories_from_yaml() -> None:
    cats = load_categories_from_yaml()
    for c in cats:
        existing = await crud.get_category_by_code(c["arxiv_code"])
        if not existing:
            await crud.create_category(
                name=c.get("name", c["arxiv_code"]),
                arxiv_code=c["arxiv_code"],
                description=c.get("description"),
            )
            logger.info("Synced category %s from YAML", c["arxiv_code"])


def _extract_arxiv_id(link: str) -> str | None:
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", link)
    return m.group(0) if m else None


async def _fetch_metadata(arxiv_ids: list[str]) -> dict[str, arxiv.Result]:
    if not arxiv_ids:
        return {}
    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    search = arxiv.Search(id_list=arxiv_ids)
    results = await asyncio.to_thread(lambda: list(client.results(search)))
    mapping: dict[str, arxiv.Result] = {}
    for r in results:
        aid = r.entry_id.split("/abs/")[-1]
        mapping[aid] = r
    return mapping


async def poll_category(arxiv_code: str, category_id: int) -> int:
    url = f"{ARXIV_RSS_BASE}/{arxiv_code}"
    logger.info("Polling %s", url)

    feed = await asyncio.to_thread(feedparser.parse, url)
    entries = feed.get("entries", [])
    if not entries:
        logger.info("No entries in feed for %s", arxiv_code)
        return 0

    rss_ids: list[str] = []
    for entry in entries:
        link = entry.get("link", "") or entry.get("id", "")
        aid = _extract_arxiv_id(link)
        if aid:
            rss_ids.append(aid)

    if not rss_ids:
        return 0

    existing = await crud.get_existing_arxiv_ids(rss_ids)
    new_ids = [aid for aid in rss_ids if aid not in existing]
    if not new_ids:
        logger.info("No new papers for %s", arxiv_code)
        return 0

    metadata = await _fetch_metadata(new_ids)

    papers_data: list[dict] = []
    for aid, result in metadata.items():
        papers_data.append(
            {
                "category_id": category_id,
                "arxiv_id": aid,
                "title": result.title,
                "authors": [a.name for a in result.authors],
                "abstract": result.summary,
                "pdf_url": result.pdf_url,
                "published_at": result.published,
                "categories": list(result.categories),
                "journal_ref": result.journal_ref,
                "doi": result.doi,
            }
        )

    await crud.create_papers_bulk(papers_data)
    logger.info("Inserted %d new papers for %s", len(papers_data), arxiv_code)
    return len(papers_data)


async def poll_all_categories() -> dict[str, int]:
    categories = await crud.get_all_categories()
    results: dict[str, int] = {}
    for cat in categories:
        try:
            count = await poll_category(cat.arxiv_code, cat.id)
            results[cat.name] = count
        except Exception:
            logger.exception("Error polling %s", cat.arxiv_code)
            results[cat.name] = 0
    return results
