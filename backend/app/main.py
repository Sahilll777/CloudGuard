from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.aws_inspector import AwsInspectionError, inspect_vpc
from app.services.network_engine import (
    NetworkPlanError,
    build_network_plan,
)
from app.services.routing_engine import (
    RoutingError,
    evaluate_route,
)
from app.services.security_analyzer import (
    SecurityRuleError,
    analyze_security_group,
)
from app.services.traffic_simulator import (
    TrafficSimulationError,
    simulate_traffic,
)

app = FastAPI(
    title="CLOUDGUARD API",
    description=(
        "Secure AWS network architecture, subnet planning, routing, "
        "security auditing, traffic simulation, and read-only AWS discovery."
    ),
    version="0.6.0",
)


class NetworkPlanRequest(BaseModel):
    cidr: str = "10.0.0.0/16"
    subnet_prefix: int = Field(default=24, ge=16, le=28)
    public_subnets: int = Field(default=2, ge=0, le=32)
    private_subnets: int = Field(default=2, ge=0, le=32)


class RouteEntry(BaseModel):
    destination_cidr: str
    target: str


class RouteCheckRequest(BaseModel):
    vpc_cidr: str = "10.0.0.0/16"
    destination_ip: str
    routes: list[RouteEntry] = Field(default_factory=list)


class SecurityRule(BaseModel):
    protocol: str
    cidr: str
    from_port: int | None = None
    to_port: int | None = None


class SecurityAuditRequest(BaseModel):
    group_name: str = "cloudguard-demo"
    inbound_rules: list[SecurityRule] = Field(default_factory=list)
    outbound_rules: list[SecurityRule] = Field(default_factory=list)


class TrafficSimulationRequest(BaseModel):
    vpc_cidr: str = "10.0.0.0/16"
    source_ip: str
    destination_ip: str
    protocol: str = "tcp"
    destination_port: int | None = None
    routes: list[RouteEntry] = Field(default_factory=list)
    inbound_rules: list[SecurityRule] = Field(default_factory=list)
    outbound_rules: list[SecurityRule] = Field(default_factory=list)


@app.get("/", tags=["System"])
def root() -> dict[str, str]:
    return {
        "name": "CLOUDGUARD",
        "description": "Secure AWS Network Architect",
        "version": "0.6.0",
        "status": "operational",
    }


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "cloudguard-api"}


@app.post("/api/network/plan", tags=["Network Planning"])
def create_network_plan(request: NetworkPlanRequest) -> dict:
    try:
        return build_network_plan(
            cidr=request.cidr,
            subnet_prefix=request.subnet_prefix,
            public_subnets=request.public_subnets,
            private_subnets=request.private_subnets,
        )
    except NetworkPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/network/route-check", tags=["Routing"])
def check_route(request: RouteCheckRequest) -> dict:
    try:
        return evaluate_route(
            request.vpc_cidr,
            request.destination_ip,
            [route.model_dump() for route in request.routes],
        )
    except RoutingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/security/audit", tags=["Security Audit"])
def audit_security_group(request: SecurityAuditRequest) -> dict:
    try:
        return analyze_security_group(
            request.group_name,
            [rule.model_dump() for rule in request.inbound_rules],
            [rule.model_dump() for rule in request.outbound_rules],
        )
    except SecurityRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/traffic/simulate", tags=["Traffic Simulation"])
def simulate_network_traffic(request: TrafficSimulationRequest) -> dict:
    try:
        return simulate_traffic(
            vpc_cidr=request.vpc_cidr,
            source_ip=request.source_ip,
            destination_ip=request.destination_ip,
            protocol=request.protocol,
            destination_port=request.destination_port,
            routes=[route.model_dump() for route in request.routes],
            inbound_rules=[
                rule.model_dump() for rule in request.inbound_rules
            ],
            outbound_rules=[
                rule.model_dump() for rule in request.outbound_rules
            ],
        )
    except TrafficSimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/aws/discovery", tags=["Live AWS"])
def discover_aws_network(
    vpc_id: str = Query(
        ...,
        description="Existing VPC ID to inspect, for example vpc-0123456789abcdef0.",
    ),
    region: str = Query(
        default="ap-south-1",
        description="AWS region containing the VPC.",
    ),
) -> dict:
    """Read the actual AWS network configuration without changing resources."""
    try:
        return inspect_vpc(vpc_id=vpc_id, region=region)
    except AwsInspectionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc