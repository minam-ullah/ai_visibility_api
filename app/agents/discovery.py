from app.agents.base import BaseAgent

SYSTEM_PROMPT = """You are a Query Discovery Agent inside an AI-visibility research \
platform. Your sole job is to generate realistic, natural-language questions that \
real buyers type into AI assistants (ChatGPT, Claude, Perplexity) when researching \
products or services in a given competitive space.

Rules:
- Generate between 10 and 20 questions.
- Questions must be commercially relevant to someone evaluating or comparing \
products/services in the given industry -- not generic trivia.
- Cover a MIX of intents: informational ("how do I..."), comparison \
("X vs Y"), best-of ("what is the best..."), and transactional/evaluative \
("is X worth it", "does X do..."). Aim for roughly: 30% informational, \
30% comparison, 25% best-of, 15% transactional.
- Use natural phrasing a real person would type, not SEO keyword strings.
- Do not mention the target company by name in every query -- most real \
searches are category-level, not brand-level.
- Never invent statistics or claims; you are only generating QUESTIONS, not answers.

Output STRICT JSON only, matching exactly this schema, with no prose before or after:
{
  "queries": [
    {"query_text": "string", "intent": "informational|comparison|best_of|transactional"}
  ]
}
"""

USER_PROMPT_TEMPLATE = """Business profile:
- Name: {name}
- Domain: {domain}
- Industry: {industry}
- Description: {description}
- Known competitors: {competitors}

Generate 10-20 realistic questions people in this industry ask AI assistants when \
researching products/services like this one. Return JSON only, per the schema."""


class QueryDiscoveryAgent(BaseAgent):
    """Agent 1: given a business profile, discovers the questions buyers ask
    AI assistants in that competitive space."""

    def run(self, profile) -> tuple[list[dict], int]:
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description or "N/A",
            competitors=", ".join(profile.competitors or []) or "none listed",
        )
        result = self.ask(SYSTEM_PROMPT, user_prompt, max_tokens=2500)
        raw_queries = self._validate(result.data)
        return raw_queries, result.tokens_used

    @staticmethod
    def _validate(data) -> list[dict]:
        """Defensive parsing: tolerate a bare list, a dict without the
        'queries' key, missing 'intent' fields, or a handful of malformed
        entries -- but never let one bad item kill the whole batch."""
        if isinstance(data, dict):
            items = data.get("queries", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []

        cleaned = []
        for item in items:
            if isinstance(item, str):
                cleaned.append({"query_text": item.strip(), "intent": "informational"})
                continue
            if not isinstance(item, dict):
                continue
            text = (item.get("query_text") or item.get("query") or "").strip()
            if not text:
                continue
            intent = item.get("intent", "informational")
            if intent not in ("informational", "comparison", "best_of", "transactional"):
                intent = "informational"
            cleaned.append({"query_text": text, "intent": intent})

        return cleaned[:20]
