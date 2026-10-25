import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.routing_engine import (
    RoutingError,
    evaluate_route,
)

client = TestClient(app)


def test_vpc_local_route() -> None:
    result = evaluate_route(
        "10.0.0.0/16",
        "10.0.5.10",
        [],
    )

    assert result["decision"] == "ALLOW"
    assert result["target"] == "local"


def test_internet_gateway_route() -> None:
    result = evaluate_route(
        "10.0.0.0/16",
        "8.8.8.8",
        [{"destination_cidr": "0.0.0.0/0", "target": "igw"}],
    )

    assert result["decision"] == "ROUTE"
    assert result["target"] == "igw"


def test_longest_prefix_match_wins() -> None:
    result = evaluate_route(
        "10.0.0.0/16",
        "8.8.8.8",
        [
            {"destination_cidr": "0.0.0.0/0", "target": "igw"},
            {"destination_cidr": "8.8.8.0/24", "target": "blackhole"},
        ],
    )

    assert result["decision"] == "DENY"
    assert result["matched_route"] == "8.8.8.0/24"


def test_missing_route_is_denied() -> None:
    result = evaluate_route("10.0.0.0/16", "8.8.8.8", [])

    assert result["decision"] == "DENY"
    assert result["matched_route"] is None


def test_nat_gateway_route() -> None:
    result = evaluate_route(
        "10.0.0.0/16",
        "1.1.1.1",
        [{"destination_cidr": "0.0.0.0/0", "target": "nat"}],
    )

    assert result["decision"] == "ROUTE"
    assert result["target"] == "nat"


def test_invalid_destination_is_rejected() -> None:
    with pytest.raises(RoutingError):
        evaluate_route("10.0.0.0/16", "not-an-ip", [])


def test_route_api() -> None:
    response = client.post(
        "/api/network/route-check",
        json={
            "vpc_cidr": "10.0.0.0/16",
            "destination_ip": "8.8.8.8",
            "routes": [
                {
                    "destination_cidr": "0.0.0.0/0",
                    "target": "igw",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["target"] == "igw"
