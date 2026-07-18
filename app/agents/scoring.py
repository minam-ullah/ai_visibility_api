from app.agents.base import BaseAgent
from app.services import search_data
from app.utils.scoring import compute_opportunity_score

SYSTEM_PROMPT = """You are a Visibility Scoring Agent inside an AI-visibility research \
platform. Given one search query and a target domain, your job is to simulate what a \
knowledgeable, well-informed AI assistant (like ChatGPT or Claude) would say if asked \
that exact question today, and determine whether the target domain would plausibly be \
mentioned in that answer.

Reason step by step about who the real, well-known players are in this space for this \
specific query, then decide:
- Would the target domain realistically be named or recommended in a good-faith answer?
- If yes, roughly where would it rank among the domains mentioned (1 = mentioned first/most \
prominently)?

Be honest and skeptical -- do NOT assume the target domain is visible just because it was \
supplied to you. Most domains are NOT visible for most queries; only mark a domain visible \
if there is a genuine, specific reason a well-informed model would surface it (e.g. it is \
a category leader, or one of the named competitors is itself the target).

Output STRICT JSON only, matching exactly this schema, no prose before or after:
{
  "domain_visible": true|false,
  "visibility_position": integer or null,
  "reasoning": "one sentence"
}
"""

USER_PROMPT_TEMPLATE = """Query: "{query_text}"
Target domain: {domain}
Target company: {name} ({industry})
Known competitors in this space: {competitors}

Simulate the AI-generated answer for this query and assess the target domain's \
visibility in it. Return JSON only, per the schema."""


class VisibilityScoringAgent(BaseAgent):
    """Agent 2: for a single query, gets real keyword metrics (search volume,
    competitive difficulty) and simulates whether the target domain would
    appear in an AI-generated answer, then computes the opportunity score."""

    def run(self, profile, query_text: str, intent: str = "informational") -> tuple[dict, int]:
        metrics = search_data.get_keyword_metrics(query_text)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            query_text=query_text,
            domain=profile.domain,
            name=profile.name,
            industry=profile.industry,
            competitors=", ".join(profile.competitors or []) or "none listed",
        )
        result = self.ask(SYSTEM_PROMPT, user_prompt, max_tokens=500)
        visibility = self._validate(result.data)

        opportunity_score = compute_opportunity_score(
            search_volume=metrics.search_volume,
            competitive_difficulty=metrics.competitive_difficulty,
            domain_visible=visibility["domain_visible"],
            intent=intent,
        )

        scored = {
            "estimated_search_volume": metrics.search_volume,
            "competitive_difficulty": metrics.competitive_difficulty,
            "domain_visible": visibility["domain_visible"],
            "visibility_position": visibility["visibility_position"],
            "visibility_status": "visible" if visibility["domain_visible"] else "not_visible",
            "opportunity_score": opportunity_score,
            "data_source": metrics.source,
        }
        return scored, result.tokens_used

    @staticmethod
    def _validate(data) -> dict:
        if not isinstance(data, dict):
            data = {}
        domain_visible = bool(data.get("domain_visible", False))
        position = data.get("visibility_position")
        try:
            position = int(position) if domain_visible and position is not None else None
        except (TypeError, ValueError):
            position = None
        return {"domain_visible": domain_visible, "visibility_position": position}
