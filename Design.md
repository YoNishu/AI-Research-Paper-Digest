# AI Research Paper Digest — Design Document

> **Author**: Pathik Patel
> **Date**: 29 March 2026
> **Status**: Draft

## Overview

A FastAPI service that automatically polls arXiv RSS feeds by research category, downloads papers as PDFs, extracts full text, and generates structured AI analyses via Azure OpenAI GPT-4o (AI Foundry) — including a plain-English summary, key contributions, methodology breakdown, novelty score (1–10), and extracted keywords. Delivers a daily digest ranked by novelty, and includes a conversational AI chat agent for exploring your paper library through natural language.

Hosted on Azure App Service. AI stack powered by Azure OpenAI GPT-4o (AI Foundry). Infrastructure covered by Azure credits.

---

## Problem Statement

Researchers tracking multiple arXiv categories face an overwhelming volume of daily submissions — cs.AI alone can publish 50–100 papers per day. There's no efficient way to triage which papers deserve a full read without scanning every abstract manually, and abstracts alone often lack enough detail to judge novelty or relevance.

**Solution**: An automated pipeline that ingests new papers from arXiv, extracts their full text from PDFs, and generates structured AI analyses — then ranks them by a novelty score (1–10), giving you a scannable daily digest. A chat agent lets you ask questions about papers, search across extracted content, compare methodologies, and get personalized recommendations aligned to your research interests.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11 | Best ecosystem for ML/NLP/PDF libraries |
| Framework | FastAPI (async) | High-performance async API, same pattern as podcast project |
| Paper Source | arXiv RSS feeds + `arxiv` Python library | RSS for daily new papers, `arxiv` lib for metadata + PDF download |
| PDF Extraction | PyMuPDF (`pymupdf`) | Fast, reliable PDF text extraction; handles multi-column layouts |
| Analysis | Azure OpenAI GPT-4o (JSON mode) | AI Foundry deployment; structured output; 128k context |
| Chat Agent | Azure OpenAI GPT-4o + Tool Calling | Function calling for DB queries, SSE streaming |
| Database | Azure PostgreSQL Flexible Server | B1ms, SSL-encrypted, async via asyncpg |
| Hosting | Azure App Service (B1 Linux) | Always-on, container deployment via ACR |
| Container | Docker → Azure Container Registry | Reproducible builds, managed image hosting |
| PDF Storage | Azure Blob Storage | Temporary PDF staging, cleaned after text extraction |
| Scheduler | APScheduler (AsyncIO) | In-process, no broker dependency |
| MCP Server | FastMCP (Python MCP SDK) | Expose tools to AI assistants (Claude Desktop, etc.) |
| Frontend | Jinja2 + vanilla JS + CSS | Server-rendered UI with SSE streaming for chat |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Azure App Service (B1 Linux)                    │
│                      Docker container via ACR                        │
│                                                                      │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────────┐       │
│  │ Scheduler │───▶│ arXiv Poller │───▶│  New Paper Detection  │       │
│  │ (6h poll) │    │ (RSS + API)  │    │  (arXiv ID dedup)     │       │
│  └──────────┘    └──────────────┘    └──────────┬────────────┘       │
│                                                  │                    │
│  ┌──────────┐                                    │                    │
│  │ Add Cat- │─── poll_category() ───────────────▶│                    │
│  │ egory API│    + BackgroundTasks                │                    │
│  └──────────┘                                    ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │   PDF Downloader      │       │
│                                      │ (arxiv lib → Blob)    │       │
│                                      └──────────┬────────────┘       │
│                                                  │                    │
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │   Text Extractor      │       │
│                                      │ (PyMuPDF full-text)   │──▶ Raw text
│                                      └──────────┬────────────┘       │
│                                                  │                    │
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │  Azure OpenAI GPT-4o  │       │
│                                      │  (analyze + score)     │──▶ Analysis +
│                                      └──────────┬────────────┘    Novelty Score
│                                                  │                (1-10)
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │  Azure PostgreSQL     │       │
│                                      │  (Flexible Server)    │       │
│                                      └──┬─────┬─────┬────────┘       │
│                                         │     │     │                 │
│                          ┌──────────────┘     │     └──────────┐      │
│                          ▼                    ▼                ▼      │
│               ┌──────────────┐    ┌────────────────┐  ┌────────────┐ │
│               │  REST API    │    │  Chat Agent    │  │ MCP Server │ │
│               │  (FastAPI)   │    │  (Tool Calling │  │ (FastMCP)  │ │
│               └──────┬───────┘    │   + SSE)       │  └────────────┘ │
│                      │            └───────┬────────┘                  │
│                      ▼                    ▼                           │
│               ┌────────────────────────────────────┐                 │
│               │           Web UI (Jinja2)          │                 │
│               │  Digest · Papers · Chat · Detail   │                 │
│               └────────────────────────────────────┘                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

