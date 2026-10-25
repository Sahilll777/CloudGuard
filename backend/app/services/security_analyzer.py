from ipaddress import ip_network


VALID_PROTOCOLS = {"tcp", "udp", "icmp", "all"}
ADMIN_PORTS = {
    22: ("SSH", "Remote Linux administration"),
    3389: ("RDP", "Remote Windows administration"),
}


class SecurityRuleError(ValueError):
    """Raised when a security rule is invalid."""


def analyze_security_group(
    group_name: str,
    inbound_rules: list[dict],
    outbound_rules: list[dict] | None = None,
) -> dict:
    """Analyze security group rules and produce actionable findings."""

    if not isinstance(group_name, str) or not group_name.strip():
        raise SecurityRuleError("Security group name is required.")

    outbound_rules = outbound_rules or []
    findings = []
    validated_counts = {"inbound": 0, "outbound": 0}

    def inspect_rule(rule: dict, direction: str, index: int) -> None:
        if not isinstance(rule, dict):
            raise SecurityRuleError(
                f"{direction} rule {index}: rule must be an object."
            )

        protocol = rule.get("protocol")
        cidr = rule.get("cidr")
        from_port = rule.get("from_port")
        to_port = rule.get("to_port")

        if not isinstance(protocol, str):
            raise SecurityRuleError(
                f"{direction} rule {index}: protocol must be a string."
            )

        protocol = protocol.lower()

        if protocol not in VALID_PROTOCOLS:
            raise SecurityRuleError(
                f"{direction} rule {index}: unsupported protocol."
            )

        if not isinstance(cidr, str):
            raise SecurityRuleError(
                f"{direction} rule {index}: CIDR must be a string."
            )

        try:
            network = ip_network(cidr, strict=True)
        except ValueError as exc:
            raise SecurityRuleError(
                f"{direction} rule {index}: invalid CIDR '{cidr}'."
            ) from exc

        if protocol == "all":
            if from_port is not None or to_port is not None:
                raise SecurityRuleError(
                    f"{direction} rule {index}: all-protocol rules "
                    "must not specify port ranges."
                )
        elif protocol in {"tcp", "udp"}:
            if (
                not isinstance(from_port, int)
                or isinstance(from_port, bool)
                or not isinstance(to_port, int)
                or isinstance(to_port, bool)
                or not 0 <= from_port <= to_port <= 65535
            ):
                raise SecurityRuleError(
                    f"{direction} rule {index}: invalid port range."
                )
        elif from_port is not None or to_port is not None:
            raise SecurityRuleError(
                f"{direction} rule {index}: ICMP rules in this "
                "simulator do not accept TCP/UDP port fields."
            )

        validated_counts[direction] += 1
        unrestricted = network.prefixlen == 0

        if direction == "inbound" and unrestricted and protocol == "all":
            findings.append({
                "severity": "CRITICAL",
                "code": "INGRESS_ALL_TRAFFIC_PUBLIC",
                "title": "All inbound traffic is unrestricted",
                "risk": (
                    "Any IPv4 source can attempt traffic using any protocol "
                    "allowed by this rule."
                ),
                "recommendation": (
                    "Remove the unrestricted rule. Permit only required "
                    "protocols, ports, and trusted source ranges."
                ),
                "rule_index": index,
            })

        if direction == "inbound" and unrestricted and protocol in {"tcp", "udp"}:
            if from_port == 0 and to_port == 65535:
                findings.append({
                    "severity": "CRITICAL",
                    "code": "INGRESS_ALL_PORTS_PUBLIC",
                    "title": "All TCP/UDP ports are publicly exposed",
                    "risk": (
                        "Every port in the configured protocol range "
                        "is reachable from any IPv4 source, subject to "
                        "other network controls."
                    ),
                    "recommendation": (
                        "Restrict exposed ports and limit source CIDRs."
                    ),
                    "rule_index": index,
                })

        if direction == "inbound" and unrestricted and protocol == "tcp":
            for port, (service, description) in ADMIN_PORTS.items():
                if from_port <= port <= to_port:
                    findings.append({
                        "severity": "HIGH",
                        "code": f"PUBLIC_{service.upper()}",
                        "title": f"{service} is open to the internet",
                        "risk": (
                            f"{description} is exposed to any IPv4 source. "
                            "This increases brute-force and exploitation risk."
                        ),
                        "recommendation": (
                            "Remove public access. Restrict the source to "
                            "a trusted IP/CIDR or use a controlled "
                            "administration service."
                        ),
                        "rule_index": index,
                    })

        if direction == "inbound" and unrestricted and protocol == "tcp":
            if from_port <= 3306 <= to_port or from_port <= 5432 <= to_port:
                findings.append({
                    "severity": "CRITICAL",
                    "code": "PUBLIC_DATABASE_PORT",
                    "title": "A common database port is publicly exposed",
                    "risk": (
                        "MySQL/MariaDB port 3306 or PostgreSQL port 5432 "
                        "is included in the public TCP range."
                    ),
                    "recommendation": (
                        "Keep database access private and allow only "
                        "the required application security group."
                    ),
                    "rule_index": index,
                })

        if unrestricted and direction == "outbound":
            findings.append({
                "severity": "MEDIUM",
                "code": "UNRESTRICTED_EGRESS",
                "title": "Outbound access is unrestricted",
                "risk": (
                    "The rule permits traffic to any IPv4 destination "
                    "within the configured protocol and port scope."
                ),
                "recommendation": (
                    "Review business requirements and restrict egress "
                    "where practical."
                ),
                "rule_index": index,
            })

    for index, rule in enumerate(inbound_rules):
        inspect_rule(rule, "inbound", index)

    for index, rule in enumerate(outbound_rules):
        inspect_rule(rule, "outbound", index)

    severity_order = {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }
    findings.sort(key=lambda item: severity_order[item["severity"]])

    counts = {
        severity: sum(
            1 for finding in findings
            if finding["severity"] == severity
        )
        for severity in severity_order
    }

    return {
        "group_name": group_name,
        "rules_analyzed": validated_counts,
        "finding_count": len(findings),
        "severity_counts": counts,
        "risk_level": (
            "CRITICAL" if counts["CRITICAL"]
            else "HIGH" if counts["HIGH"]
            else "MEDIUM" if counts["MEDIUM"]
            else "LOW" if counts["LOW"]
            else "NO_FINDINGS"
        ),
        "findings": findings,
        "limitations": [
            "This is a local rule analyzer, not an AWS account audit.",
            "Findings identify rule exposure, not proof of exploitability.",
            "IPv6 rules, prefix lists, and security-group references "
            "are not yet modeled.",
        ],
    }
