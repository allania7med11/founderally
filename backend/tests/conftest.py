"""Settings for every test: the local stack's addresses. Set at import, so settings() works without a .env."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://founderally:founderally@localhost:5432/founderally")
os.environ.setdefault("TEMPORAL_ADDRESS", "localhost:7233")
os.environ.setdefault("API_URL", "http://localhost:8000")
