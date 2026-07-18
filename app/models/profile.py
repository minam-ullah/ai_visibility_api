import uuid
from datetime import datetime, timezone

from app.extensions import db


def gen_uuid() -> str:
    return str(uuid.uuid4())


class BusinessProfile(db.Model):
    __tablename__ = "business_profiles"

    uuid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(255), nullable=False)
    domain = db.Column(db.String(255), nullable=False, index=True)
    industry = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    competitors = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(db.String(32), nullable=False, default="created")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    runs = db.relationship("PipelineRun", backref="profile", cascade="all, delete-orphan")
    queries = db.relationship("DiscoveredQuery", backref="profile", cascade="all, delete-orphan")
    recommendations = db.relationship(
        "ContentRecommendation", backref="profile", cascade="all, delete-orphan"
    )

    def to_dict(self, with_stats: bool = False) -> dict:
        data = {
            "profile_uuid": self.uuid,
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "description": self.description,
            "competitors": self.competitors,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_stats:
            scores = [q.opportunity_score for q in self.queries if q.opportunity_score is not None]
            data["stats"] = {
                "total_queries_discovered": len(self.queries),
                "avg_opportunity_score": round(sum(scores) / len(scores), 4) if scores else None,
                "total_recommendations": len(self.recommendations),
            }
        return data
