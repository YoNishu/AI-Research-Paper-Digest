# AI Research Paper Digest

An AI-powered research assistant that automatically tracks arXiv papers, analyzes them with GPT-4o, and lets you explore your paper library through a conversational chat interface.

## What It Does

- **Auto-fetches papers** from arXiv RSS feeds every 6 hours across your subscribed categories (cs.AI, cs.LG, cs.CL, cs.CV, stat.ML, etc.)
- **Downloads & analyzes full PDFs** — extracts text via PyMuPDF, then GPT-4o generates a structured analysis: summary, key contributions, methodology, limitations, keywords, and a novelty score (1–10)
- **Daily digest** — shows the latest papers ranked by novelty so you see what matters first
- **Browse & search** — full archive with keyword search, category filters, score filters, and sorting
- **Chat with your papers** — ask questions in natural language; the AI calls tools to search, retrieve, and compare papers from your database before answering
- **MCP server** — exposes paper tools to external AI agents (Claude, Copilot, etc.) via Model Context Protocol

## Tech Stack

| | |
|---|---|
| **Backend** | Python 3.11, FastAPI, SQLAlchemy 2.0 (async), asyncpg |
| **AI** | Azure OpenAI GPT-4o — JSON mode for analysis, function calling for chat |
| **Database** | PostgreSQL 16 (Azure Flexible Server) |
| **PDF** | PyMuPDF for text extraction, Azure Blob Storage for staging |
| **Frontend** | Jinja2 templates, vanilla JS, SSE for real-time chat streaming |
| **Infra** | Docker, Azure Container Apps, ACR, managed identity |

## Architecture

```
arXiv RSS ──→ Poller ──→ Download PDF ──→ Extract Text ──→ GPT-4o ──→ PostgreSQL
                              │                              │
                         Blob Storage                  JSON analysis
                         (temp staging)              (summary, score,
                                                     contributions...)
                                                          │
                                           ┌──────────────┼──────────────┐
                                           │              │              │
                                        Web UI        REST API      MCP Server
                                     (Jinja2+SSE)    (FastAPI)     (FastMCP)
```

## Pages

| Page | What you see |
|---|---|
| **Digest** `/ui` | Today's papers ranked by novelty score |
| **Browse** `/ui/papers` | Full archive — search, filter by category/score, paginate |
| **Categories** `/ui/categories` | Add/remove arXiv category subscriptions |
| **Paper Detail** `/ui/paper/{id}` | Full AI analysis, abstract, metadata |
| **Chat** `/ui/chat` | Conversational AI — searches papers, compares them, answers questions |
| **API Docs** `/docs` | Auto-generated Swagger UI |

## Chat Tools

The chat assistant has 7 tools it can call before answering:

| Tool | What it does |
|---|---|
| `get_daily_digest` | Fetch recent papers ranked by score |
| `search_papers` | Full-text search across titles, abstracts, summaries, keywords |
| `get_paper_detail` | Get complete analysis for a specific paper |
| `compare_papers` | Side-by-side comparison of multiple papers |
| `list_categories` | Show subscribed arXiv categories |
| `add_category` | Subscribe to a new category |
| `remove_category` | Unsubscribe from a category |

## Quick Start

### Local

```bash
pip install -r requirements.txt
# Set env vars: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, DATABASE_URL, AZURE_BLOB_CONNECTION_STRING
uvicorn app.main:app --port 8000
```

### Azure (one-click)

```powershell
.\deploy.ps1
```

Creates all resources (PostgreSQL, Storage, OpenAI, Container Registry, Container App), builds the Docker image, and deploys.

### Tear down

```bash
az group delete --name rg-paper-digest --yes --no-wait
```

## Project Structure

```
app/
├── main.py              # FastAPI app, lifespan, router mounts
├── config.py            # Pydantic settings from env vars
├── api/
│   ├── routes.py        # REST endpoints (papers, categories, chat SSE)
│   └── schemas.py       # Pydantic request/response models
├── db/
│   ├── models.py        # SQLAlchemy models (Paper, Analysis, Conversation, Message)
│   ├── database.py      # Async engine + session factory
│   └── crud.py          # All database operations
├── services/
│   ├── arxiv_feed.py    # RSS polling + arXiv API metadata enrichment
│   ├── pipeline.py      # Download → extract → analyze → save
│   ├── analyzer.py      # GPT-4o structured analysis (JSON mode)
│   ├── pdf.py           # PDF download, text extraction, blob storage
│   └── chat.py          # Chat engine with tool-calling loop + SSE streaming
├── scheduler/
│   └── jobs.py          # APScheduler: poll every 6h + startup catch-up
├── mcp/
│   └── server.py        # MCP tools for external AI agents
└── ui/
    ├── views.py         # Jinja2 page routes
    ├── templates/       # HTML templates (base, digest, browse, chat, etc.)
    └── static/          # CSS + chat.js
```

## License

MIT
