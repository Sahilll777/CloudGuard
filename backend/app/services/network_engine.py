from ipaddress import IPv4Network, ip_network
from itertools import islice


class NetworkPlanError(ValueError):
    """Raised when a requested network plan is invalid."""


def build_network_plan(
    cidr: str,
    subnet_prefix: int = 24,
    public_subnets: int = 2,
    private_subnets: int = 2,
) -> dict:
    """Create a validated IPv4 subnet allocation plan."""

    try:
        network = ip_network(cidr, strict=True)
    except ValueError as exc:
        raise NetworkPlanError(
            f"Invalid VPC CIDR '{cidr}': {exc}"
        ) from exc

    if not isinstance(network, IPv4Network):
        raise NetworkPlanError("Only IPv4 VPC networks are supported.")

    if not 16 <= network.prefixlen <= 28:
        raise NetworkPlanError(
            "AWS VPC IPv4 CIDR prefixes must be between /16 and /28."
        )

    if not isinstance(subnet_prefix, int) or isinstance(subnet_prefix, bool):
        raise NetworkPlanError("Subnet prefix must be an integer.")

    if not network.prefixlen <= subnet_prefix <= 28:
        raise NetworkPlanError(
            "Subnet prefix must be equal to or longer than the VPC prefix, "
            "and between /16 and /28."
        )

    for name, count in (
        ("public_subnets", public_subnets),
        ("private_subnets", private_subnets),
    ):
        if not isinstance(count, int) or isinstance(count, bool):
            raise NetworkPlanError(f"{name} must be an integer.")
        if not 0 <= count <= 32:
            raise NetworkPlanError(f"{name} must be between 0 and 32.")

    total_requested = public_subnets + private_subnets

    if total_requested == 0:
        raise NetworkPlanError(
            "At least one public or private subnet must be requested."
        )

    available = 1 << (subnet_prefix - network.prefixlen)

    if total_requested > available:
        raise NetworkPlanError(
            f"Requested {total_requested} subnets, but only "
            f"{available} subnet(s) of /{subnet_prefix} fit inside "
            f"{network.with_prefixlen}."
        )

    allocated = list(
        islice(network.subnets(new_prefix=subnet_prefix), total_requested)
    )

    results = []
    index = 0

    for subnet_type, count in (
        ("public", public_subnets),
        ("private", private_subnets),
    ):
        for _ in range(count):
            subnet = allocated[index]
            index += 1

            results.append(
                {
                    "name": f"{subnet_type}-subnet-{sum(
                        1 for item in results
                        if item['type'] == subnet_type
                    ) + 1}",
                    "type": subnet_type,
                    "cidr": subnet.with_prefixlen,
                    "availability_zone_index": (
                        sum(1 for item in results if item["type"] == subnet_type)
                        % 2
                    ),
                    "total_ipv4_addresses": subnet.num_addresses,
                    "aws_usable_ipv4_addresses": max(
                        0, subnet.num_addresses - 5
                    ),
                }
            )

    return {
        "vpc_cidr": network.with_prefixlen,
        "vpc_prefix": network.prefixlen,
        "subnet_prefix": subnet_prefix,
        "total_subnets": total_requested,
        "available_subnet_capacity": available,
        "remaining_subnet_capacity": available - total_requested,
        "subnets": results,
        "notes": [
            "Public subnet routing requires an internet gateway and "
            "an appropriate route table.",
            "Private subnets do not become private through their names alone; "
            "their routes and associated controls determine connectivity.",
            "AWS reserves five IPv4 addresses in each subnet."
        ],
    }
