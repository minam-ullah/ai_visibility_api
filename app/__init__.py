from flask import Flask, jsonify

from app.config import Config
from app.extensions import db, migrate
from app.utils.errors import register_error_handlers
from app.utils.limiter import limiter
from app.utils.logging_config import configure_logging


def create_app(config_object: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    configure_logging(app)

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # Register models so Flask-Migrate can see them.
    from app import models  # noqa: F401

    from app.api.profiles import bp as profiles_bp
    from app.api.queries import bp as queries_bp

    app.register_blueprint(profiles_bp)
    app.register_blueprint(queries_bp)

    register_error_handlers(app)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app
