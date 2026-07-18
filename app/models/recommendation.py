from datetime import datetime, timezone

from app.extensions import db
from app.models.profile import gen_uuid


class ContentRecommendation(db.Model):
    __tablename__ = "content_recommendations"

    uuid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    profile_uuid = db.Column(db.String(36), db.ForeignKey("business_profiles.uuid"), nullable=False)
    query_uuid = db.Column(db.String(36), db.ForeignKey("discovered_queries.uuid"), nullable=False)

    content_type = db.Column(db.String(32), nullable=False)  # blog_post|landing_page|faq|comparison_page
    title = db.Column(db.String(500), nullable=False)
    rationale = db.Column(db.Text, nullable=False)
    target_keywords = db.Column(db.JSON, nullable=False, default=list)
    priority = db.Column(db.String(16), nullable=False, default="medium")  # high|medium|low

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "recommendation_uuid": self.uuid,
            "target_query_uuid": self.query_uuid,
            "content_type": self.content_type,
            "title": self.title,
            "rationale": self.rationale,
            "target_keywords": self.target_keywords,
            "priority": self.priority,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
