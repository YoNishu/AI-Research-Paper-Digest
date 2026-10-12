import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import cast, delete, func, select, String as SAString
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import async_session
from app.db.models import (
    Analysis,
    Category,
    Conversation,
    Message,
    MessageRole,
    Paper,
    PaperStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category CRUD
# ---------------------------------------------------------------------------

async def get_all_categories() -> list[Category]:
    async with async_session() as s:
        result = await s.execute(select(Category).order_by(Category.added_at.desc()))
        return list(result.scalars().all())


async def get_category_by_code(arxiv_code: str) -> Category | None:
    async with async_session() as s:
        result = await s.execute(select(Category).where(Category.arxiv_code == arxiv_code))
        return result.scalar_one_or_none()


async def create_category(name: str, arxiv_code: str, description: str | None = None) -> Category:
    async with async_session() as s:
        cat = Category(name=name, arxiv_code=arxiv_code, description=description)
        s.add(cat)
        await s.commit()
        await s.refresh(cat)
        logger.info("Created category id=%d code=%s", cat.id, arxiv_code)
        return cat


async def delete_category(category_id: int) -> None:
    async with async_session() as s:
        await s.execute(delete(Category).where(Category.id == category_id))
        await s.commit()
        logger.info("Deleted category id=%d", category_id)


# ---------------------------------------------------------------------------
# Paper CRUD
# ---------------------------------------------------------------------------

async def get_existing_arxiv_ids(arxiv_ids: list[str]) -> set[str]:
    if not arxiv_ids:
        return set()
    async with async_session() as s:
        result = await s.execute(select(Paper.arxiv_id).where(Paper.arxiv_id.in_(arxiv_ids)))
        return set(result.scalars().all())


async def create_papers_bulk(papers: list[dict]) -> list[Paper]:
    if not papers:
        return []
    async with async_session() as s:
        objs = [Paper(**p) for p in papers]
        s.add_all(objs)
        await s.commit()
        for o in objs:
            await s.refresh(o)
        logger.info("Bulk inserted %d papers", len(objs))
        return objs


async def get_pending_papers() -> list[Paper]:
    async with async_session() as s:
        result = await s.execute(
            select(Paper)
            .where(Paper.status == PaperStatus.pending)
            .order_by(Paper.created_at.asc())
        )
        return list(result.scalars().all())


async def update_paper_status(
    paper_id: int, status: PaperStatus, error_message: str | None = None
) -> None:
    async with async_session() as s:
        paper = await s.get(Paper, paper_id)
        if paper:
            paper.status = status
            paper.error_message = error_message
            await s.commit()
            logger.debug("Paper %d status -> %s", paper_id, status.value)


async def get_papers(
    category_id: int | None = None, status: str | None = None
) -> list[Paper]:
    async with async_session() as s:
        stmt = select(Paper).options(selectinload(Paper.category), selectinload(Paper.analysis))
        if category_id:
            stmt = stmt.where(Paper.category_id == category_id)
        if status:
            stmt = stmt.where(Paper.status == PaperStatus(status))
        stmt = stmt.order_by(Paper.published_at.desc())
        result = await s.execute(stmt)
        return list(result.scalars().all())


async def get_paper(paper_id: int) -> Paper | None:
    async with async_session() as s:
        result = await s.execute(
            select(Paper)
            .options(selectinload(Paper.category), selectinload(Paper.analysis))
            .where(Paper.id == paper_id)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Analysis CRUD
# ---------------------------------------------------------------------------

async def create_analysis(
    paper_id: int,
    full_text: str,
    summary: str,
    key_contributions: list[str],
    methodology: str,
    limitations: str | None,
    keywords: list[str],
    novelty_score: int,
) -> Analysis:
    async with async_session() as s:
        a = Analysis(
            paper_id=paper_id,
            full_text=full_text,
            summary=summary,
            key_contributions=key_contributions,
            methodology=methodology,
            limitations=limitations,
            keywords=keywords,
            novelty_score=novelty_score,
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
        logger.info("Created analysis for paper %d — score=%d, keywords=%s", paper_id, novelty_score, keywords)
        return a


async def get_analysis_by_paper(paper_id: int) -> Analysis | None:
    async with async_session() as s:
        result = await s.execute(select(Analysis).where(Analysis.paper_id == paper_id))
        return result.scalar_one_or_none()


async def get_daily_digest() -> list[Paper]:
    async with async_session() as s:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await s.execute(
            select(Paper)
            .join(Paper.analysis)
            .options(selectinload(Paper.analysis), selectinload(Paper.category))
            .where(Analysis.created_at >= cutoff)
            .order_by(Analysis.novelty_score.desc())
        )
        papers = list(result.scalars().all())
        # Fallback: if no papers in last 24h, return the latest 20
        if not papers:
            result = await s.execute(
                select(Paper)
                .join(Paper.analysis)
                .options(selectinload(Paper.analysis), selectinload(Paper.category))
                .order_by(Analysis.created_at.desc())
                .limit(20)
            )
            papers = list(result.scalars().all())
        return papers


async def search_papers(query: str) -> list[Paper]:
    logger.debug("Searching papers for query='%s'", query)
    async with async_session() as s:
        pattern = f"%{query}%"
        result = await s.execute(
            select(Paper)
            .join(Paper.analysis)
            .options(selectinload(Paper.analysis), selectinload(Paper.category))
            .where(
                Paper.title.ilike(pattern)
                | Analysis.summary.ilike(pattern)
                | cast(Analysis.keywords, SAString).ilike(pattern)
                | Paper.abstract.ilike(pattern)
            )
            .order_by(Analysis.novelty_score.desc())
        )
        return list(result.scalars().unique().all())


async def browse_papers(
    query: str | None = None,
    category_id: int | None = None,
    min_score: int | None = None,
    sort: str = "newest",
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Paper], int]:
    """Browse all papers with search, category filter, score filter, sorting, and pagination."""
    async with async_session() as s:
        stmt = (
            select(Paper)
            .join(Paper.analysis)
            .options(selectinload(Paper.analysis), selectinload(Paper.category))
        )
        count_stmt = select(func.count(Paper.id)).join(Paper.analysis)

        if query:
            pattern = f"%{query}%"
            filt = (
                Paper.title.ilike(pattern)
                | Analysis.summary.ilike(pattern)
                | cast(Analysis.keywords, SAString).ilike(pattern)
                | Paper.abstract.ilike(pattern)
            )
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)

        if category_id:
            stmt = stmt.where(Paper.category_id == category_id)
            count_stmt = count_stmt.where(Paper.category_id == category_id)

        if min_score is not None:
            stmt = stmt.where(Analysis.novelty_score >= min_score)
            count_stmt = count_stmt.where(Analysis.novelty_score >= min_score)

        if sort == "score":
            stmt = stmt.order_by(Analysis.novelty_score.desc())
        elif sort == "oldest":
            stmt = stmt.order_by(Paper.published_at.asc())
        else:  # newest
            stmt = stmt.order_by(Paper.published_at.desc())

        total = (await s.execute(count_stmt)).scalar() or 0
        offset = (page - 1) * per_page
        stmt = stmt.offset(offset).limit(per_page)

        result = await s.execute(stmt)
        return list(result.scalars().unique().all()), total


# ---------------------------------------------------------------------------
# Conversation + Message CRUD
# ---------------------------------------------------------------------------

async def create_conversation(
    title: str = "New Chat", research_interest: str | None = None
) -> Conversation:
    async with async_session() as s:
        c = Conversation(title=title, research_interest=research_interest)
        s.add(c)
        await s.commit()
        await s.refresh(c)
        logger.info("Created conversation id=%d title='%s'", c.id, title)
        return c


async def get_conversations() -> list[Conversation]:
    async with async_session() as s:
        result = await s.execute(
            select(Conversation).order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())


async def get_conversation(conversation_id: int) -> Conversation | None:
    async with async_session() as s:
        return await s.get(Conversation, conversation_id)


async def get_conversation_messages(conversation_id: int) -> list[Message]:
    async with async_session() as s:
        result = await s.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())


async def add_message(
    conversation_id: int,
    role: MessageRole,
    content: str | None = None,
    tool_calls: list | None = None,
    tool_call_id: str | None = None,
) -> Message:
    async with async_session() as s:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        s.add(msg)
        conv = await s.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.now(timezone.utc)
        await s.commit()
        await s.refresh(msg)
        return msg


async def delete_conversation(conversation_id: int) -> None:
    async with async_session() as s:
        await s.execute(delete(Conversation).where(Conversation.id == conversation_id))
        await s.commit()
        logger.info("Deleted conversation id=%d", conversation_id)


async def update_conversation_research_interest(
    conversation_id: int, research_interest: str
) -> None:
    async with async_session() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv:
            conv.research_interest = research_interest
            await s.commit()


async def update_conversation_title(conversation_id: int, title: str) -> None:
    async with async_session() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv:
            conv.title = title
            await s.commit()
