from unittest.mock import patch

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.services.llm_client import LLMResult
from app.services.search_data import KeywordMetrics
from app.utils.scoring import compute_opportunity_score


class FakeLLMClient:
    """Drop-in replacement for LLMClient that returns a canned LLMResult."""

    def __init__(self, data, tokens=42):
        self._data = data
        self._tokens = tokens

    def complete_json(self, system, user, max_tokens=2000):
        return LLMResult(data=self._data, tokens_used=self._tokens)


# ---------------------------------------------------------------------------
# Agent 1: Query Discovery
# ---------------------------------------------------------------------------

def test_discovery_agent_parses_well_formed_response(app, profile):
    canned = {
        "queries": [
            {"query_text": "What is the best AI tool for SEO content briefs?", "intent": "best_of"},
            {"query_text": "Frase vs Surfer SEO, which is better?", "intent": "comparison"},
        ]
    }
    with app.app_context():
        agent = QueryDiscoveryAgent(llm_client=FakeLLMClient(canned))
        queries, tokens = agent.run(profile)

    assert len(queries) == 2
    assert queries[0]["intent"] == "best_of"
    assert tokens == 42


def test_discovery_agent_tolerates_malformed_items(app, profile):
    """A bad item (missing text, wrong shape) should be dropped, not crash the batch."""
    canned = {
        "queries": [
            {"query_text": "How do I speed up keyword research with AI?"},  # missing intent -> default
            {"not_query_text": "garbage"},  # dropped
            "just a bare string question",  # tolerated, becomes informational
            42,  # dropped
        ]
    }
    with app.app_context():
        agent = QueryDiscoveryAgent(llm_client=FakeLLMClient(canned))
        queries, _ = agent.run(profile)

    assert len(queries) == 2
    assert queries[0]["intent"] == "informational"
    assert queries[1]["query_text"] == "just a bare string question"


def test_discovery_agent_handles_totally_empty_response(app, profile):
    with app.app_context():
        agent = QueryDiscoveryAgent(llm_client=FakeLLMClient({}))
        queries, _ = agent.run(profile)
    assert queries == []


# ---------------------------------------------------------------------------
# Agent 2: Visibility Scoring
# ---------------------------------------------------------------------------

def test_scoring_agent_computes_score_when_not_visible(app, profile):
    canned = {"domain_visible": False, "visibility_position": None, "reasoning": "not a known player"}
    mock_metrics = KeywordMetrics(search_volume=1200, competitive_difficulty=62, source="mock")

    with app.app_context(), patch(
        "app.agents.scoring.search_data.get_keyword_metrics", return_value=mock_metrics
    ):
        agent = VisibilityScoringAgent(llm_client=FakeLLMClient(canned))
        scored, tokens = agent.run(profile, "What is the best AI content brief tool?", "best_of")

    assert scored["domain_visible"] is False
    assert scored["visibility_status"] == "not_visible"
    assert scored["estimated_search_volume"] == 1200
    assert 0.0 < scored["opportunity_score"] <= 1.0
    assert tokens == 42


def test_scoring_agent_forces_null_position_when_not_visible(app, profile):
    """Even if the LLM hallucinates a position while saying not visible, we ignore it."""
    canned = {"domain_visible": False, "visibility_position": 3}
    mock_metrics = KeywordMetrics(search_volume=500, competitive_difficulty=40, source="mock")

    with app.app_context(), patch(
        "app.agents.scoring.search_data.get_keyword_metrics", return_value=mock_metrics
    ):
        agent = VisibilityScoringAgent(llm_client=FakeLLMClient(canned))
        scored, _ = agent.run(profile, "some query", "informational")

    assert scored["visibility_position"] is None


# ---------------------------------------------------------------------------
# Agent 3: Content Recommendations
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, uuid, score, intent, text):
        self.uuid = uuid
        self.opportunity_score = score
        self.query_intent = intent
        self.query_text = text


def test_recommendation_agent_drops_recs_for_unknown_query_ids(app, profile):
    gap_queries = [_FakeQuery("q-1", 0.8, "best_of", "What is the best tool?")]
    canned = {
        "recommendations": [
            {
                "query_id": "q-1",
                "content_type": "blog_post",
                "title": "Best AI Content Brief Tools in 2026",
                "rationale": "Directly answers the best-of query with a comparison.",
                "target_keywords": ["ai content brief tool", "best seo content tool"],
                "priority": "high",
            },
            {
                "query_id": "q-does-not-exist",
                "content_type": "blog_post",
                "title": "Should be dropped",
                "rationale": "n/a",
                "target_keywords": [],
                "priority": "low",
            },
        ]
    }
    with app.app_context():
        agent = ContentRecommendationAgent(llm_client=FakeLLMClient(canned))
        recs, _ = agent.run(profile, gap_queries)

    assert len(recs) == 1
    assert recs[0]["query_uuid"] == "q-1"


def test_recommendation_agent_returns_empty_for_no_gaps(app, profile):
    with app.app_context():
        agent = ContentRecommendationAgent(llm_client=FakeLLMClient({}))
        recs, tokens = agent.run(profile, [])
    assert recs == []
    assert tokens == 0


# ---------------------------------------------------------------------------
# API-level: request validation (marshmallow)
# ---------------------------------------------------------------------------

def test_create_profile_rejects_missing_required_fields(client):
    r = client.post("/api/v1/profiles", json={"name": "X"})
    assert r.status_code == 422
    body = r.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "domain" in body["error"]["details"]
    assert "industry" in body["error"]["details"]


def test_create_profile_rejects_wrong_type_for_competitors(client):
    r = client.post(
        "/api/v1/profiles",
        json={"name": "X", "domain": "x.com", "industry": "SaaS", "competitors": "not-a-list"},
    )
    assert r.status_code == 422
    assert "competitors" in r.get_json()["error"]["details"]


def test_create_profile_succeeds_with_valid_payload(client):
    r = client.post(
        "/api/v1/profiles",
        json={"name": "Frase", "domain": "frase.io", "industry": "SEO Content Tools"},
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["name"] == "Frase"
    assert body["competitors"] == []  # defaulted by the schema when omitted


def test_opportunity_score_rewards_high_volume_low_difficulty_invisible_comparison():
    high = compute_opportunity_score(
        search_volume=15000, competitive_difficulty=10, domain_visible=False, intent="comparison"
    )
    low = compute_opportunity_score(
        search_volume=50, competitive_difficulty=90, domain_visible=True, intent="informational"
    )
    assert high > low
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_opportunity_score_visibility_gap_is_the_swing_factor():
    visible = compute_opportunity_score(
        search_volume=1000, competitive_difficulty=50, domain_visible=True, intent="best_of"
    )
    not_visible = compute_opportunity_score(
        search_volume=1000, competitive_difficulty=50, domain_visible=False, intent="best_of"
    )
    assert not_visible > visible
