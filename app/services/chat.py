import json
import logging
from collections.abc import AsyncGenerator

from openai import AsyncAzureOpenAI

from app.config import settings
from app.db import crud
from app.db.models import MessageRole

logger = logging.getLogger(__name__)

MODEL = None  # uses settings.azure_openai_deployment
MAX_TOOL_ROUNDS = 5

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_daily_digest",
            "description": "Get today's paper digest — papers from the last 24 hours ranked by novelty score.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": "Search papers by keyword across titles, abstracts, summaries, and keywords.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_paper_detail",
            "description": "Get the full analysis and abstract for a specific paper by ID.",
            "parameters": {
                "type": "object",
                "properties": {"paper_id": {"type": "integer", "description": "Paper ID"}},
                "required": ["paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_papers",
            "description": "Compare two or more papers side-by-side on methodology, contributions, and novelty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of paper IDs to compare",
                    }
                },
                "required": ["paper_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "List all subscribed arXiv categories.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_category",
            "description": "Subscribe to a new arXiv category (e.g., cs.AI, cs.LG, stat.ML).",
            "parameters": {
                "type": "object",
                "properties": {"arxiv_code": {"type": "string", "description": "arXiv category code"}},
                "required": ["arxiv_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_category",
            "description": "Unsubscribe from an arXiv category by its database ID.",
            "parameters": {
                "type": "object",
                "properties": {"category_id": {"type": "integer", "description": "Category ID"}},
                "required": ["category_id"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _exec_tool(name: str, args: dict) -> str:
    logger.info("Executing tool '%s' with args: %s", name, args)
    if name == "get_daily_digest":
        papers = await crud.get_daily_digest()
        if not papers:
            return "No new papers in the last 24 hours."
        lines = []
        for p in papers:
            a = p.analysis
            lines.append(
                f"[ID:{p.id}] **{p.title}** — Score: {a.novelty_score}/10\n"
                f"  Authors: {', '.join(p.authors[:3])}\n"
                f"  Summary: {a.summary[:200]}\n"
                f"  Keywords: {', '.join(a.keywords)}"
            )
        return "\n\n".join(lines)

    if name == "search_papers":
        papers = await crud.search_papers(args["query"])
        if not papers:
            return f"No papers found matching '{args['query']}'."
        lines = []
        for p in papers[:10]:
            a = p.analysis
            lines.append(
                f"[ID:{p.id}] **{p.title}** — Score: {a.novelty_score}/10\n"
                f"  Keywords: {', '.join(a.keywords)}"
            )
        return "\n\n".join(lines)

    if name == "get_paper_detail":
        paper = await crud.get_paper(args["paper_id"])
        if not paper or not paper.analysis:
            return f"Paper {args['paper_id']} not found or not yet analysed."
        a = paper.analysis
        return (
            f"**{paper.title}**\n"
            f"Authors: {', '.join(paper.authors)}\n"
            f"Published: {paper.published_at.strftime('%Y-%m-%d')}\n"
            f"Categories: {', '.join(paper.categories)}\n"
            f"Novelty Score: {a.novelty_score}/10\n\n"
            f"**Summary**: {a.summary}\n\n"
            f"**Key Contributions**:\n" + "\n".join(f"- {c}" for c in a.key_contributions) + "\n\n"
            f"**Methodology**: {a.methodology}\n\n"
            f"**Limitations**: {a.limitations or 'Not specified'}\n\n"
            f"**Abstract**: {paper.abstract[:3000]}"
        )

    if name == "compare_papers":
        ids = args["paper_ids"]
        papers = [await crud.get_paper(pid) for pid in ids]
        parts = []
        for p in papers:
            if not p or not p.analysis:
                continue
            a = p.analysis
            parts.append(
                f"--- Paper ID:{p.id} ---\n"
                f"Title: {p.title}\n"
                f"Score: {a.novelty_score}/10\n"
                f"Contributions: {'; '.join(a.key_contributions)}\n"
                f"Methodology: {a.methodology[:500]}\n"
                f"Keywords: {', '.join(a.keywords)}"
            )
        return "\n\n".join(parts) if parts else "No valid papers found."

    if name == "list_categories":
        cats = await crud.get_all_categories()
        if not cats:
            return "No categories subscribed."
        return "\n".join(f"[ID:{c.id}] {c.name} ({c.arxiv_code})" for c in cats)

    if name == "add_category":
        code = args["arxiv_code"]
        existing = await crud.get_category_by_code(code)
        if existing:
            return f"Already subscribed to {code}."
        await crud.create_category(name=code, arxiv_code=code)
        return f"Subscribed to {code}."

    if name == "remove_category":
        await crud.delete_category(args["category_id"])
        return "Category removed."

    logger.warning("Unknown tool requested: %s", name)
    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(research_interest: str | None, categories: list) -> str:
    base = (
        "You are a research paper analyst assistant. You help researchers explore, "
        "compare, and understand papers from their arXiv subscriptions.\n\n"
        "CRITICAL RULES:\n"
        "1. ALWAYS call tools before answering. NEVER answer from your general knowledge.\n"
        "2. For ANY question about papers, research, or innovations: call search_papers or get_daily_digest FIRST.\n"
        "3. Only discuss papers returned by the tools. If tools return no results, say so.\n"
        "4. Do NOT say you lack access to papers — you have tools. USE THEM.\n\n"
        "When recommending papers:\n"
        "- Show both **novelty_score** (from analysis) and **relevance_score** "
        "(your assessment, 1-10, based on the user's research interest)\n"
        "- Format as cards with: Title (bold), Authors, Score badges, Key contribution, arXiv link\n\n"
        "Respond in Markdown.\n"
    )
    if categories:
        base += "\nSubscribed categories: " + ", ".join(c.arxiv_code for c in categories)
    if research_interest:
        base += (
            f"\n\nThe user's research interest: \"{research_interest}\"\n"
            "Prioritize and frame all recommendations through this lens. "
            "Compute relevance_score based on how directly the paper relates."
        )
    return base


def _db_messages_to_openai(messages: list) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        msg: dict = {"role": m.role.value}
        if m.content:
            msg["content"] = m.content
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
            msg.pop("content", None)
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        out.append(msg)
    return out


# ---------------------------------------------------------------------------
# Chat stream (SSE)
# ---------------------------------------------------------------------------

async def chat_stream(conversation_id: int, user_message: str) -> AsyncGenerator[str, None]:
    logger.info("Chat stream started — conv=%d, message_len=%d", conversation_id, len(user_message))
    conv = await crud.get_conversation(conversation_id)
    if not conv:
        logger.warning("Conversation %d not found", conversation_id)
        yield json.dumps({"type": "error", "content": "Conversation not found"})
        return

    await crud.add_message(conversation_id, MessageRole.user, content=user_message)

    # Auto-title from first message
    msgs = await crud.get_conversation_messages(conversation_id)
    user_msgs = [m for m in msgs if m.role == MessageRole.user]
    if len(user_msgs) == 1:
        title = user_message[:60] + ("…" if len(user_message) > 60 else "")
        await crud.update_conversation_title(conversation_id, title)

    categories = await crud.get_all_categories()
    system_prompt = _build_system_prompt(conv.research_interest, categories)

    history = [{"role": "system", "content": system_prompt}]
    history.extend(_db_messages_to_openai(msgs))

    client = AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
    model = settings.azure_openai_deployment

    # Tool loop
    for round_num in range(MAX_TOOL_ROUNDS):
        logger.debug("Tool round %d/%d — sending %d messages to model", round_num + 1, MAX_TOOL_ROUNDS, len(history))
        try:
            resp = await client.chat.completions.create(
                model=model, messages=history, tools=TOOLS, temperature=0.4
            )
        except Exception:
            logger.exception("Azure OpenAI API call failed in tool round %d", round_num + 1)
            yield json.dumps({"type": "error", "content": "AI service error — please retry."})
            return
        choice = resp.choices[0]
        logger.debug("Model finish_reason=%s, tool_calls=%s", choice.finish_reason, bool(choice.message.tool_calls))

        if choice.finish_reason == "tool_calls" or choice.message.tool_calls:
            tc_list = choice.message.tool_calls
            # Save assistant tool-call message
            tc_data = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tc_list
            ]
            await crud.add_message(conversation_id, MessageRole.assistant, tool_calls=tc_data)
            history.append({"role": "assistant", "tool_calls": tc_data})

            logger.info("Model requested %d tool call(s) in round %d", len(tc_list), round_num + 1)
            for tc in tc_list:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                yield json.dumps({"type": "tool", "name": name})
                try:
                    result = await _exec_tool(name, args)
                except Exception:
                    logger.exception("Tool '%s' execution failed", name)
                    result = f"Error executing {name} — tool failed."
                await crud.add_message(
                    conversation_id, MessageRole.tool, content=result, tool_call_id=tc.id
                )
                history.append({"role": "tool", "content": result, "tool_call_id": tc.id})
        else:
            break

    # Final streaming response
    logger.info("Starting final streaming response for conv=%d", conversation_id)
    try:
        stream = await client.chat.completions.create(
            model=model, messages=history, stream=True, tools=TOOLS, tool_choice="none"
        )
        full_response = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                full_response += delta.content
                yield json.dumps({"type": "text", "content": delta.content})

        await crud.add_message(conversation_id, MessageRole.assistant, content=full_response)
        logger.info("Chat complete — conv=%d, response_len=%d", conversation_id, len(full_response))
    except Exception:
        logger.exception("Streaming response failed for conv=%d", conversation_id)
        yield json.dumps({"type": "error", "content": "Streaming failed — please retry."})
