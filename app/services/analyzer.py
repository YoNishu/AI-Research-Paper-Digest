import asyncio
import json
import logging

from openai import AsyncAzureOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 120_000
MAX_RETRIES = 3

SYSTEM_PROMPT = """You are an expert academic paper analyst. Given the full text of a research paper, produce a structured JSON analysis.

Scoring rubric for novelty_score (1-10):
- 1-3: Incremental. Minor extensions of known methods. Limited new insight.
- 4-5: Solid. Useful engineering contribution or thorough evaluation. Standard methodology.
- 6-7: Significant. Novel approach, strong experimental results, or meaningful theoretical contribution.
- 8-9: Highly novel. Potential to shift research direction. New paradigm, surprising results, or major capability leap.
- 10: Landmark. Fundamentally redefines the field. Rare — reserve for truly exceptional work.

You MUST output valid JSON with exactly these keys:
{
  "summary": "3-5 sentence plain-English summary of what the paper does, its core idea, and main result",
  "key_contributions": ["contribution 1", "contribution 2"],
  "methodology": "Description of the approach, architecture, training procedure, or proof technique",
  "limitations": "Key limitations, assumptions, or scope constraints acknowledged or apparent",
  "keywords": ["keyword1", "keyword2"],
  "novelty_score": 7
}
"""


def _get_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


async def analyze_paper(full_text: str, title: str = "", abstract: str = "") -> dict:
    truncated = full_text[:MAX_TEXT_CHARS]
    if len(full_text) > MAX_TEXT_CHARS:
        logger.warning("Truncated text from %d to %d chars", len(full_text), MAX_TEXT_CHARS)

    user_content = f"Paper title: {title}\n\nAbstract: {abstract}\n\nFull text:\n{truncated}"

    client = _get_client()
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=settings.azure_openai_deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = resp.choices[0].message.content
            data = json.loads(raw)

            required = {"summary", "key_contributions", "methodology", "keywords", "novelty_score"}
            if not required.issubset(data.keys()):
                raise ValueError(f"Missing keys: {required - data.keys()}")

            data["novelty_score"] = max(1, min(10, int(data["novelty_score"])))
            data.setdefault("limitations", None)
            logger.info("Analysis complete for '%s' — score %d", title[:60], data["novelty_score"])
            return data
        except Exception:
            wait = 2 ** (attempt + 1)
            logger.warning("Analysis attempt %d failed, retrying in %ds", attempt + 1, wait, exc_info=True)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait)

    raise RuntimeError(f"Analysis failed after {MAX_RETRIES} attempts for '{title}'")