| Component | What it does | Key behaviors |
|-----------|-------------|---------------|
| **arXiv Service** | Polls arXiv RSS feeds by category, fetches metadata via `arxiv` Python lib | Daily RSS check, arXiv ID-based dedup, multi-category subscription support |
| **PDF Service** | Downloads PDFs via `arxiv` lib, uploads to blob, extracts text | Streaming download, PyMuPDF text extraction, handles multi-column & LaTeX-heavy papers |
| **Analyzer** | Sends extracted text to Azure OpenAI GPT-4o | Structured JSON prompt, truncates papers >120k chars, validates output keys, clamps score 1–10 |
| **Pipeline** | Chains the above steps per paper | Marks papers processing→done/failed, always cleans up local files and blob, error-isolated per paper |
| **Scheduler** | Triggers poll+process on an interval | APScheduler AsyncIO, 6h default, syncs categories.yaml then polls all DB categories |
| **Chat Agent** | Conversational paper exploration | 7 tools, max 5 tool-calling rounds per message, SSE streaming, dual scoring (novelty + relevance to research interest) |
| **MCP Server** | Exposes tools for external AI agents | 5 tools (digest, search, detail, add category, list), shared CRUD layer |

---

## Data Flow: New Paper Processing

```
1. Scheduler fires (or user adds category)
2. arXiv RSS feed fetched for each subscribed category (e.g., cs.AI, cs.LG)
3. arXiv IDs compared against DB — only new papers inserted (status: pending)
4. For each new paper, fetch full metadata via arxiv Python library (title, authors, abstract, categories, published date, PDF URL)
5. Pipeline picks up pending papers sequentially:
   a. Download PDF via arxiv lib → local /data/ directory
   b. Upload PDF to Azure Blob Storage (staging)
   c. Extract full text via PyMuPDF → plain text string
   d. Extracted text → Azure OpenAI GPT-4o → JSON (summary, key_contributions, methodology, limitations, novelty_score, keywords)
   e. Analysis stored in DB, paper marked "done"
   f. Local files and blob deleted (cleanup always runs, even on error)
6. If any step fails: paper marked "failed" with error message, pipeline moves to next
```

### Pipeline Diagram

```
arXiv RSS (cs.AI, cs.LG, stat.ML, ...)
            ↓
   Parse feed, extract arXiv IDs
            ↓
   Dedup against DB (by arxiv_id)
            ↓
   Insert new papers (status: pending)
            ↓
   Fetch full metadata (arxiv Python lib)
            ↓
   Download PDF → local /data/paper_{id}.pdf
            ↓
   Upload to Azure Blob (staging)
            ↓
   PyMuPDF → extract full text
            ↓
   Truncate if >120k chars
            ↓
   Azure OpenAI GPT-4o (JSON mode)
   ┌────────────────────────────────┐
   │ {                              │
   │   "summary": "...",           │
   │   "key_contributions": [...], │
   │   "methodology": "...",       │
   │   "limitations": "...",       │
   │   "keywords": [...],          │
   │   "novelty_score": 8          │
   │ }                              │
   └────────────────────────────────┘
            ↓
   Store analysis in DB, mark "done"
            ↓
   Cleanup local file + blob
```

---

## Data Flow: Chat Message

```
1. User sends message via POST /chat (SSE stream)
2. Conversation loaded (or created), user message saved to DB
3. System prompt built dynamically: base instructions + subscribed categories + user's research interest
4. Message history loaded from DB → Azure OpenAI API format
5. Tool loop (max 5 rounds):
   a. Call Azure OpenAI GPT-4o with tools + history
   b. If model returns tool_calls: execute each, save results, emit SSE tool events
   c. If model returns text: break loop
6. Final text response streamed word-by-word via SSE
7. Complete response saved to DB
```

