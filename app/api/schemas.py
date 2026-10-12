from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    arxiv_code: str
    name: str | None = None
    description: str | None = None


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    research_interest: str | None = None


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    research_interest: str | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CategoryResponse(BaseModel):
    id: int
    name: str
    arxiv_code: str
    description: str | None
    added_at: datetime

    model_config = {"from_attributes": True}


class PaperResponse(BaseModel):
    id: int
    category_id: int
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str
    published_at: datetime
    categories: list[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisResponse(BaseModel):
    id: int
    paper_id: int
    summary: str
    key_contributions: list[str]
    methodology: str
    limitations: str | None
    keywords: list[str]
    novelty_score: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DigestItem(BaseModel):
    paper: PaperResponse
    category_name: str
    analysis: AnalysisResponse

    model_config = {"from_attributes": True}
