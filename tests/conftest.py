import os

os.environ["CONNECTOR_API_KEY"] = "test-connector-key"
os.environ["PHASE2_TEST_TOKENS"] = "test-token-rahul:12345,test-token-amit:12346,test-token-neha:12348,test-token-priya:12347,test-token-karan:12349,test-token-vikram:12350,mock-token-rahul:12345,mock-token-amit:12346,mock-token-neha:12348,mock-token-priya:12347,mock-token-karan:12349,mock-token-vikram:12350"
os.environ["MOCK_WHMCS_IDENTIFIER"] = "test-whmcs-identifier"
os.environ["MOCK_WHMCS_SECRET"] = "test-whmcs-secret"

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-Connector-Key": "test-connector-key"}