---

## Data Models

### Entity-Relationship Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Category   │     │    Paper     │     │   Analysis   │
│──────────────│     │──────────────│     │──────────────│
│ id (PK)      │     │ id (PK)      │     │ id (PK)      │
│ name         │◄───┐│ category_id  │     │ paper_id (FK)│
│ arxiv_code   │    ││ arxiv_id (UQ)│────▶│ full_text    │
│ description  │    ││ title        │     │ summary      │
│ added_at     │    ││ authors (JSON)     │ key_contribs │
└──────────────┘    ││ abstract     │     │ methodology  │
                    ││ pdf_url      │     │ limitations  │
                    ││ published_at │     │ keywords(JSON│
                    ││ categories   │     │ novelty_score│
                    │  (JSON)       │     │ created_at   │
                    ││ status       │     └──────────────┘
                    ││ error_message│
                    ││ created_at   │
                    │└──────────────┘
                    │       │
                    │       │ 1:1
                    │       ▼
                    │ ┌──────────────┐
                    │ │   Analysis   │
                    │ └──────────────┘
                    │
                    └─────── 1:N

┌──────────────┐     ┌──────────────┐
│ Conversation │     │   Message    │
│──────────────│     │──────────────│
│ id (PK)      │────▶│ id (PK)      │
│ title        │ 1:N │ conv_id (FK) │
│ research_    │     │ role         │
│   interest   │     │ content      │
│ created_at   │     │ tool_calls   │
│ updated_at   │     │ tool_call_id │
└──────────────┘     │ created_at   │
                     └──────────────┘
```

### Model Specifications

#### Category

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | Integer | PK, auto | |
| `name` | String | NOT NULL | Human-readable name (e.g., "Artificial Intelligence") |
| `arxiv_code` | String | UNIQUE, NOT NULL | arXiv category code (e.g., "cs.AI") |
| `description` | String | NULLABLE | User-added description of why they follow this category |
| `added_at` | DateTime | DEFAULT UTC now | |

**Relationships**: 1 → Many Papers

#### Paper

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | Integer | PK, auto | |
| `category_id` | Integer | FK → categories.id, CASCADE | Primary category that triggered ingestion |
| `arxiv_id` | String | UNIQUE, NOT NULL | arXiv identifier (e.g., "2403.12345v1") — dedup key |
| `title` | String | NOT NULL | Paper title from metadata |
| `authors` | JSON | NOT NULL | List of author names |
| `abstract` | Text | NOT NULL | arXiv abstract |
| `pdf_url` | String | NOT NULL | Direct PDF download URL |
| `published_at` | DateTime | NOT NULL | Original publication date on arXiv |
| `categories` | JSON | NOT NULL | All arXiv categories (e.g., ["cs.AI", "cs.LG"]) |
| `journal_ref` | String | NULLABLE | Journal reference if published |
| `doi` | String | NULLABLE | DOI if available |
| `status` | Enum | DEFAULT pending | `pending` → `processing` → `done` / `failed` |
| `error_message` | Text | NULLABLE | Failure reason if status=failed |
| `created_at` | DateTime | DEFAULT UTC now | When paper was discovered by our system |

**Relationships**: Many → 1 Category, 1 → 1 Analysis (cascade delete)

#### Analysis

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | Integer | PK, auto | |
| `paper_id` | Integer | FK → papers.id, UNIQUE, CASCADE | One analysis per paper |
| `full_text` | Text | NOT NULL | Complete extracted text from PDF |
| `summary` | Text | NOT NULL | AI-generated 3–5 sentence summary |
| `key_contributions` | JSON | NOT NULL | List of 2–5 key contributions |
| `methodology` | Text | NOT NULL | Description of methods/approach |
| `limitations` | Text | NULLABLE | Identified limitations |
| `keywords` | JSON | NOT NULL | Extracted keywords/topics |
| `novelty_score` | Integer | NOT NULL, 1–10 | AI-assessed novelty score |
| `created_at` | DateTime | DEFAULT UTC now | When analysis was completed |

**Scoring Rubric**:
- **1–3**: Incremental work, minor extensions of existing methods
- **4–5**: Solid contribution, useful but not groundbreaking
- **6–7**: Significant contribution, novel approach or strong results
- **8–9**: Highly novel, potential to shift the field
- **10**: Landmark paper, introduces a fundamentally new paradigm

#### Conversation

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | Integer | PK, auto | |
| `title` | String | NOT NULL, DEFAULT "New Chat" | Auto-generated from first message |
| `research_interest` | Text | NULLABLE | Equivalent to "objective" — e.g., "I'm working on efficient transformers" |
| `created_at` | DateTime | DEFAULT UTC now | |
| `updated_at` | DateTime | DEFAULT UTC now, ON UPDATE | Touched on new message |

**Relationships**: 1 → Many Messages (cascade delete)

#### Message

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | Integer | PK, auto | |
| `conversation_id` | Integer | FK → conversations.id, CASCADE | |
| `role` | Enum | NOT NULL | `user`, `assistant`, `tool` |
| `content` | Text | NULLABLE | Message text (null for tool calls) |
| `tool_calls` | JSON | NULLABLE | Structured tool call objects |
| `tool_call_id` | String | NULLABLE | Reference to tool call being responded to |
| `created_at` | DateTime | DEFAULT UTC now | |

---

## API Specifications

### REST Endpoints

| Method | Endpoint | Purpose | Request | Response |
|--------|----------|---------|---------|----------|
| GET | `/categories` | List subscribed categories | — | `[CategoryResponse]` |
| POST | `/categories` | Subscribe to arXiv category | `{arxiv_code, description?}` | `CategoryResponse` (201) |
| DELETE | `/categories/{id}` | Unsubscribe from category | Path: id | 204 |
| GET | `/papers` | List papers (filter by category/status) | Query: `category_id?`, `status?` | `[PaperResponse]` |
| GET | `/papers/{id}/analysis` | Get analysis for a paper | Path: id | `AnalysisResponse` / 404 |
| GET | `/daily-digest` | Last 24h papers ranked by novelty | — | `[DigestItem]` |
| POST | `/process` | Manual trigger: poll + process | — | `{new_papers_found, papers_processed}` |
| GET | `/last-updated` | Timestamp of most recent analysis | — | `{last_updated: ISO8601}` |
| GET | `/conversations` | List all conversations | — | `[Conversation]` |
| POST | `/conversations` | Create new chat | `{title?, research_interest?}` | `{id, title, research_interest}` (201) |
| GET | `/conversations/{id}/messages` | Load chat history | Path: id | `[Message]` / 404 |
| DELETE | `/conversations/{id}` | Delete conversation | Path: id | 204 |
| PUT | `/conversations/{id}/research-interest` | Update research interest | `{research_interest}` | `{ok: true}` |
| POST | `/chat` | Send message (SSE stream) | `ChatRequest` | SSE StreamingResponse |

### SSE Streaming Protocol (`POST /chat`)

| Event Type | Fields | Description |
|-----------|--------|-------------|
| `meta` | `conversation_id` | First event — identifies or creates conversation |
| `tool` | `name` | Tool being executed (e.g., "search_papers") |
| `text` | `content` | Streamed text chunk of assistant response |
| `[DONE]` | — | End-of-stream marker |

### UI Routes (Server-Rendered)

| Method | Path | Template | Purpose |
|--------|------|----------|---------|
| GET | `/ui` | `digest.html` | Daily digest — papers ranked by novelty score |
| POST | `/ui/refresh` | — | Manual refresh, redirect to `/ui` |
| GET | `/ui/categories` | `categories.html` | Manage arXiv category subscriptions |
| POST | `/ui/categories/add` | — | Add category via form |
| POST | `/ui/categories/{id}/delete` | — | Remove category |
| GET | `/ui/paper/{id}` | `paper.html` | Full paper detail: analysis, contributions, full text |
| GET | `/ui/chat` | `chat.html` | Chat interface (new conversation) |
| GET | `/ui/chat/{id}` | `chat.html` | Chat with existing conversation |

### Chat Agent Tools (Azure OpenAI Function-Calling)

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `get_daily_digest` | — | Last 24h papers ranked by novelty | Today's highlights |
| `search_papers` | `query: str` | Papers matching keyword across titles, abstracts, analyses | Find specific work |
| `get_paper_detail` | `paper_id: int` | Full analysis + text excerpt | Deep-dive into a paper |
| `compare_papers` | `paper_ids: list[int]` | Side-by-side comparison of methodology, contributions | Compare approaches |
| `list_categories` | — | All subscriptions | See what you're tracking |
| `add_category` | `arxiv_code: str` | Subscribe to new category | Expand interests |
| `remove_category` | `category_id: int` | Unsubscribe | Narrow focus |

### MCP Tools (Model Context Protocol)

| Tool | Parameters | Returns |
|------|-----------|---------|
| `get_daily_digest` | — | Formatted markdown of today's top papers |
| `search_papers` | `query: str` | Search results across papers |
| `get_paper_analysis` | `paper_id: int` | Full analysis + abstract |
| `add_category` | `arxiv_code: str` | Subscribe confirmation |
| `list_categories` | — | All subscriptions |

---

## Project Structure

```
ai-research-paper-digest/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + lifespan (DB, scheduler, MCP)
│   ├── config.py               # Settings via pydantic-settings (.env)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy models: Category, Paper, Analysis, Conversation, Message
│   │   ├── database.py         # Async engine + session factory (Azure SSL handling)
│   │   └── crud.py             # All database operations
│   ├── services/
│   │   ├── __init__.py
│   │   ├── arxiv_feed.py       # arXiv RSS polling + arxiv lib metadata fetch
│   │   ├── pdf.py              # PDF download → blob upload → text extraction → cleanup
│   │   ├── analyzer.py         # Azure OpenAI GPT-4o structured analysis (JSON mode)
│   │   ├── pipeline.py         # Orchestrator: download → extract → analyze → store
│   │   └── chat.py             # Chat agent: Azure OpenAI tool-calling + SSE streaming
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py           # REST + Chat SSE endpoints
│   │   └── schemas.py          # Pydantic request/response models
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py           # FastMCP tools for AI assistant integration
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py             # APScheduler job: poll + process every 6h
│   └── ui/
│       ├── views.py            # Server-rendered routes (Jinja2)
│       ├── static/
│       │   ├── chat.js         # Chat client: SSE, markdown, tool status
│       │   └── style.css       # Dark theme, responsive, animations
│       └── templates/
│           ├── base.html       # Layout: nav, sidebar, content block
│           ├── digest.html     # Daily digest: scored paper cards
│           ├── categories.html # Category subscription management
│           ├── paper.html      # Full paper detail: analysis, contributions, text
│           └── chat.html       # Chat UI: sidebar, messages, research interest
├── data/                       # Temporary PDF downloads (gitignored)
├── categories.yaml             # Seed arXiv category subscriptions
├── requirements.txt
├── Dockerfile
└── README.md
```

### Module Responsibility Map

| Module | Responsibility | Dependencies | Parallel to Podcast Project |
|--------|---------------|-------------|----------------------------|
| `arxiv_feed.py` | Poll arXiv RSS, fetch metadata via `arxiv` lib, detect new papers by arXiv ID | `feedparser`, `arxiv`, `crud` | `rss.py` |
| `pdf.py` | Download PDF, upload to blob, extract text with PyMuPDF, cleanup | `arxiv`, `pymupdf`, `azure-storage-blob` | `audio.py` + `transcription.py` |
| `analyzer.py` | Send extracted text to Azure OpenAI GPT-4o for structured JSON analysis | `openai` (Azure) | `summarizer.py` |
| `pipeline.py` | Chain download → extract → analyze per paper, manage state transitions | All services, `crud` | `pipeline.py` |
| `chat.py` | Multi-round tool-calling chat agent, SSE streaming | `openai` (Azure), `crud` | `chat.py` |
| `jobs.py` | APScheduler: poll + process every 6h | `arxiv_feed`, `pipeline` | `jobs.py` |
| `server.py` (MCP) | FastMCP tools for external AI assistants | `crud` | `server.py` |
| `crud.py` | All async database operations | SQLAlchemy | `crud.py` |
| `models.py` | 5 SQLAlchemy ORM models | SQLAlchemy | `models.py` |
| `routes.py` | 14 REST endpoints + SSE chat | FastAPI, services | `routes.py` |
| `views.py` | 8 server-rendered HTML routes | Jinja2, `crud` | `views.py` |

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | Yes | — | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | No | `gpt-4o` | Azure OpenAI model deployment name |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://localhost:5432/paper_digest` | PostgreSQL async URL |
| `AZURE_BLOB_CONNECTION_STRING` | Yes | — | Azure Storage connection string |
| `AZURE_BLOB_CONTAINER_NAME` | No | `paper-pdfs` | Blob container name |
| `POLL_INTERVAL_HOURS` | No | `6` | Scheduler interval |
| `CATEGORIES_FILE` | No | `categories.yaml` | Seed categories file |

### Seed Categories File

```yaml
# categories.yaml
categories:
  - name: "Artificial Intelligence"
    arxiv_code: "cs.AI"

  - name: "Machine Learning"
    arxiv_code: "cs.LG"

  - name: "Computation and Language (NLP)"
    arxiv_code: "cs.CL"

  - name: "Computer Vision"
    arxiv_code: "cs.CV"

  - name: "Machine Learning (Stats)"
    arxiv_code: "stat.ML"
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

# No ffmpeg needed — PDF extraction is pure Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY categories.yaml .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Key difference from podcast project**: No `ffmpeg` system dependency needed. PyMuPDF handles PDF extraction natively.

---

## Dependencies

```
# requirements.txt
fastapi[standard]>=0.115.0
uvicorn[standard]>=0.30.0
jinja2>=3.1.0

# Database
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.30.0
alembic>=1.14.0

# AI
openai>=1.40.0

# arXiv
arxiv>=2.4.0
feedparser>=6.0.0

# PDF text extraction
pymupdf>=1.24.0

# HTTP
httpx>=0.27.0

# Azure
azure-storage-blob>=12.20.0
aiohttp>=3.9.0

# Configuration
pydantic-settings>=2.5.0
python-dotenv>=1.0.0
pyyaml>=6.0.0

# Scheduling
apscheduler>=3.10.0

# MCP
fastmcp>=2.0.0
```

**Compared to podcast project**: Replaces `pydub` (audio) with `pymupdf` (PDF). Adds `arxiv` library. Removes ffmpeg dependency entirely.

---

## Behaviors & Edge Cases

### arXiv Polling

- **RSS feed timing**: arXiv RSS feeds update daily at midnight EST. Polling every 6h means we'll catch new papers within 6 hours of the daily update.
- **Multi-category papers**: A paper can appear in multiple category feeds (e.g., cs.AI + cs.LG). arXiv ID-based dedup prevents duplicating it. The paper is associated with whichever category feed discovers it first.
- **arXiv ID as dedup key**: Every arXiv paper has a unique identifier (e.g., `2403.12345v1`). We store this and check it before inserting, same pattern as GUID dedup in the podcast project.
- **Immediate poll on add**: When a category is added (via API or UI), `poll_category()` runs immediately followed by `process_pending_papers()` in a FastAPI `BackgroundTask`.
- **categories.yaml sync**: On each scheduler run, entries are synced into the DB (inserts only). Categories added via UI/API persist regardless.
- **Rate limiting**: The `arxiv` Python library has built-in rate limiting (3-second delay between API calls by default). We rely on this rather than implementing our own.

### PDF Processing

- **Text extraction quality**: PyMuPDF handles most standard academic PDFs well. Multi-column layouts, equations rendered as images, and heavily-formatted tables may lose fidelity. We store the raw extracted text regardless.
- **PDF size**: Most arXiv papers are 1–5 MB. The occasional supplementary-heavy paper can be 50+ MB. Azure Blob staging prevents disk exhaustion on B1 (1 GB limit).
- **Extraction failures**: Some arXiv papers are scanned images (rare for CS). PyMuPDF will extract empty or garbled text. The analyzer will still process it — the analysis will reflect "limited text extracted" and score accordingly.
- **LaTeX in text**: Extracted text will contain raw LaTeX fragments for equations. The LLM handles this well — Llama 3.3 can interpret common LaTeX math notation.

### Analysis

- **Truncation**: Papers with extracted text >120k characters (~30k tokens) are truncated before analysis. This primarily affects papers with very long appendices. Full text is still stored in the DB.
- **Score rubric**: The analyzer prompt includes a detailed 1–10 rubric emphasizing novelty and potential impact, not just quality of writing.
- **JSON validation**: The LLM response is validated for required keys. If parsing fails, retry with backoff (3 attempts, 2s/4s/8s).
- **Full text vs. abstract-only**: We analyze the full paper text, not just the abstract. This gives much richer summaries and methodology extraction compared to abstract-only analysis services.

### Chat Agent

- **Tool loop cap**: Maximum 5 tool-calling rounds per message. Most queries need 1–2 rounds.
- **Auto-titling**: First user message generates a conversation title.
- **Research interest personalization**: Each conversation can have a research interest (e.g., "efficient inference for LLMs"). The agent computes a per-paper relevance score alongside the static novelty score.
- **`compare_papers` tool**: Unique to this project — fetches multiple analyses and generates a structured comparison. Useful for literature-review-style queries.

### Scheduler

- **In-process**: APScheduler runs inside FastAPI. Same trade-off as the podcast project — zero infrastructure overhead, but no distributed locking.
- **Sequential processing**: Papers processed one at a time to manage API costs and rate limits.

---

## Tradeoffs

### Full-Text Extraction vs. Abstract-Only

**Chose**: Download PDF and extract full text for analysis.

**Why**: Abstracts are typically 150–250 words. A full paper is 4,000–10,000 words. Analyzing the full text yields far richer summaries — methodology details, experimental results, specific architectural choices, and limitation discussion are only available in the body. This is the main differentiator vs. existing abstract-summarization tools.

**Downside**: PDF download + extraction adds latency (~5–10s per paper). Text extraction is imperfect for image-heavy or scanned papers. More tokens consumed per Groq API call. For a 50-paper daily batch, total processing time is ~30–60 minutes.

### PyMuPDF vs. GROBID/SciPDF vs. Marker

**Chose**: PyMuPDF (`pymupdf`) for text extraction.

**Why**: Pure Python, no external service dependency, fast (<1s per paper), handles 95%+ of standard arXiv PDFs. No Docker sidecar or API call needed.

**Alternatives considered**:
- **GROBID**: Better structured extraction (sections, references, figures). But requires a separate Java service — adds infrastructure complexity for a single-user tool.
- **Marker**: Better LaTeX reconstruction. But heavier dependency, slower, and overkill when the LLM handles LaTeX fragments well.
- **pypdf**: Simpler but worse extraction quality than PyMuPDF for academic papers.

### arXiv RSS + Python Library vs. API-Only

**Chose**: RSS feeds for daily discovery + `arxiv` Python library for metadata enrichment.

**Why**: RSS feeds give us the daily new-paper listing per category efficiently (one HTTP request per category). The `arxiv` library provides richer metadata (authors, all categories, journal refs) and PDF download helpers. Using both avoids hammering the search API for discovery while still getting complete metadata.

**Downside**: Two data sources to coordinate. RSS may occasionally lag behind the arXiv API by a few hours.

### Single-Provider AI (Azure OpenAI / AI Foundry)

**Chose**: Azure OpenAI GPT-4o for all LLM tasks (analysis + chat).

**Why**: One API key, Azure credits cover usage. GPT-4o handles academic text well, supports JSON mode and tool calling natively. 128k token context window fits full papers without truncation.

**Downside**: Single point of failure. No fallback. Costs scale with usage (pay-per-token). Requires Azure subscription.

### Azure Blob as PDF Staging — Same as Podcast Project

**Chose**: Upload PDF to blob, extract text, delete.

**Why**: Same B1 disk constraint (1 GB). Papers are smaller than podcasts (1–5 MB vs. 50–100 MB) but can accumulate if processing falls behind.

### No Authentication — Same as Podcast Project

**Chose**: Single-user, no login.

**Why**: Personal research tool. Same trade-off as podcast project.

### In-Process Scheduler — Same as Podcast Project

**Chose**: APScheduler inside FastAPI.

**Why**: Zero infrastructure overhead. Same trade-off.

---

## Comparison: Podcast Assistant → Paper Digest

| Aspect | Podcast Assistant | Paper Digest |
|--------|------------------|-------------|
| **Source** | Podcast RSS feeds | arXiv RSS feeds + `arxiv` library |
| **Content** | Audio files (50–100 MB) | PDF files (1–5 MB) |
| **Extraction** | Groq Whisper (audio → text) | PyMuPDF (PDF → text) |
| **Chunking** | pydub ≤25 MB audio segments | Not needed — text fits in one LLM call |
| **System dependency** | ffmpeg | None |
| **AI Analysis** | Groq Llama 3.3 (summary, topics, score) | Azure OpenAI GPT-4o (summary, contributions, methodology, score) |
| **Scoring** | Listen-worthiness (1–10) | Novelty (1–10) |
| **Chat dual scoring** | Listen score + relevance to objective | Novelty score + relevance to research interest |
| **Dedup key** | RSS GUID | arXiv ID |
| **Unique chat tool** | — | `compare_papers` (side-by-side methodology comparison) |
| **Processing time/item** | 2–3 min (audio transcription bottleneck) | 10–20s (PDF extraction is fast, one LLM call) |
| **Daily volume** | 5–15 episodes | 20–100+ papers (depending on categories) |

---

## Deployment

### Azure Resources

| Resource | Name | SKU |
|----------|------|-----|
| Resource Group | `rg-paper-digest` | — |
| Azure OpenAI (AI Foundry) | `paperdigest-ai` | S0 (GPT-4o deployment) |
| PostgreSQL Flexible Server | `paperdigest-db` | B1ms |
| Storage Account | `paperdigeststor` | Standard LRS |
| Container Registry | `paperdigestacr` | Basic |
| App Service Plan | Linux | B1 |
| Web App | `paperdigest-app` | — |

### Build & Deploy

```bash
# Build and push to ACR
az acr build \
  --registry paperdigestacr \
  --image paper-digest:v1 \
  --file Dockerfile .

# Restart the app
az webapp restart \
  --name paper-digest-app \
  --resource-group rg-paper-digest
```

---

## Analyzer Prompt (Structured JSON Output)

```
You are an expert academic paper analyst. Given the full text of a research paper, produce a structured JSON analysis.

Scoring rubric for novelty_score (1-10):
- 1-3: Incremental. Minor extensions of known methods. Limited new insight.
- 4-5: Solid. Useful engineering contribution or thorough evaluation. Standard methodology.
- 6-7: Significant. Novel approach, strong experimental results, or meaningful theoretical contribution.
- 8-9: Highly novel. Potential to shift research direction. New paradigm, surprising results, or major capability leap.
- 10: Landmark. Fundamentally redefines the field. Rare — reserve for truly exceptional work.

Output JSON with exactly these keys:
{
  "summary": "3-5 sentence plain-English summary of what the paper does, its core idea, and main result",
  "key_contributions": ["contribution 1", "contribution 2", ...],  // 2-5 items
  "methodology": "Description of the approach, architecture, training procedure, or proof technique",
  "limitations": "Key limitations, assumptions, or scope constraints acknowledged or apparent",
  "keywords": ["keyword1", "keyword2", ...],  // 3-8 relevant terms
  "novelty_score": 7  // integer 1-10
}
```

---

## Chat System Prompt (Dynamic)

```
You are a research paper analyst assistant. You help researchers explore, compare, and understand papers from their arXiv subscriptions.

Your subscribed categories: {categories_list}

You MUST use tools to ground your answers in actual paper data. Do not speculate about papers — search and retrieve first.

When recommending papers:
- Show both **novelty_score** (from analysis) and **relevance_score** (your assessment, 1-10, based on the user's research interest)
- Format as cards with: Title (bold), Authors, Score badges, Key contribution, Link

{if research_interest}
The user's research interest: "{research_interest}"
Prioritize and frame all recommendations through this lens. Compute relevance_score based on how directly the paper relates to this interest.
{endif}

Available tools: get_daily_digest, search_papers, get_paper_detail, compare_papers, list_categories, add_category, remove_category
```

---

## Implementation Order

| Phase | Tasks | Estimate |
|-------|-------|----------|
| **Phase 1: Core Pipeline** | Config, DB models, arXiv polling, PDF download + extraction, Llama analysis, pipeline orchestrator | Foundation |
| **Phase 2: API + UI** | REST endpoints, schemas, digest page, categories page, paper detail page | User-facing |
| **Phase 3: Chat Agent** | Chat service with tool-calling, SSE streaming, conversation persistence, chat UI | Interactive |
| **Phase 4: MCP + Polish** | MCP server, scheduler, Dockerfile, Azure deployment | Integration |

---

*Document Status: Draft — Ready for implementation planning*
