from ipaddress import ip_address, ip_network

from app.services.routing_engine import evaluate_route, RoutingError


class TrafficSimulationError(ValueError):
    """Raised when a traffic simulation request is invalid."""


def _rule_matches(
    rule: dict,
    peer_ip: str,
    protocol: str,
    port: int | None,
) -> bool:
    try:
        network = ip_network(rule["cidr"], strict=True)
        address = ip_address(peer_ip)
    except (ValueError, KeyError, TypeError):
        return False

    if network.version != address.version or address not in network:
        return False

    rule_protocol = str(rule.get("protocol", "")).lower()

    if rule_protocol == "all":
        return True

    if rule_protocol != protocol:
        return False

    if protocol in {"tcp", "udp"}:
        start = rule.get("from_port")
        end = rule.get("to_port")

        return (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and port is not None
            and start <= port <= end
        )

    return protocol == "icmp"


def _matching_rule(
    rules: list[dict],
    peer_ip: str,
    protocol: str,
    port: int | None,
) -> int | None:
    for index, rule in enumerate(rules):
        if _rule_matches(rule, peer_ip, protocol, port):
            return index
    return None


def simulate_traffic(
    vpc_cidr: str,
    source_ip: str,
    destination_ip: str,
    protocol: str,
    destination_port: int | None,
    routes: list[dict],
    inbound_rules: list[dict],
    outbound_rules: list[dict],
) -> dict:
    """Simulate a simplified packet path and explain each decision."""

    try:
        source = ip_address(source_ip)
        destination = ip_address(destination_ip)
        vpc = ip_network(vpc_cidr, strict=True)
    except ValueError as exc:
        raise TrafficSimulationError(str(exc)) from exc

    if source.version != 4 or destination.version != 4 or vpc.version != 4:
        raise TrafficSimulationError("Only IPv4 traffic is supported.")

    if not isinstance(protocol, str):
        raise TrafficSimulationError("Protocol must be a string.")

    protocol = protocol.lower()

    if protocol not in {"tcp", "udp", "icmp"}:
        raise TrafficSimulationError("Protocol must be tcp, udp, or icmp.")

    if protocol in {"tcp", "udp"}:
        if (
            not isinstance(destination_port, int)
            or isinstance(destination_port, bool)
            or not 0 <= destination_port <= 65535
        ):
            raise TrafficSimulationError(
                "TCP/UDP traffic requires a valid destination port."
            )
    elif destination_port is not None:
        raise TrafficSimulationError(
            "ICMP simulation must not specify a TCP/UDP port."
        )

    if source in vpc and destination in vpc:
        if source == destination:
            raise TrafficSimulationError(
                "Source and destination IP addresses must differ."
            )

    try:
        route_result = evaluate_route(
            vpc_cidr,
            str(destination),
            routes,
        )
    except RoutingError as exc:
        raise TrafficSimulationError(str(exc)) from exc

    steps = [
        {
            "stage": "route_lookup",
            "decision": route_result["decision"],
            "reason": route_result["reason"],
        }
    ]

    if route_result["decision"] == "DENY":
        return {
            "decision": "BLOCKED",
            "source_ip": str(source),
            "destination_ip": str(destination),
            "protocol": protocol,
            "destination_port": destination_port,
            "steps": steps,
            "explanation": "Traffic was blocked because no usable route matched.",
        }

    outbound_index = _matching_rule(
        outbound_rules,
        str(destination),
        protocol,
        destination_port,
    )

    steps.append({
        "stage": "security_group_egress",
        "decision": "ALLOW" if outbound_index is not None else "DENY",
        "matched_rule_index": outbound_index,
        "reason": (
            "An outbound rule matches the destination and traffic."
            if outbound_index is not None
            else "No outbound Security Group rule matches the traffic."
        ),
    })

    if outbound_index is None:
        return {
            "decision": "BLOCKED",
            "source_ip": str(source),
            "destination_ip": str(destination),
            "protocol": protocol,
            "destination_port": destination_port,
            "steps": steps,
            "explanation": "Outbound Security Group rules do not permit this traffic.",
        }

    inbound_index = _matching_rule(
        inbound_rules,
        str(source),
        protocol,
        destination_port,
    )

    steps.append({
        "stage": "security_group_ingress",
        "decision": "ALLOW" if inbound_index is not None else "DENY",
        "matched_rule_index": inbound_index,
        "reason": (
            "An inbound rule matches the source and traffic."
            if inbound_index is not None
            else "No inbound Security Group rule matches the traffic."
        ),
    })

    if inbound_index is None:
        return {
            "decision": "BLOCKED",
            "source_ip": str(source),
            "destination_ip": str(destination),
            "protocol": protocol,
            "destination_port": destination_port,
            "steps": steps,
            "explanation": "Inbound Security Group rules do not permit this traffic.",
        }

    return {
        "decision": "ALLOWED",
        "source_ip": str(source),
        "destination_ip": str(destination),
        "protocol": protocol,
        "destination_port": destination_port,
        "steps": steps,
        "explanation": (
            "The simulated route and both Security Group rule checks passed. "
            "Other AWS controls and actual service availability are not modeled."
        ),
    }
