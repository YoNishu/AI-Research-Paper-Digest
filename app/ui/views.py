import logging

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import crud
from app.services.arxiv_feed import poll_all_categories, poll_category, sync_categories_from_yaml
from app.services.pipeline import process_pending_papers

logger = logging.getLogger(__name__)

ui_router = APIRouter(prefix="/ui")
templates = Jinja2Templates(directory="app/ui/templates")


@ui_router.get("", response_class=HTMLResponse)
async def digest_page(request: Request):
    logger.debug("GET /ui — loading digest")
    papers = await crud.get_daily_digest()
    logger.info("Digest page: %d papers in last 24h", len(papers))
    return templates.TemplateResponse(request=request, name="digest.html", context={"papers": papers})


@ui_router.post("/refresh")
async def refresh(request: Request):
    logger.info("POST /ui/refresh — manual refresh triggered")
    await sync_categories_from_yaml()
    await poll_all_categories()
    await process_pending_papers()
    logger.info("Manual refresh complete")
    return RedirectResponse("/ui", status_code=303)


@ui_router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request):
    cats = await crud.get_all_categories()
    return templates.TemplateResponse(request=request, name="categories.html", context={"categories": cats})


@ui_router.post("/categories/add")
async def add_category_form(request: Request, arxiv_code: str = Form(...)):
    logger.info("POST /ui/categories/add — code=%s", arxiv_code.strip())
    existing = await crud.get_category_by_code(arxiv_code.strip())
    if not existing:
        cat = await crud.create_category(name=arxiv_code.strip(), arxiv_code=arxiv_code.strip())
        try:
            await poll_category(cat.arxiv_code, cat.id)
            await process_pending_papers()
        except Exception:
            logger.exception("Background processing failed")
    return RedirectResponse("/ui/categories", status_code=303)


@ui_router.post("/categories/{category_id}/delete")
async def delete_category_form(category_id: int):
    logger.info("POST /ui/categories/%d/delete", category_id)
    await crud.delete_category(category_id)
    return RedirectResponse("/ui/categories", status_code=303)


@ui_router.get("/papers", response_class=HTMLResponse)
async def browse_papers_page(
    request: Request,
    q: str = Query("", alias="q"),
    category: int = Query(0, alias="category"),
    min_score: int = Query(0, alias="min_score"),
    sort: str = Query("newest", alias="sort"),
    page: int = Query(1, alias="page"),
):
    logger.info("GET /ui/papers — q=%s category=%s score>=%s sort=%s page=%d", q, category, min_score, sort, page)
    cat_id = category if category > 0 else None
    score = min_score if min_score > 0 else None
    papers, total = await crud.browse_papers(
        query=q or None, category_id=cat_id, min_score=score, sort=sort, page=page,
    )
    categories = await crud.get_all_categories()
    total_pages = max(1, (total + 19) // 20)
    return templates.TemplateResponse(
        request=request,
        name="browse.html",
        context={
            "papers": papers, "total": total, "page": page, "total_pages": total_pages,
            "q": q, "category": category, "min_score": min_score, "sort": sort,
            "categories": categories,
        },
    )


@ui_router.get("/paper/{paper_id}", response_class=HTMLResponse)
async def paper_detail_page(request: Request, paper_id: int):
    logger.debug("GET /ui/paper/%d", paper_id)
    paper = await crud.get_paper(paper_id)
    if not paper:
        logger.warning("Paper %d not found", paper_id)
        return HTMLResponse("Paper not found", status_code=404)
    return templates.TemplateResponse(request=request, name="paper.html", context={"paper": paper})


@ui_router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request=request, name="chat.html", context={"conversation_id": None})


@ui_router.get("/chat/{conversation_id}", response_class=HTMLResponse)
async def chat_with_conversation(request: Request, conversation_id: int):
    return templates.TemplateResponse(
        request=request, name="chat.html", context={"conversation_id": conversation_id}
    )
