import base64
import json
import threading
from http.client import HTTPConnection

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.persistence.schema import CREATORS, metadata
from src.provider_credit import ProviderCreditGovernor
from src.web.dashboard import DashboardServer


USER = "operator"
PASSWORD = "strong-dashboard-password"
CSRF = "provider-credit-reset-csrf-token"


def _auth():
    encoded = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    return f"Basic {encoded}"


def _request(host, method, path, payload=None):
    body = json.dumps(payload) if payload is not None else ""
    headers = {
        "Authorization": _auth(),
        "Content-Type": "application/json",
    }
    if method == "POST":
        headers["X-CSRF-Token"] = CSRF
        headers["Origin"] = f"http://{host}"
    connection = HTTPConnection(host, timeout=5)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    parsed = json.loads(response.read())
    status = response.status
    connection.close()
    return status, parsed


def test_operations_exposes_credit_state_and_reset_requires_confirmation():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(CREATORS.insert().values(id="creator-a"))
    governor = ProviderCreditGovernor(engine, creator_id="creator-a")
    governor.open_circuit("payment_required")

    server = DashboardServer(
        None,
        port=0,
        engine=engine,
        creator_id="creator-a",
        provider_connected=True,
        provider_error="PaymentRequiredError",
        dashboard_user=USER,
        dashboard_password=PASSWORD,
        csrf_token=CSRF,
        credit_governor=governor,
    )
    port = server.server.server_address[1]
    host = f"127.0.0.1:{port}"
    thread = threading.Thread(
        target=server.server.serve_forever,
        daemon=True,
    )
    thread.start()
    try:
        status, operations = _request(
            host,
            "GET",
            "/api/operations",
        )
        assert status == 200
        assert operations["provider_credit"]["circuit_open"] is True

        status, error = _request(
            host,
            "POST",
            "/api/provider/credits/reset",
            {"confirmation": "wrong"},
        )
        assert status == 400
        assert "confirmation" in error["error"]
        assert governor.is_circuit_open() is True

        status, result = _request(
            host,
            "POST",
            "/api/provider/credits/reset",
            {"confirmation": "RESET_PROVIDER_CREDIT_CIRCUIT"},
        )
        assert status == 200
        assert result == {"status": "reset", "circuit_open": False}
        assert governor.is_circuit_open() is False
    finally:
        server.shutdown()
        thread.join(timeout=2)
