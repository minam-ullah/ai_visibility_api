from datetime import datetime, timezone

from app.extensions import db
from app.models.profile import gen_uuid


class PipelineRun(db.Model):
    __tablename__ = "pipeline_runs"

    uuid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    profile_uuid = db.Column(db.String(36), db.ForeignKey("business_profiles.uuid"), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="running")  # running|completed|failed
    queries_discovered = db.Column(db.Integer, default=0)
    queries_scored = db.Column(db.Integer, default=0)
    tokens_used = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)

    queries = db.relationship("DiscoveredQuery", backref="run", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "pipeline_run_uuid": self.uuid,
            "profile_uuid": self.profile_uuid,
            "status": self.status,
            "queries_discovered": self.queries_discovered,
            "queries_scored": self.queries_scored,
            "tokens_used": self.tokens_used,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
