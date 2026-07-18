import logging
from datetime import datetime, timezone

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.scoring import VisibilityScoringAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.extensions import db
from app.models import DiscoveredQuery, ContentRecommendation, PipelineRun
from app.utils.logging_config import get_run_logger

logger = logging.getLogger(__name__)

TOP_GAP_QUERIES_FOR_RECOMMENDATIONS = 8  # how many not-visible queries Agent 3 sees


def run_pipeline(profile) -> PipelineRun:
    """Orchestrates Agent 1 -> Agent 2 (per query, failure-isolated) -> Agent 3.

    A failure in Agent 2 for a single query is logged and that query is
    skipped (it stays in the DB with default/unscored values); it does not
    abort the run. A failure in Agent 1 or a total failure of Agent 2 (zero
    queries scored) marks the whole run "failed". Agent 3 failing does not
    fail the run -- recommendations are a bonus on top of a working
    discovery+scoring result.
    """
    run = PipelineRun(profile_uuid=profile.uuid, status="running")
    db.session.add(run)
    db.session.commit()

    run_logger = get_run_logger(logger, run.uuid)
    run_logger.info("Pipeline started for profile_uuid=%s (%s)", profile.uuid, profile.domain)

    total_tokens = 0

    try:
        # ---- Agent 1: Discovery ----
        discovery_agent = QueryDiscoveryAgent()
        raw_queries, tokens = discovery_agent.run(profile)
        total_tokens += tokens
        run_logger.info("Agent 1 discovered %d candidate queries (%d tokens)", len(raw_queries), tokens)

        if not raw_queries:
            raise RuntimeError("Agent 1 (discovery) returned zero usable queries")

        query_rows = []
        for item in raw_queries:
            row = DiscoveredQuery(
                profile_uuid=profile.uuid,
                run_uuid=run.uuid,
                query_text=item["query_text"],
                query_intent=item["intent"],
            )
            db.session.add(row)
            query_rows.append(row)
        db.session.commit()
        run.queries_discovered = len(query_rows)

        # ---- Agent 2: Visibility Scoring (per query, isolated failures) ----
        scoring_agent = VisibilityScoringAgent()
        scored_count = 0
        for row in query_rows:
            try:
                scored, tokens = scoring_agent.run(profile, row.query_text, row.query_intent)
                total_tokens += tokens
                row.estimated_search_volume = scored["estimated_search_volume"]
                row.competitive_difficulty = scored["competitive_difficulty"]
                row.domain_visible = scored["domain_visible"]
                row.visibility_position = scored["visibility_position"]
                row.visibility_status = scored["visibility_status"]
                row.opportunity_score = scored["opportunity_score"]
                row.last_checked_at = datetime.now(timezone.utc)
                scored_count += 1
            except Exception:
                run_logger.exception(
                    "Agent 2 failed for query_uuid=%s ('%s'); leaving it unscored and continuing",
                    row.uuid,
                    row.query_text,
                )
                row.visibility_status = "unknown"
        db.session.commit()
        run.queries_scored = scored_count
        run_logger.info("Agent 2 scored %d/%d queries (%d tokens so far)", scored_count, len(query_rows), total_tokens)

        if scored_count == 0:
            raise RuntimeError("Agent 2 (scoring) failed for every discovered query")

        # ---- Agent 3: Content Recommendations (best-effort, non-fatal) ----
        try:
            gap_queries = (
                DiscoveredQuery.query.filter_by(run_uuid=run.uuid, domain_visible=False)
                .order_by(DiscoveredQuery.opportunity_score.desc())
                .limit(TOP_GAP_QUERIES_FOR_RECOMMENDATIONS)
                .all()
            )
            rec_agent = ContentRecommendationAgent()
            raw_recs, tokens = rec_agent.run(profile, gap_queries)
            total_tokens += tokens
            for item in raw_recs:
                db.session.add(
                    ContentRecommendation(
                        profile_uuid=profile.uuid,
                        query_uuid=item["query_uuid"],
                        content_type=item["content_type"],
                        title=item["title"],
                        rationale=item["rationale"],
                        target_keywords=item["target_keywords"],
                        priority=item["priority"],
                    )
                )
            db.session.commit()
            run_logger.info("Agent 3 generated %d content recommendations (%d tokens)", len(raw_recs), tokens)
        except Exception:
            run_logger.exception("Agent 3 (recommendations) failed; run still counts as completed")

        run.status = "completed"
        run.tokens_used = total_tokens
        run.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        run_logger.info("Pipeline completed: discovered=%d scored=%d tokens=%d", run.queries_discovered, run.queries_scored, total_tokens)
        return run

    except Exception as exc:
        run_logger.exception("Pipeline run failed")
        run.status = "failed"
        run.error_message = str(exc)
        run.tokens_used = total_tokens
        run.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return run
