import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import BusinessProfile


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def profile(app):
    with app.app_context():
        p = BusinessProfile(
            name="Frase",
            domain="frase.io",
            industry="SEO Content Tools",
            description="AI-powered content briefs and SEO research",
            competitors=["surferseo.com", "marketmuse.com", "clearscope.io"],
        )
        db.session.add(p)
        db.session.commit()
        db.session.refresh(p)
        yield p
