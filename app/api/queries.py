from datetime import datetime, timezone

from flask import Blueprint, jsonify

from app.agents.scoring import VisibilityScoringAgent
from app.extensions import db
from app.models import BusinessProfile, DiscoveredQuery
from app.utils.errors import APIError

bp = Blueprint("queries", __name__, url_prefix="/api/v1/queries")


@bp.post("/<query_uuid>/recheck")
def recheck_query(query_uuid):
    query = DiscoveredQuery.query.get(query_uuid)
    if not query:
        raise APIError("Query not found", 404, "NOT_FOUND")

    profile = BusinessProfile.query.get(query.profile_uuid)
    if not profile:
        raise APIError("Parent profile not found", 404, "NOT_FOUND")

    agent = VisibilityScoringAgent()
    try:
        scored, tokens = agent.run(profile, query.query_text, query.query_intent)
    except Exception as exc:
        raise APIError(f"Recheck failed: {exc}", 502, "AGENT_FAILURE")

    query.estimated_search_volume = scored["estimated_search_volume"]
    query.competitive_difficulty = scored["competitive_difficulty"]
    query.domain_visible = scored["domain_visible"]
    query.visibility_position = scored["visibility_position"]
    query.visibility_status = scored["visibility_status"]
    query.opportunity_score = scored["opportunity_score"]
    query.last_checked_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({"query": query.to_dict(), "tokens_used": tokens}), 200
