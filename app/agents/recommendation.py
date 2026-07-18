from app.agents.base import BaseAgent

SYSTEM_PROMPT = """You are a Content Recommendation Agent inside an AI-visibility research \
platform. You are given a list of high-opportunity queries where the target domain is \
currently NOT appearing in AI-generated answers. Your job is to recommend specific, \
actionable content the target company should create to close that gap.

Rules:
- Produce between 3 and 5 recommendations total across the whole list of queries (not \
per query) -- prioritise the highest-opportunity gaps.
- Each recommendation must target exactly one of the given queries (reference it by its \
query_id).
- content_type must be one of: blog_post, landing_page, faq, comparison_page.
- title must be a concrete, publishable content title, not a generic instruction.
- rationale must explain specifically why this content closes the gap for that query \
(1-2 sentences), referencing the query's intent or the competitive situation.
- target_keywords must be 3-6 specific keyword phrases the content should cover.
- priority must be high, medium, or low, based on the query's opportunity score \
(>=0.7 high, 0.4-0.7 medium, <0.4 low).

Output STRICT JSON only, matching exactly this schema, no prose before or after:
{
  "recommendations": [
    {
      "query_id": "string (matches the id given in the input)",
      "content_type": "blog_post|landing_page|faq|comparison_page",
      "title": "string",
      "rationale": "string",
      "target_keywords": ["string", "..."],
      "priority": "high|medium|low"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """Target company: {name} ({domain}), industry: {industry}

High-opportunity queries where {domain} is currently NOT visible (gaps to close):
{query_lines}

Generate 3-5 content recommendations per the schema, prioritising the highest-opportunity \
gaps first."""


class ContentRecommendationAgent(BaseAgent):
    """Agent 3: given the top opportunity-gap queries, generates concrete
    content recommendations to close them."""

    def run(self, profile, gap_queries: list) -> tuple[list[dict], int]:
        """gap_queries: list of DiscoveredQuery ORM objects (domain_visible=False),
        already sorted by opportunity_score descending and truncated by the caller."""
        if not gap_queries:
            return [], 0

        query_lines = "\n".join(
            f'- id="{q.uuid}" (score={q.opportunity_score:.2f}, intent={q.query_intent}): "{q.query_text}"'
            for q in gap_queries
        )
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            query_lines=query_lines,
        )
        result = self.ask(SYSTEM_PROMPT, user_prompt, max_tokens=2000)
        valid_ids = {q.uuid for q in gap_queries}
        recs = self._validate(result.data, valid_ids)
        return recs, result.tokens_used

    @staticmethod
    def _validate(data, valid_ids: set) -> list[dict]:
        if isinstance(data, dict):
            items = data.get("recommendations", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []

        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            query_id = item.get("query_id")
            if query_id not in valid_ids:
                continue  # never attach a recommendation to a query we didn't offer
            content_type = item.get("content_type")
            if content_type not in ("blog_post", "landing_page", "faq", "comparison_page"):
                content_type = "blog_post"
            title = (item.get("title") or "").strip()
            rationale = (item.get("rationale") or "").strip()
            if not title or not rationale:
                continue
            keywords = item.get("target_keywords") or []
            if not isinstance(keywords, list):
                keywords = []
            keywords = [str(k).strip() for k in keywords if str(k).strip()][:6]
            priority = item.get("priority")
            if priority not in ("high", "medium", "low"):
                priority = "medium"

            cleaned.append(
                {
                    "query_uuid": query_id,
                    "content_type": content_type,
                    "title": title,
                    "rationale": rationale,
                    "target_keywords": keywords,
                    "priority": priority,
                }
            )

        return cleaned[:5]
