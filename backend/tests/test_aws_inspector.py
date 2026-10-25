from app.services import aws_inspector


class FakeEC2Client:
    def describe_vpcs(self, **kwargs):
        return {
            "Vpcs": [{
                "VpcId": "vpc-0123456789abcdef0",
                "CidrBlock": "10.0.0.0/16",
                "State": "available",
                "IsDefault": False,
                "Tags": [{"Key": "Project", "Value": "CLOUDGUARD"}],
            }]
        }

    def describe_subnets(self, **kwargs):
        return {
            "Subnets": [
                {
                    "SubnetId": "subnet-public",
                    "CidrBlock": "10.0.0.0/24",
                    "AvailabilityZone": "ap-south-1a",
                    "State": "available",
                    "MapPublicIpOnLaunch": False,
                    "Tags": [],
                },
                {
                    "SubnetId": "subnet-private",
                    "CidrBlock": "10.0.1.0/24",
                    "AvailabilityZone": "ap-south-1b",
                    "State": "available",
                    "MapPublicIpOnLaunch": False,
                    "Tags": [],
                },
            ]
        }

    def describe_route_tables(self, **kwargs):
        return {
            "RouteTables": [
                {
                    "RouteTableId": "rtb-public",
                    "Routes": [
                        {
                            "DestinationCidrBlock": "10.0.0.0/16",
                            "GatewayId": "local",
                            "State": "active",
                        },
                        {
                            "DestinationCidrBlock": "0.0.0.0/0",
                            "GatewayId": "igw-example",
                            "State": "active",
                        },
                    ],
                    "Associations": [
                        {"SubnetId": "subnet-public", "Main": False}
                    ],
                },
                {
                    "RouteTableId": "rtb-private",
                    "Routes": [
                        {
                            "DestinationCidrBlock": "10.0.0.0/16",
                            "GatewayId": "local",
                            "State": "active",
                        }
                    ],
                    "Associations": [
                        {"SubnetId": "subnet-private", "Main": False}
                    ],
                },
            ]
        }

    def describe_internet_gateways(self, **kwargs):
        return {
            "InternetGateways": [{
                "InternetGatewayId": "igw-example",
                "Attachments": [{
                    "VpcId": "vpc-0123456789abcdef0",
                    "State": "available",
                }],
            }]
        }

    def describe_security_groups(self, **kwargs):
        return {
            "SecurityGroups": [{
                "GroupId": "sg-example",
                "GroupName": "cloudguard-test",
                "Description": "Test security group",
                "IpPermissions": [{
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    "Ipv6Ranges": [],
                    "UserIdGroupPairs": [],
                    "PrefixListIds": [],
                }],
                "IpPermissionsEgress": [{
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    "Ipv6Ranges": [],
                    "UserIdGroupPairs": [],
                    "PrefixListIds": [],
                }],
            }]
        }


def test_inspect_vpc_classifies_routes_and_reports_public_ssh(monkeypatch):
    monkeypatch.setattr(
        aws_inspector.boto3,
        "client",
        lambda *args, **kwargs: FakeEC2Client(),
    )

    result = aws_inspector.inspect_vpc(
        "vpc-0123456789abcdef0",
        "ap-south-1",
    )

    assert result["read_only"] is True
    assert result["vpc"]["cidr"] == "10.0.0.0/16"
    assert result["summary"]["subnet_count"] == 2
    assert result["summary"]["subnets_with_igw_default_route"] == 1

    by_id = {item["subnet_id"]: item for item in result["subnets"]}
    assert by_id["subnet-public"]["route_access"] == "public_route"
    assert by_id["subnet-private"]["route_access"] == "private_or_internal_route"

    assert any(
        finding["code"] == "PUBLIC_REMOTE_ADMIN"
        and finding["severity"] == "HIGH"
        for finding in result["findings"]
    )


def test_invalid_vpc_id_is_rejected_before_aws_call():
    try:
        aws_inspector.inspect_vpc("not-a-vpc", "ap-south-1")
    except aws_inspector.AwsInspectionError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Invalid VPC ID should be rejected.")