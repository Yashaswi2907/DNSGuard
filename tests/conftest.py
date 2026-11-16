"""Shared pytest fixtures. All DNS traffic is mocked: tests never use the network."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from config import TestConfig  # noqa: E402
from dns_engine import DNSQueryEngine, get_resolver  # noqa: E402
from services.security import rate_limiter  # noqa: E402
from tests.mock_dns import MockDNS  # noqa: E402


@pytest.fixture
def mock_dns():
    return MockDNS()


@pytest.fixture
def engine(mock_dns):
    return DNSQueryEngine(udp=mock_dns.udp, tcp=mock_dns.tcp)


@pytest.fixture
def google():
    return get_resolver("google")


@pytest.fixture
def cloudflare():
    return get_resolver("cloudflare")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "dnsguard-test.db")


@pytest.fixture
def app(engine, db_path):
    application = create_app(TestConfig, engine=engine, DATABASE=db_path)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


def run(client, **body):
    """POST a synchronous DNS test and return the parsed JSON."""
    payload = {"domain": "example.com", "record_type": "A", "resolvers": "both", "attempts": 3, "timeout": 1}
    payload.update(body)
    return client.post("/api/dns/resolve", json=payload)
