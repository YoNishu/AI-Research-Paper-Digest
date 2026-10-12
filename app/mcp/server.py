import logging

from fastmcp import FastMCP

from app.db import crud

logger = logging.getLogger(__name__)

mcp = FastMCP("Paper Digest Assistant")


@mcp.tool()
async def get_daily_digest() -> str:
    """Get today's paper digest — papers from the last 24 hours ranked by novelty score."""
    logger.info("MCP tool: get_daily_digest")
    papers = await crud.get_daily_digest()
    logger.info("MCP get_daily_digest: returning %d papers", len(papers))
    if not papers:
        return "No new papers in the last 24 hours."
    lines = []
    for p in papers:
        a = p.analysis
        lines.append(
            f"**{p.title}** (Score: {a.novelty_score}/10)\n"
            f"Authors: {', '.join(p.authors[:3])}\n"
            f"Summary: {a.summary[:300]}\n"
            f"Keywords: {', '.join(a.keywords)}"
        )
    return "\n\n---\n\n".join(lines)


@mcp.tool()
async def search_papers(query: str) -> str:
    """Search papers by keyword across titles, abstracts, summaries, and keywords."""
    logger.info("MCP tool: search_papers query='%s'", query)
    papers = await crud.search_papers(query)
    logger.info("MCP search_papers: %d results for '%s'", len(papers), query)
    if not papers:
        return f"No papers found matching '{query}'."
    lines = []
    for p in papers[:10]:
        a = p.analysis
        lines.append(
            f"[ID:{p.id}] **{p.title}** — Score: {a.novelty_score}/10\n"
            f"Summary: {a.summary[:200]}"
        )
    return "\n\n".join(lines)


@mcp.tool()
async def get_paper_analysis(paper_id: int) -> str:
    """Get the full analysis for a specific paper."""
    logger.info("MCP tool: get_paper_analysis paper_id=%d", paper_id)
    paper = await crud.get_paper(paper_id)
    if not paper or not paper.analysis:
        return f"Paper {paper_id} not found or not yet analysed."
    a = paper.analysis
    return (
        f"**{paper.title}**\n"
        f"Authors: {', '.join(paper.authors)}\n"
        f"Novelty Score: {a.novelty_score}/10\n\n"
        f"**Summary**: {a.summary}\n\n"
        f"**Key Contributions**:\n" + "\n".join(f"- {c}" for c in a.key_contributions) + "\n\n"
        f"**Methodology**: {a.methodology}\n\n"
        f"**Limitations**: {a.limitations or 'Not specified'}\n\n"
        f"**Abstract**: {paper.abstract[:2000]}"
    )


@mcp.tool()
async def add_category(arxiv_code: str) -> str:
    """Subscribe to a new arXiv category."""
    logger.info("MCP tool: add_category code='%s'", arxiv_code)
    existing = await crud.get_category_by_code(arxiv_code)
    if existing:
        return f"Already subscribed to {arxiv_code}."
    await crud.create_category(name=arxiv_code, arxiv_code=arxiv_code)
    return f"Subscribed to {arxiv_code}. Papers will appear after the next poll."


@mcp.tool()
async def list_categories() -> str:
    """List all subscribed arXiv categories."""
    logger.info("MCP tool: list_categories")
    cats = await crud.get_all_categories()
    if not cats:
        return "No categories subscribed."
    return "\n".join(f"- {c.name} ({c.arxiv_code})" for c in cats)
