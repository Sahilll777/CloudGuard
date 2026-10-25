from fastapi.testclient import TestClient

from app.main import app
from app.services.traffic_simulator import simulate_traffic

client = TestClient(app)


def test_allowed_https_traffic() -> None:
    result = simulate_traffic(
        vpc_cidr="10.0.0.0/16",
        source_ip="203.0.113.10",
        destination_ip="10.0.1.10",
        protocol="tcp",
        destination_port=443,
        routes=[],
        inbound_rules=[{
            "protocol": "tcp",
            "cidr": "203.0.113.10/32",
            "from_port": 443,
            "to_port": 443,
        }],
        outbound_rules=[{
            "protocol": "all",
            "cidr": "0.0.0.0/0",
        }],
    )

    assert result["decision"] == "ALLOWED"


def test_missing_route_blocks_traffic() -> None:
    result = simulate_traffic(
        "10.0.0.0/16",
        "10.0.1.10",
        "8.8.8.8",
        "tcp",
        443,
        [],
        [{"protocol": "tcp", "cidr": "0.0.0.0/0",
          "from_port": 443, "to_port": 443}],
        [{"protocol": "all", "cidr": "0.0.0.0/0"}],
    )

    assert result["decision"] == "BLOCKED"
    assert result["steps"][0]["decision"] == "DENY"


def test_missing_egress_rule_blocks_traffic() -> None:
    result = simulate_traffic(
        "10.0.0.0/16",
        "10.0.1.10",
        "10.0.2.10",
        "tcp",
        443,
        [],
        [{"protocol": "tcp", "cidr": "10.0.1.10/32",
          "from_port": 443, "to_port": 443}],
        [],
    )

    assert result["decision"] == "BLOCKED"
    assert result["steps"][1]["decision"] == "DENY"


def test_missing_ingress_rule_blocks_traffic() -> None:
    result = simulate_traffic(
        "10.0.0.0/16",
        "10.0.1.10",
        "10.0.2.10",
        "tcp",
        443,
        [],
        [],
        [{"protocol": "all", "cidr": "0.0.0.0/0"}],
    )

    assert result["decision"] == "BLOCKED"
    assert result["steps"][2]["decision"] == "DENY"


def test_traffic_api() -> None:
    response = client.post(
        "/api/traffic/simulate",
        json={
            "vpc_cidr": "10.0.0.0/16",
            "source_ip": "10.0.1.10",
            "destination_ip": "10.0.2.10",
            "protocol": "tcp",
            "destination_port": 443,
            "routes": [],
            "inbound_rules": [{
                "protocol": "tcp",
                "cidr": "10.0.1.10/32",
                "from_port": 443,
                "to_port": 443,
            }],
            "outbound_rules": [{
                "protocol": "all",
                "cidr": "0.0.0.0/0",
            }],
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "ALLOWED"


def test_invalid_protocol_is_rejected() -> None:
    response = client.post(
        "/api/traffic/simulate",
        json={
            "source_ip": "10.0.1.10",
            "destination_ip": "10.0.2.10",
            "protocol": "ftp",
            "destination_port": 21,
        },
    )

    assert response.status_code == 422
