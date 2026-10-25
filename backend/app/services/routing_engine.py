from ipaddress import ip_address, ip_network


class RoutingError(ValueError):
    """Raised when a route table or destination is invalid."""


def evaluate_route(
    vpc_cidr: str,
    destination_ip: str,
    routes: list[dict],
) -> dict:
    """Evaluate a destination using AWS-style longest-prefix matching."""

    try:
        vpc = ip_network(vpc_cidr, strict=True)
        destination = ip_address(destination_ip)
    except ValueError as exc:
        raise RoutingError(str(exc)) from exc

    if vpc.version != 4 or destination.version != 4:
        raise RoutingError("Only IPv4 routing is supported.")

    if destination in vpc:
        return {
            "decision": "ALLOW",
            "matched_route": vpc.with_prefixlen,
            "target": "local",
            "reason": "Destination is inside the VPC CIDR.",
            "next_step": "Route traffic through the VPC local route.",
        }

    validated_routes = []

    for route in routes:
        try:
            network = ip_network(route["destination_cidr"], strict=True)
        except (ValueError, KeyError, TypeError) as exc:
            raise RoutingError(
                "Every route must have a valid destination_cidr."
            ) from exc

        if network.version != 4:
            raise RoutingError("Only IPv4 routes are supported.")

        target = route.get("target")

        if not isinstance(target, str) or not target.strip():
            raise RoutingError("Every route must have a non-empty target.")

        validated_routes.append((network, target.strip()))

    matches = [
        (network, target)
        for network, target in validated_routes
        if destination in network
    ]

    if not matches:
        return {
            "decision": "DENY",
            "matched_route": None,
            "target": None,
            "reason": "No route matches the destination.",
            "next_step": "Add an appropriate route if this traffic is required.",
        }

    network, target = max(matches, key=lambda item: item[0].prefixlen)

    if target.lower() == "blackhole":
        return {
            "decision": "DENY",
            "matched_route": network.with_prefixlen,
            "target": target,
            "reason": "The selected route is marked as a blackhole.",
            "next_step": "Repair or remove the unavailable route target.",
        }

    if target == "igw":
        return {
            "decision": "ROUTE",
            "matched_route": network.with_prefixlen,
            "target": target,
            "reason": "The selected route points to an Internet Gateway.",
            "next_step": (
                "Check public IPv4 addressing, security groups, network ACLs, "
                "and gateway configuration before concluding connectivity works."
            ),
        }

    if target == "nat":
        return {
            "decision": "ROUTE",
            "matched_route": network.with_prefixlen,
            "target": target,
            "reason": "The selected route points to a NAT Gateway.",
            "next_step": (
                "Check NAT Gateway availability, its public subnet route, "
                "and security controls. NAT does not provide unsolicited "
                "inbound internet access."
            ),
        }

    return {
        "decision": "ROUTE",
        "matched_route": network.with_prefixlen,
        "target": target,
        "reason": "A matching route was found.",
        "next_step": (
            "Verify that the route target exists and that security controls "
            "permit the traffic."
        ),
    }
