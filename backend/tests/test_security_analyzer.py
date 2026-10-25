import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.security_analyzer import (
    SecurityRuleError,
    analyze_security_group,
)

client = TestClient(app)


def test_public_ssh_is_flagged() -> None:
    result = analyze_security_group(
        "demo",
        [{
            "protocol": "tcp",
            "cidr": "0.0.0.0/0",
            "from_port": 22,
            "to_port": 22,
        }],
    )

    assert result["risk_level"] == "HIGH"
    assert any(
        item["code"] == "PUBLIC_SSH"
        for item in result["findings"]
    )


def test_public_database_is_flagged() -> None:
    result = analyze_security_group(
        "database",
        [{
            "protocol": "tcp",
            "cidr": "0.0.0.0/0",
            "from_port": 5432,
            "to_port": 5432,
        }],
    )

    assert any(
        item["code"] == "PUBLIC_DATABASE_PORT"
        for item in result["findings"]
    )


def test_all_inbound_traffic_is_critical() -> None:
    result = analyze_security_group(
        "exposed",
        [{
            "protocol": "all",
            "cidr": "0.0.0.0/0",
        }],
    )

    assert result["risk_level"] == "CRITICAL"
    assert result["severity_counts"]["CRITICAL"] >= 1


def test_restricted_ssh_does_not_trigger_public_ssh() -> None:
    result = analyze_security_group(
        "restricted",
        [{
            "protocol": "tcp",
            "cidr": "203.0.113.10/32",
            "from_port": 22,
            "to_port": 22,
        }],
    )

    assert not any(
        item["code"] == "PUBLIC_SSH"
        for item in result["findings"]
    )


def test_unrestricted_egress_is_reported() -> None:
    result = analyze_security_group(
        "egress",
        [],
        [{
            "protocol": "all",
            "cidr": "0.0.0.0/0",
        }],
    )

    assert any(
        item["code"] == "UNRESTRICTED_EGRESS"
        for item in result["findings"]
    )


def test_invalid_cidr_is_rejected() -> None:
    with pytest.raises(SecurityRuleError):
        analyze_security_group(
            "invalid",
            [{
                "protocol": "tcp",
                "cidr": "10.0.0.1/24",
                "from_port": 22,
                "to_port": 22,
            }],
        )


def test_invalid_port_range_is_rejected() -> None:
    with pytest.raises(SecurityRuleError):
        analyze_security_group(
            "invalid",
            [{
                "protocol": "tcp",
                "cidr": "10.0.0.0/24",
                "from_port": 100,
                "to_port": 50,
            }],
        )


def test_security_audit_api() -> None:
    response = client.post(
        "/api/security/audit",
        json={
            "group_name": "web-server",
            "inbound_rules": [{
                "protocol": "tcp",
                "cidr": "0.0.0.0/0",
                "from_port": 22,
                "to_port": 22,
            }],
            "outbound_rules": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["finding_count"] >= 1
    assert response.json()["risk_level"] == "HIGH"


def test_security_audit_rejects_bad_port() -> None:
    response = client.post(
        "/api/security/audit",
        json={
            "group_name": "invalid",
            "inbound_rules": [{
                "protocol": "tcp",
                "cidr": "0.0.0.0/0",
                "from_port": 70000,
                "to_port": 70000,
            }],
        },
    )

    assert response.status_code == 422
