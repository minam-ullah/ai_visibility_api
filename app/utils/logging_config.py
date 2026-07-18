"""Structured logging with correlation IDs.

Two kinds of correlation ID are threaded through here:

- request_id: generated (or read from an incoming X-Request-ID header) once
  per HTTP request, attached to Flask's `g`, echoed back in the response
  header, and injected into every log line emitted during that request via
  a logging.Filter.
- pipeline run_uuid: PipelineRun.uuid is bound onto a LoggerAdapter at the
  start of run_pipeline() (see services/pipeline.py) so every log line for
  that run -- across all three agents -- carries the same run_uuid, letting
  you grep one pipeline run's full trace out of shared logs.
"""
import logging
import uuid

from flask import g, request

LOG_FORMAT = "%(asctime)s %(levelname)s [request_id=%(request_id)s] %(name)s: %(message)s"


class _RequestIdFilter(logging.Filter):
    """Injects the current request's correlation ID into every log record,
    falling back to '-' for log lines emitted outside a request context
    (e.g. at app startup)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = getattr(g, "request_id", "-")
        except RuntimeError:
            record.request_id = "-"
        return True


def configure_logging(app):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    @app.before_request
    def _assign_request_id():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    @app.after_request
    def _echo_request_id(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        return response


class _RunLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[run_uuid={self.extra['run_uuid']}] {msg}", kwargs


def get_run_logger(base_logger: logging.Logger, run_uuid: str) -> logging.LoggerAdapter:
    """Wrap a module logger so every message it emits is prefixed with the
    pipeline run's UUID, in addition to the per-request correlation ID."""
    return _RunLoggerAdapter(base_logger, extra={"run_uuid": run_uuid})
