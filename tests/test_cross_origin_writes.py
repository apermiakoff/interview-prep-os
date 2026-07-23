"""Same-origin write middleware behind a TLS-terminating reverse proxy.

Production serves https via Tailscale Serve proxying to plain-http uvicorn, so
the app-side transport scheme is http while the browser's Origin is https. The
middleware must reconcile the two via X-Forwarded-Proto without ever letting a
foreign Origin through. TestClient speaks http to host "testserver", which
mirrors the proxied hop exactly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

PAYLOAD = {
    "display_name": "Proxy Learner",
    "interview_target": "Backend role",
    "weekly_hours": 7,
    "timezone": "America/New_York",
    "weak_areas": ["graphs"],
    "preferred_language": "Python",
}


def put_settings(client: TestClient, headers: dict[str, str]) -> int:
    return client.put("/api/learner-settings", json=PAYLOAD, headers=headers).status_code


def test_https_write_through_tls_terminating_proxy_is_same_origin():
    with TestClient(app) as client:
        status = put_settings(
            client,
            {"Origin": "https://testserver", "X-Forwarded-Proto": "https"},
        )
        assert status == 200


def test_referer_fallback_works_through_proxy():
    with TestClient(app) as client:
        status = put_settings(
            client,
            {"Referer": "https://testserver/#/solve", "X-Forwarded-Proto": "https"},
        )
        assert status == 200


def test_multi_hop_forwarded_proto_uses_first_value():
    with TestClient(app) as client:
        status = put_settings(
            client,
            {"Origin": "https://testserver", "X-Forwarded-Proto": "https, http"},
        )
        assert status == 200


def test_direct_localhost_write_still_works():
    with TestClient(app) as client:
        assert put_settings(client, {"Origin": "http://testserver"}) == 200


def test_cli_write_without_origin_still_works():
    with TestClient(app) as client:
        assert put_settings(client, {}) == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "https://evil.example", "X-Forwarded-Proto": "https"},
        {"Origin": "http://evil.example", "X-Forwarded-Proto": "http"},
        {"Referer": "https://evil.example/attack", "X-Forwarded-Proto": "https"},
    ],
)
def test_foreign_origin_write_rejected_regardless_of_proxy_headers(headers):
    with TestClient(app) as client:
        response = client.put("/api/learner-settings", json=PAYLOAD, headers=headers)
        assert response.status_code == 403
        assert response.json() == {"detail": "cross-origin write rejected"}


def test_scheme_mismatch_still_rejected_without_proxy_header():
    # No X-Forwarded-Proto: an https Origin against the http transport must
    # keep failing, so a garbage forwarded value must not relax the check.
    with TestClient(app) as client:
        assert put_settings(client, {"Origin": "https://testserver"}) == 403
        assert (
            put_settings(
                client,
                {"Origin": "https://testserver", "X-Forwarded-Proto": "gopher"},
            )
            == 403
        )
