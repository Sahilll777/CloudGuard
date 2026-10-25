import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.network_engine import (
    NetworkPlanError,
    build_network_plan,
)

client = TestClient(app)


def test_default_vpc_plan() -> None:
    plan = build_network_plan("10.0.0.0/16")

    assert plan["total_subnets"] == 4
    assert plan["vpc_cidr"] == "10.0.0.0/16"
    assert [s["type"] for s in plan["subnets"]] == [
        "public", "public", "private", "private"
    ]
    assert len({s["cidr"] for s in plan["subnets"]}) == 4


def test_subnets_fit_inside_vpc() -> None:
    plan = build_network_plan(
        "10.10.0.0/16",
        subnet_prefix=24,
        public_subnets=2,
        private_subnets=2,
    )

    for subnet in plan["subnets"]:
        assert subnet["cidr"].startswith("10.10.")
        assert subnet["aws_usable_ipv4_addresses"] == 251


def test_capacity_is_reported() -> None:
    plan = build_network_plan(
        "192.168.0.0/24",
        subnet_prefix=26,
        public_subnets=2,
        private_subnets=2,
    )

    assert plan["available_subnet_capacity"] == 4
    assert plan["remaining_subnet_capacity"] == 0


def test_invalid_cidr_is_rejected() -> None:
    with pytest.raises(NetworkPlanError):
        build_network_plan("10.0.0.1/16")


def test_subnet_capacity_overflow_is_rejected() -> None:
    with pytest.raises(NetworkPlanError):
        build_network_plan(
            "192.168.0.0/24",
            subnet_prefix=26,
            public_subnets=3,
            private_subnets=2,
        )


def test_api_returns_network_plan() -> None:
    response = client.post(
        "/api/network/plan",
        json={
            "cidr": "10.0.0.0/16",
            "subnet_prefix": 24,
            "public_subnets": 2,
            "private_subnets": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["total_subnets"] == 4


def test_api_rejects_invalid_network() -> None:
    response = client.post(
        "/api/network/plan",
        json={"cidr": "10.0.0.1/16"},
    )

    assert response.status_code == 422
