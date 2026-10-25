import ipaddress
import re
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class AwsInspectionError(Exception):
    """An expected, user-safe error during AWS inspection."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _route_target(route: dict[str, Any]) -> str:
    """Return the most relevant AWS target field for a route."""
    for key in (
        "GatewayId",
        "NatGatewayId",
        "TransitGatewayId",
        "NetworkInterfaceId",
        "InstanceId",
        "VpcPeeringConnectionId",
        "EgressOnlyInternetGatewayId",
        "LocalGatewayId",
        "CarrierGatewayId",
        "CoreNetworkArn",
    ):
        if route.get(key):
            return str(route[key])
    return "unknown"


def _route_summary(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "destination": (
            route.get("DestinationCidrBlock")
            or route.get("DestinationIpv6CidrBlock")
            or route.get("DestinationPrefixListId")
            or "unknown"
        ),
        "target": _route_target(route),
        "state": route.get("State", "unknown"),
        "origin": route.get("Origin", "unknown"),
    }


def _route_table_has_public_default(route_table: dict[str, Any]) -> bool:
    """A public default route requires an active IPv4 default route to an IGW."""
    return any(
        route.get("DestinationCidrBlock") == "0.0.0.0/0"
        and str(route.get("GatewayId", "")).startswith("igw-")
        and route.get("State") == "active"
        for route in route_table.get("Routes", [])
    )


def _permission_summary(permission: dict[str, Any]) -> dict[str, Any]:
    protocol_value = str(permission.get("IpProtocol", "-1"))
    protocol_names = {
        "-1": "all",
        "1": "icmp",
        "6": "tcp",
        "17": "udp",
        "58": "icmpv6",
    }

    if protocol_value == "-1":
        port_range: str | None = "all"
    elif "FromPort" in permission or "ToPort" in permission:
        start = permission.get("FromPort", "?")
        end = permission.get("ToPort", "?")
        port_range = str(start) if start == end else f"{start}-{end}"
    else:
        port_range = None

    sources: list[dict[str, str]] = []

    for item in permission.get("IpRanges", []):
        sources.append({
            "type": "ipv4",
            "value": item.get("CidrIp", "unknown"),
            "description": item.get("Description", ""),
        })

    for item in permission.get("Ipv6Ranges", []):
        sources.append({
            "type": "ipv6",
            "value": item.get("CidrIpv6", "unknown"),
            "description": item.get("Description", ""),
        })

    for item in permission.get("PrefixListIds", []):
        sources.append({
            "type": "prefix_list",
            "value": item.get("PrefixListId", "unknown"),
            "description": item.get("Description", ""),
        })

    for item in permission.get("UserIdGroupPairs", []):
        sources.append({
            "type": "security_group",
            "value": item.get("GroupId", "unknown"),
            "description": item.get("Description", ""),
        })

    return {
        "protocol": protocol_names.get(protocol_value, protocol_value),
        "from_port": permission.get("FromPort"),
        "to_port": permission.get("ToPort"),
        "port_range": port_range,
        "sources": sources,
    }


def _security_group_findings(
    group: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    group_id = group.get("GroupId", "unknown")
    public_cidrs = {"0.0.0.0/0", "::/0"}

    for index, permission in enumerate(group.get("IpPermissions", [])):
        protocol = str(permission.get("IpProtocol", "-1"))
        start = permission.get("FromPort")
        end = permission.get("ToPort")

        sources = [
            item.get("CidrIp")
            for item in permission.get("IpRanges", [])
        ] + [
            item.get("CidrIpv6")
            for item in permission.get("Ipv6Ranges", [])
        ]

        for cidr in sources:
            if cidr not in public_cidrs:
                continue

            def includes_port(port: int) -> bool:
                if protocol == "-1":
                    return True
                if start is None or end is None:
                    return False
                return start <= port <= end

            if protocol == "-1":
                severity = "HIGH"
                code = "PUBLIC_ALL_PROTOCOLS"
                title = "All inbound protocols exposed publicly"
                recommendation = (
                    "Restrict inbound sources and protocols to the minimum "
                    "required by the workload."
                )
            elif includes_port(22) or includes_port(3389):
                severity = "HIGH"
                code = "PUBLIC_REMOTE_ADMIN"
                title = "SSH or RDP exposed publicly"
                recommendation = (
                    "Remove public SSH/RDP access. Use a controlled "
                    "administration path and trusted source ranges."
                )
            elif any(includes_port(port) for port in (3306, 5432, 1433, 1521, 27017)):
                severity = "HIGH"
                code = "PUBLIC_DATABASE_PORT"
                title = "Database port exposed publicly"
                recommendation = (
                    "Limit database ingress to approved application "
                    "sources or trusted private networks."
                )
            else:
                severity = "MEDIUM"
                code = "PUBLIC_INGRESS"
                title = "Inbound rule permits a public source"
                recommendation = (
                    "Review whether internet-wide access is necessary "
                    "and restrict the source CIDR where possible."
                )

            findings.append({
                "severity": severity,
                "code": code,
                "title": title,
                "resource_id": group_id,
                "rule_index": str(index),
                "source": str(cidr),
                "recommendation": recommendation,
            })

    for index, permission in enumerate(group.get("IpPermissionsEgress", [])):
        if str(permission.get("IpProtocol", "-1")) != "-1":
            continue

        sources = [
            item.get("CidrIp")
            for item in permission.get("IpRanges", [])
        ] + [
            item.get("CidrIpv6")
            for item in permission.get("Ipv6Ranges", [])
        ]

        for cidr in sources:
            if cidr in public_cidrs:
                findings.append({
                    "severity": "MEDIUM",
                    "code": "UNRESTRICTED_EGRESS",
                    "title": "All outbound protocols permitted to a public destination",
                    "resource_id": group_id,
                    "rule_index": str(index),
                    "source": str(cidr),
                    "recommendation": (
                        "Restrict outbound protocols and destinations "
                        "to the application's documented requirements."
                    ),
                })

    return findings


def inspect_vpc(vpc_id: str, region: str = "ap-south-1") -> dict[str, Any]:
    """
    Inspect an existing VPC using read-only EC2 Describe APIs.
    This function never creates, changes, or deletes AWS resources.
    """
    if not re.fullmatch(r"vpc-[0-9a-f]+", vpc_id or ""):
        raise AwsInspectionError(
            "Invalid VPC ID format. Expected an ID such as vpc-0123456789abcdef0.",
            422,
        )

    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region or ""):
        raise AwsInspectionError("Invalid AWS region format.", 422)

    try:
        ec2 = boto3.client("ec2", region_name=region)

        vpc_response = ec2.describe_vpcs(VpcIds=[vpc_id])
        vpcs = vpc_response.get("Vpcs", [])
        if not vpcs:
            raise AwsInspectionError(
                f"VPC {vpc_id} was not found in region {region}.",
                404,
            )

        vpc = vpcs[0]

        subnet_response = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        subnet_items = subnet_response.get("Subnets", [])

        route_response = ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        route_items = route_response.get("RouteTables", [])

        igw_response = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )
        igw_items = igw_response.get("InternetGateways", [])

        sg_response = ec2.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        sg_items = sg_response.get("SecurityGroups", [])

    except AwsInspectionError:
        raise
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = error.get("Code", "AWSClientError")

        if code in {"InvalidVpcID.NotFound", "InvalidVpcID.Malformed"}:
            raise AwsInspectionError(
                f"AWS could not find VPC {vpc_id} in {region}.",
                404,
            ) from exc

        if code in {"UnauthorizedOperation", "AccessDenied", "AccessDeniedException"}:
            raise AwsInspectionError(
                "AWS denied the inspection request. Check that the configured "
                "identity has EC2 Describe permissions for this region.",
                403,
            ) from exc

        raise AwsInspectionError(
            f"AWS inspection failed ({code}). Check the AWS CLI identity, "
            "region, and EC2 read permissions.",
            502,
        ) from exc
    except BotoCoreError as exc:
        raise AwsInspectionError(
            "Could not communicate with AWS. Check credentials, network access, "
            "and the configured region.",
            502,
        ) from exc

    route_table_by_id = {
        item["RouteTableId"]: item for item in route_items
    }

    main_route_table_id = None
    subnet_route_table: dict[str, str] = {}

    for table in route_items:
        for association in table.get("Associations", []):
            if association.get("Main"):
                main_route_table_id = table["RouteTableId"]
            if association.get("SubnetId"):
                subnet_route_table[association["SubnetId"]] = table["RouteTableId"]

    route_tables = []
    for table in route_items:
        is_public = _route_table_has_public_default(table)
        route_tables.append({
            "route_table_id": table["RouteTableId"],
            "is_main": any(
                association.get("Main")
                for association in table.get("Associations", [])
            ),
            "classification": (
                "public_default_route_to_internet_gateway"
                if is_public
                else "no_active_ipv4_default_route_to_internet_gateway"
            ),
            "routes": [
                _route_summary(route)
                for route in table.get("Routes", [])
            ],
            "associated_subnet_ids": sorted(
                association["SubnetId"]
                for association in table.get("Associations", [])
                if association.get("SubnetId")
            ),
        })

    subnets = []
    for subnet in subnet_items:
        subnet_id = subnet["SubnetId"]
        table_id = subnet_route_table.get(subnet_id, main_route_table_id)
        table = route_table_by_id.get(table_id) if table_id else None
        has_igw_default = bool(
            table and _route_table_has_public_default(table)
        )

        subnets.append({
            "subnet_id": subnet_id,
            "cidr": subnet.get("CidrBlock"),
            "availability_zone": subnet.get("AvailabilityZone"),
            "state": subnet.get("State"),
            "map_public_ip_on_launch": subnet.get("MapPublicIpOnLaunch", False),
            "route_table_id": table_id,
            "route_access": (
                "public_route" if has_igw_default else "private_or_internal_route"
            ),
            "tags": {
                tag["Key"]: tag["Value"]
                for tag in subnet.get("Tags", [])
            },
        })

    security_groups = []
    findings: list[dict[str, str]] = []

    for group in sg_items:
        inbound = [
            _permission_summary(permission)
            for permission in group.get("IpPermissions", [])
        ]
        outbound = [
            _permission_summary(permission)
            for permission in group.get("IpPermissionsEgress", [])
        ]

        group_findings = _security_group_findings(group)
        findings.extend(group_findings)

        security_groups.append({
            "group_id": group.get("GroupId"),
            "group_name": group.get("GroupName"),
            "description": group.get("Description"),
            "inbound_rules": inbound,
            "outbound_rules": outbound,
            "findings": group_findings,
        })

    public_route_subnets = sum(
        subnet["route_access"] == "public_route" for subnet in subnets
    )

    return {
        "read_only": True,
        "region": region,
        "vpc": {
            "vpc_id": vpc.get("VpcId"),
            "cidr": vpc.get("CidrBlock"),
            "state": vpc.get("State"),
            "is_default": vpc.get("IsDefault", False),
            "tags": {
                tag["Key"]: tag["Value"]
                for tag in vpc.get("Tags", [])
            },
        },
        "summary": {
            "subnet_count": len(subnets),
            "subnets_with_igw_default_route": public_route_subnets,
            "route_table_count": len(route_tables),
            "internet_gateway_count": len(igw_items),
            "security_group_count": len(security_groups),
            "security_finding_count": len(findings),
            "high_findings": sum(
                finding["severity"] == "HIGH" for finding in findings
            ),
            "medium_findings": sum(
                finding["severity"] == "MEDIUM" for finding in findings
            ),
        },
        "subnets": sorted(subnets, key=lambda item: item["cidr"] or ""),
        "route_tables": sorted(
            route_tables, key=lambda item: item["route_table_id"]
        ),
        "internet_gateways": [
            {
                "gateway_id": gateway.get("InternetGatewayId"),
                "attachments": [
                    {
                        "vpc_id": attachment.get("VpcId"),
                        "state": attachment.get("State"),
                    }
                    for attachment in gateway.get("Attachments", [])
                ],
            }
            for gateway in igw_items
        ],
        "security_groups": sorted(
            security_groups, key=lambda item: item["group_id"] or ""
        ),
        "findings": findings,
        "limitations": [
            "Read-only inventory and rule analysis; no AWS resources were modified.",
            "Route-table classification does not prove that a workload is reachable from the internet.",
            "Network ACLs, IAM policies, firewall appliances, workload state, and application health are not evaluated.",
            "Security findings are rule-based indicators and require human review.",
        ],
    }