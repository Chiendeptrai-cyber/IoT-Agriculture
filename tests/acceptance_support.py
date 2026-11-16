"""Small in-process adapters shared by the KT1/KT2 acceptance tests."""

from pathlib import Path
import sys

import requests
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for directory in ("edge-gateway", "sensor-simulator", "server"):
    path = str(ROOT / directory)
    if path not in sys.path:
        sys.path.insert(0, path)

from server.database import build_engine
from server.main import Settings, create_app


class FakeInfluxStore:
    """Record writes so acceptance tests can verify durable-write ordering."""

    def __init__(self):
        self.rows = []
        self.healthy_state = True

    def write(self, record, gateway_id, received_at):
        self.rows.append((record, gateway_id, received_at))

    def healthy(self):
        return self.healthy_state

    def close(self):
        pass


class TestClientAdapter(requests.adapters.BaseAdapter):
    """Route SyncManager's HTTP request through FastAPI's in-process client."""

    def __init__(self, client):
        super().__init__()
        self.client = client

    def send(self, request, **kwargs):
        response = self.client.request(
            request.method,
            request.path_url,
            content=request.body,
            headers=dict(request.headers),
        )
        result = requests.Response()
        result.status_code = response.status_code
        result.reason = response.reason_phrase
        result._content = response.content
        result._content_consumed = True
        result.headers.update(response.headers)
        result.url = request.url
        result.request = request
        return result

    def close(self):
        pass


def make_server():
    engine = build_engine("sqlite://")
    influx = FakeInfluxStore()
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        influx_url="http://unused",
        influx_token="unused",
        influx_org="test",
        influx_bucket="smart_agriculture",
    )
    client = TestClient(create_app(settings=settings, engine=engine, influx_store=influx))
    client.__enter__()
    return client, engine, influx


def make_http_session(client):
    session = requests.Session()
    session.mount("http://acceptance.test/", TestClientAdapter(client))
    return session
