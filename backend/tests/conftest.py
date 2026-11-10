"""Tests always use a temporary database, never the interactive demo store."""
import os
import tempfile

import pytest

_database = tempfile.TemporaryDirectory(prefix="signal-tests-")
os.environ["SIGNAL_DATABASE_URL"] = f"sqlite:///{_database.name}/test.db"
os.environ["SIGNAL_AGENT_MODE"] = "deterministic"
os.environ["SIGNAL_ENVIRONMENT"] = "development"
os.environ["SIGNAL_ALLOWED_HOSTS"] = '["testserver", "localhost", "127.0.0.1"]'
os.environ["SIGNAL_REQUESTS_PER_MINUTE"] = "10000"

from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def headers():
    return {"Authorization": "Bearer demo-atlas-alarm"}
