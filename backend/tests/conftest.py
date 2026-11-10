"""Tests always use a temporary database, never the interactive demo store."""
import os
import tempfile

import pytest

_database = tempfile.TemporaryDirectory(prefix="signal-tests-")
os.environ["SIGNAL_DATABASE_URL"] = f"sqlite:///{_database.name}/test.db"
os.environ["SIGNAL_AGENT_MODE"] = "deterministic"

from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def headers():
    return {"Authorization": "Bearer demo-atlas-alarm"}
