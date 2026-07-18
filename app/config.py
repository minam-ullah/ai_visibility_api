import os


class Config:
    """Base config. Values are pulled from environment variables (.env in dev)."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # LLM provider
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")  # "anthropic" | "openai"
    LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

    # Third-party search data (DataForSEO). If absent, search_data.py falls back
    # to a deterministic mock generator -- see README "Tradeoffs" section.
    DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN")
    DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")

    JSON_SORT_KEYS = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATELIMIT_ENABLED = False
