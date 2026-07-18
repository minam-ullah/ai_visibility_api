import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

# Schema is managed via Flask-Migrate/Alembic (see migrations/), not auto-created
# here. Run `flask db upgrade` once after cloning -- see README "Setup".

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
