from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import BusinessProfile, ContentRecommendation, DiscoveredQuery
from app.services.pipeline import run_pipeline
from app.utils.errors import APIError

bp = Blueprint("profiles", __name__, url_prefix="/api/v1/profiles")

REQUIRED_PROFILE_FIELDS = ["name", "domain", "industry"]


@bp.post("")
def create_profile():
    body = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED_PROFILE_FIELDS if not body.get(f)]
    if missing:
        raise APIError(f"Missing required field(s): {', '.join(missing)}", 422, "VALIDATION_ERROR")

    competitors = body.get("competitors", [])
    if not isinstance(competitors, list):
        raise APIError("'competitors' must be a list of domain strings", 422, "VALIDATION_ERROR")

    profile = BusinessProfile(
        name=body["name"],
        domain=body["domain"],
        industry=body["industry"],
        description=body.get("description"),
        competitors=competitors,
        status="created",
    )
    db.session.add(profile)
    db.session.commit()
    return jsonify(profile.to_dict()), 201


@bp.get("/<profile_uuid>")
def get_profile(profile_uuid):
    profile = BusinessProfile.query.get(profile_uuid)
    if not profile:
        raise APIError("Profile not found", 404, "NOT_FOUND")
    return jsonify(profile.to_dict(with_stats=True)), 200


@bp.post("/<profile_uuid>/run")
def run_profile_pipeline(profile_uuid):
    profile = BusinessProfile.query.get(profile_uuid)
    if not profile:
        raise APIError("Profile not found", 404, "NOT_FOUND")

    run = run_pipeline(profile)

    run_queries = DiscoveredQuery.query.filter_by(run_uuid=run.uuid).all()
    top_queries = sorted(run_queries, key=lambda q: q.opportunity_score or 0, reverse=True)[:3]

    run_query_ids = [q.uuid for q in run_queries] or [None]
    recommendations = ContentRecommendation.query.filter(
        ContentRecommendation.query_uuid.in_(run_query_ids)
    ).all()

    response = run.to_dict()
    response["top_opportunity_queries"] = [q.to_dict() for q in top_queries]
    response["content_recommendations"] = [r.to_dict() for r in recommendations]

    status_code = 200 if run.status == "completed" else 502
    return jsonify(response), status_code


@bp.get("/<profile_uuid>/queries")
def list_queries(profile_uuid):
    profile = BusinessProfile.query.get(profile_uuid)
    if not profile:
        raise APIError("Profile not found", 404, "NOT_FOUND")

    q = DiscoveredQuery.query.filter_by(profile_uuid=profile_uuid)

    min_score = request.args.get("min_score", type=float)
    if min_score is not None:
        q = q.filter(DiscoveredQuery.opportunity_score >= min_score)

    status = request.args.get("status")
    if status:
        if status not in ("visible", "not_visible", "unknown"):
            raise APIError(
                "Invalid 'status'; expected one of visible|not_visible|unknown", 422, "VALIDATION_ERROR"
            )
        q = q.filter(DiscoveredQuery.visibility_status == status)

    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=20, type=int)
    if page < 1 or per_page < 1 or per_page > 100:
        raise APIError("'page' must be >=1 and 'per_page' must be between 1 and 100", 422, "VALIDATION_ERROR")

    q = q.order_by(DiscoveredQuery.opportunity_score.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    return (
        jsonify(
            {
                "queries": [item.to_dict() for item in pagination.items],
                "page": page,
                "per_page": per_page,
                "total": pagination.total,
                "total_pages": pagination.pages,
            }
        ),
        200,
    )


@bp.get("/<profile_uuid>/recommendations")
def list_recommendations(profile_uuid):
    profile = BusinessProfile.query.get(profile_uuid)
    if not profile:
        raise APIError("Profile not found", 404, "NOT_FOUND")

    recs = (
        ContentRecommendation.query.filter_by(profile_uuid=profile_uuid)
        .order_by(ContentRecommendation.created_at.desc())
        .all()
    )
    return jsonify({"recommendations": [r.to_dict() for r in recs]}), 200
