import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, Bell, Check,
  ChevronDown, ChevronRight, CircleAlert, Cloud, Command,
  ExternalLink, FileSearch, Globe, LayoutDashboard, LockKeyhole,
  Menu, Network, RefreshCw, Router, Search, Server, Shield,
  ShieldAlert, ShieldCheck, SlidersHorizontal, X, Zap
} from "lucide-react";

const DEFAULT_VPC = "vpc-0bdc314ca640c3be0";
const DEFAULT_REGION = "ap-south-1";

function shortId(value = "", start = 15) {
  return value.length > start + 5
    ? `${value.slice(0, start)}…${value.slice(-4)}`
    : value;
}

function tagName(resource) {
  return resource?.tags?.Name || resource?.name || "";
}

function formatTime(value) {
  if (!value) return "Awaiting scan";
  return value.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function Status({ children, tone = "neutral" }) {
  return (
    <span className={`status status-${tone}`}>
      <i />
      {children}
    </span>
  );
}

function SectionTitle({ eyebrow, title, action }) {
  return (
    <div className="section-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
      </div>
      {action}
    </div>
  );
}

function Metric({ label, value, detail, icon: Icon, tone = "default", featured = false }) {
  return (
    <article className={`metric ${featured ? "metric-featured" : ""}`}>
      <div className={`metric-symbol symbol-${tone}`}><Icon size={17} /></div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? "—"}</div>
      <div className="metric-detail">{detail}</div>
    </article>
  );
}

function EmptyState({ children }) {
  return <div className="empty-state">{children}</div>;
}

function App() {
  const [vpcId, setVpcId] = useState(DEFAULT_VPC);
  const [region, setRegion] = useState(DEFAULT_REGION);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [search, setSearch] = useState("");
  const [activePage, setActivePage] = useState("Overview");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedFinding, setExpandedFinding] = useState(null);
  const [expandedRoute, setExpandedRoute] = useState(null);
  const [selectedSubnet, setSelectedSubnet] = useState(null);
  const [selectedGateway, setSelectedGateway] = useState(null);
  const [showRegionEditor, setShowRegionEditor] = useState(false);
  const [draftVpc, setDraftVpc] = useState(DEFAULT_VPC);
  const [draftRegion, setDraftRegion] = useState(DEFAULT_REGION);

  const discover = useCallback(async () => {
    if (!vpcId.trim() || !region.trim()) {
      setError("A VPC ID and AWS region are required.");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const params = new URLSearchParams({
        vpc_id: vpcId.trim(),
        region: region.trim()
      });

      const response = await fetch(`/api/aws/discovery?${params.toString()}`);

      if (!response.ok) {
        let message = `Discovery failed with HTTP ${response.status}.`;
        try {
          const body = await response.json();
          if (body.detail) {
            message = typeof body.detail === "string"
              ? body.detail
              : JSON.stringify(body.detail);
          }
        } catch {
          // Keep the original HTTP error.
        }
        throw new Error(message);
      }

      const result = await response.json();
      setData(result);
      setLastUpdated(new Date());
    } catch (err) {
      setError(
        `${err.message || "Unable to reach the discovery API."} Check that FastAPI is running on port 8001.`
      );
    } finally {
      setLoading(false);
    }
  }, [vpcId, region]);

  useEffect(() => {
    discover();
  }, [discover]);

  const vpc = data?.vpc ?? {};
  const summary = data?.summary ?? {};
  const subnets = data?.subnets ?? [];
  const routeTables = data?.route_tables ?? [];
  const selectedSubnetRouteTable = selectedSubnet
    ? routeTables.find(
        (table) => table.route_table_id === selectedSubnet.route_table_id
      ) ?? null
    : null;
  const selectedSubnetRoutes = selectedSubnetRouteTable?.routes ?? [];
  const hasActiveIgwDefaultRoute = selectedSubnetRoutes.some(
    (route) =>
      route.destination === "0.0.0.0/0" &&
      String(route.target ?? "").startsWith("igw-") &&
      String(route.state ?? "").toLowerCase() === "active"
  );
  const autoPublicIpv4Enabled = Boolean(
    selectedSubnet?.map_public_ip_on_launch
  );

  const subnetExposureAssessment = !selectedSubnet
    ? null
    : hasActiveIgwDefaultRoute && autoPublicIpv4Enabled
      ? {
          tone: "warning",
          title: "Review recommended",
          summary: "Both common IPv4 exposure indicators are present.",
          evidence: "An active 0.0.0.0/0 route targets an internet gateway, and automatic public IPv4 assignment is enabled."
        }
      : hasActiveIgwDefaultRoute
        ? {
            tone: "warning",
            title: "Internet route detected",
            summary: "The subnet has an active IPv4 default route to an internet gateway.",
            evidence: "Automatic public IPv4 assignment is disabled. This does not rule out public addressing configured elsewhere."
          }
        : autoPublicIpv4Enabled
          ? {
              tone: "warning",
              title: "Review subnet configuration",
              summary: "Automatic public IPv4 assignment is enabled, but no active IPv4 default route to an internet gateway was found in the associated route table.",
              evidence: "Check the route table and any other relevant network controls before drawing conclusions."
            }
          : {
              tone: "neutral",
              title: "No common IPv4 indicators detected",
              summary: "Neither an active IPv4 internet-gateway default route nor automatic public IPv4 assignment was detected.",
              evidence: "This is not proof that the subnet or its workloads are unreachable from the internet."
            };
  const gateways = data?.internet_gateways ?? [];
  const selectedPathRoutes = selectedSubnetRouteTable?.routes ?? [];
  const selectedPathGatewayIds = [
    ...new Set(
      selectedPathRoutes
        .filter(
          (route) =>
            String(route.state ?? "").toLowerCase() === "active" &&
            String(route.target ?? "").startsWith("igw-")
        )
        .map((route) => route.target)
    )
  ];
  const selectedPathGateways = gateways.filter((gateway) =>
    selectedPathGatewayIds.includes(gateway.gateway_id)
  );
  const securityGroups = data?.security_groups ?? [];
  const findings = data?.findings ?? [];

  const publicSubnets = subnets.filter(
    (item) => item.route_access === "public_route"
  );
  const internalSubnets = subnets.filter(
    (item) => item.route_access !== "public_route"
  );

  const highCount = summary.high_findings ??
    findings.filter((item) => String(item.severity).toLowerCase() === "high").length;

  const mediumCount = summary.medium_findings ??
    findings.filter((item) => String(item.severity).toLowerCase() === "medium").length;

  const findingCount = summary.security_finding_count ?? findings.length;

  const filteredSubnets = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return subnets;

    return subnets.filter((item) =>
      [
        item.subnet_id,
        item.cidr,
        item.availability_zone,
        item.route_access,
        item.route_table_id,
        tagName(item)
      ].some((value) => String(value ?? "").toLowerCase().includes(term))
    );
  }, [subnets, search]);

  const navigation = [
    { label: "Overview", icon: LayoutDashboard, target: "overview" },
    { label: "Network topology", icon: Network, target: "topology" },
    { label: "Assets & routes", icon: Server, target: "assets" },
    { label: "Security findings", icon: ShieldAlert, target: "findings" },
    { label: "Security groups", icon: ShieldCheck, target: "groups" }
  ];

  function navigate(item) {
    setActivePage(item.label);
    setMobileOpen(false);
    document.getElementById(item.target)?.scrollIntoView({
      behavior: "smooth",
      block: "start"
    });
  }

  function applyTarget() {
    setVpcId(draftVpc.trim());
    setRegion(draftRegion.trim());
    setShowRegionEditor(false);
  }

  function findingTone(severity) {
    const value = String(severity ?? "").toLowerCase();
    if (value === "critical" || value === "high") return "red";
    if (value === "medium") return "orange";
    if (value === "low") return "yellow";
    return "blue";
  }

  function routesFor(table) {
    return Array.isArray(table.routes) ? table.routes : [];
  }

  return (
    <div className="terminal-shell">
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-icon"><Shield size={23} strokeWidth={2.2} /></div>
          <div className="brand-copy">
            <strong>CLOUDGUARD</strong>
            <span>SECURITY INTELLIGENCE</span>
          </div>
          <button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
            <X size={17} />
          </button>
        </div>

        <div className="sidebar-version">NETWORK ARCHITECT <span>v1.0</span></div>

        <div className="nav-caption">WORKSPACE</div>
        <div className="environment-card">
          <div className="environment-icon"><Cloud size={17} /></div>
          <div className="environment-copy">
            <strong>AWS network lab</strong>
            <span>{region}</span>
          </div>
          <span className="online-indicator" />
        </div>

        <div className="nav-caption nav-caption-main">INTELLIGENCE</div>
        <nav className="sidebar-nav">
          {navigation.map(({ label, icon: Icon, target }) => (
            <button
              key={label}
              className={`nav-link ${activePage === label ? "nav-link-active" : ""}`}
              onClick={() => navigate({ label, target })}
            >
              <Icon size={17} />
              <span>{label}</span>
              {activePage === label && <ChevronRight size={14} className="nav-arrow" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-spacer" />

        <div className="read-only-box">
          <div className="read-only-heading"><LockKeyhole size={14} /> READ-ONLY MODE</div>
          <p>Discovery uses AWS describe operations. No infrastructure changes are applied.</p>
          <div className="read-only-status"><span /> INSPECTION ENABLED</div>
        </div>

        <div className="sidebar-profile">
          <div className="profile-mark"><Shield size={18} /></div>
          <div className="profile-copy">
            <strong>CloudGuard Lab</strong>
            <span>Local environment</span>
          </div>
          <SlidersHorizontal size={15} className="profile-settings" />
        </div>
      </aside>

      {mobileOpen && (
        <button className="mobile-backdrop" onClick={() => setMobileOpen(false)} aria-label="Close menu" />
      )}

      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumb">
            <button className="icon-button mobile-menu-button" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
              <Menu size={19} />
            </button>
            <span>ENVIRONMENTS</span>
            <ChevronRight size={13} />
            <strong>Network intelligence</strong>
          </div>

          <div className="topbar-right">
            <div className="read-only-chip"><span /> AWS DISCOVERY</div>
            <button className="icon-button topbar-bell" aria-label="Security status" title="Read-only discovery status">
              <Bell size={17} />
              {findingCount > 0 && <i />}
            </button>
            <div className="user-badge">CG</div>
          </div>
        </header>

        <div className="dashboard">
          <section className="page-heading">
            <div>
              <div className="page-eyebrow"><span className="pulse-dot" /> CLOUD SECURITY / NETWORK POSTURE</div>
              <h1>Network intelligence<span>.</span></h1>
              <p>Investigate your cloud network, routing configuration and security exposure.</p>
            </div>
            <div className="heading-actions">
              <button className="button-outline" onClick={() => {
                setDraftVpc(vpcId);
                setDraftRegion(region);
                setShowRegionEditor((value) => !value);
              }}>
                <SlidersHorizontal size={15} /> Target
              </button>
              <button className="button-primary" onClick={discover} disabled={loading}>
                <RefreshCw size={15} className={loading ? "spin" : ""} />
                {loading ? "Scanning" : "Refresh scan"}
              </button>
            </div>
          </section>

          {showRegionEditor && (
            <section className="target-editor panel">
              <div className="target-editor-title">
                <div><div className="eyebrow">SCAN TARGET</div><h2>Discovery scope</h2></div>
                <button className="icon-button" onClick={() => setShowRegionEditor(false)} aria-label="Close target editor"><X size={17} /></button>
              </div>
              <div className="target-fields">
                <label>VPC ID<input value={draftVpc} onChange={(event) => setDraftVpc(event.target.value)} placeholder="vpc-..." /></label>
                <label>AWS region<input value={draftRegion} onChange={(event) => setDraftRegion(event.target.value)} placeholder="ap-south-1" /></label>
                <button className="button-primary" onClick={applyTarget}><Check size={15} /> Apply target</button>
              </div>
              <p className="muted-note">Changes the discovery query only. No AWS resources are created or modified.</p>
            </section>
          )}

          <section className="scan-banner">
            <div className="scan-banner-left">
              <div className="scan-cloud"><Cloud size={19} /></div>
              <div>
                <div className="scan-title">AWS network discovery <Status tone={error ? "red" : loading ? "yellow" : "green"}>{error ? "Connection issue" : loading ? "Scanning" : "Connected"}</Status></div>
                <div className="scan-description">EC2 Describe APIs <span>·</span> Read-only inspection <span>·</span> {region}</div>
              </div>
            </div>
            <div className="scan-timestamp"><span>LAST SCAN</span><strong>{formatTime(lastUpdated)}</strong></div>
          </section>

          {error && (
            <section className="error-banner">
              <CircleAlert size={19} />
              <div><strong>Discovery unsuccessful</strong><p>{error}</p></div>
              <button className="button-outline" onClick={discover}>Retry</button>
            </section>
          )}

          <section className="metrics-grid">
            <Metric
              label="VPC NETWORKS"
              value={data ? "01" : "—"}
              detail={vpc.cidr || "Waiting for discovery"}
              icon={Network}
              tone="orange"
              featured
            />
            <Metric
              label="SUBNETS DISCOVERED"
              value={summary.subnet_count ?? (data ? subnets.length : "—")}
              detail={`${publicSubnets.length} IGW routes · ${internalSubnets.length} internal`}
              icon={Server}
              tone="red"
            />
            <Metric
              label="ROUTE TABLES"
              value={summary.route_table_count ?? (data ? routeTables.length : "—")}
              detail="Routing configuration inspected"
              icon={Router}
              tone="blue"
            />
            <Metric
              label="SECURITY FINDINGS"
              value={findingCount}
              detail={`${highCount} high · ${mediumCount} medium`}
              icon={ShieldAlert}
              tone={highCount > 0 ? "red" : "orange"}
            />
          </section>

          <section className="overview-grid" id="topology">
            <article className="panel network-panel">
              <SectionTitle
                eyebrow="01 / NETWORK MAP"
                title="Network topology"
                action={<span className="micro-label"><Activity size={13} /> LIVE INVENTORY</span>}
              />

              <div className="network-map">
                <div className="internet-node"><Globe size={17} /><span>Internet</span></div>
                <div className="map-connector" />
                <div className="gateway-node">
                  <ExternalLink size={15} />
                  <div><strong>Internet Gateway</strong><span>{gateways.length} attached</span></div>
                </div>
                <div className="map-connector" />

                <div className="vpc-frame">
                  <div className="vpc-frame-heading">
                    <div className="vpc-frame-symbol"><Network size={16} /></div>
                    <div className="vpc-frame-copy">
                      <strong>{tagName(vpc) || shortId(vpc.vpc_id || "VPC network", 20)}</strong>
                      <span>{vpc.vpc_id || "VPC ID unavailable"} · {vpc.cidr || "CIDR unavailable"}</span>
                    </div>
                    <Status tone={vpc.state === "available" ? "green" : "neutral"}>{vpc.state || "Pending"}</Status>
                  </div>

                  <div className="zones-grid">
                    <div className="zone zone-public">
                      <div className="zone-heading">
                        <span className="zone-symbol"><Globe size={14} /></span>
                        <strong>IGW DEFAULT ROUTE</strong>
                        <b>{publicSubnets.length}</b>
                      </div>
                      {publicSubnets.map((subnet) => (
                        <div
                          className={`subnet-card topology-subnet-card ${
                            selectedSubnet?.subnet_id === subnet.subnet_id
                              ? "topology-subnet-selected"
                              : ""
                          }`}
                          key={subnet.subnet_id}
                          role="button"
                          tabIndex={0}
                          aria-pressed={selectedSubnet?.subnet_id === subnet.subnet_id}
                          aria-label={`Inspect subnet ${tagName(subnet) || subnet.subnet_id}`}
                          onClick={() => setSelectedSubnet(subnet)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedSubnet(subnet);
                            }
                          }}
                        >
                          <div className="subnet-symbol subnet-public"><Server size={14} /></div>
                          <div className="subnet-info">
                            <strong>{tagName(subnet) || shortId(subnet.subnet_id)}</strong>
                            <span>{subnet.cidr} · {subnet.availability_zone}</span>
                          </div>
                          <span className="small-state orange-state" />
                        </div>
                      ))}
                      {data && publicSubnets.length === 0 && <EmptyState>No matching routes.</EmptyState>}
                    </div>

                    <div className="zone zone-private">
                      <div className="zone-heading">
                        <span className="zone-symbol"><LockKeyhole size={14} /></span>
                        <strong>INTERNAL ROUTE</strong>
                        <b>{internalSubnets.length}</b>
                      </div>
                      {internalSubnets.map((subnet) => (
                        <div
                          className={`subnet-card topology-subnet-card ${
                            selectedSubnet?.subnet_id === subnet.subnet_id
                              ? "topology-subnet-selected"
                              : ""
                          }`}
                          key={subnet.subnet_id}
                          role="button"
                          tabIndex={0}
                          aria-pressed={selectedSubnet?.subnet_id === subnet.subnet_id}
                          aria-label={`Inspect subnet ${tagName(subnet) || subnet.subnet_id}`}
                          onClick={() => setSelectedSubnet(subnet)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedSubnet(subnet);
                            }
                          }}
                        >
                          <div className="subnet-symbol subnet-private"><Server size={14} /></div>
                          <div className="subnet-info">
                            <strong>{tagName(subnet) || shortId(subnet.subnet_id)}</strong>
                            <span>{subnet.cidr} · {subnet.availability_zone}</span>
                          </div>
                          <span className="small-state blue-state" />
                        </div>
                      ))}
                      {data && internalSubnets.length === 0 && <EmptyState>No internal routes.</EmptyState>}
                    </div>
                  </div>
                </div>

                <div className="map-legend">
                  <span><i className="legend-orange" /> IGW default route</span>
                  <span><i className="legend-blue" /> No IGW default route</span>
                </div>
              </div>
              <section className="network-path-analysis" aria-label="Network path analysis">
                <div className="network-path-heading">
                  <div>
                    <span className="eyebrow">NETWORK PATH ANALYSIS / SELECTED SUBNET</span>
                    <h3>Trace the configuration path</h3>
                    <p>
                      Follow the selected subnet to its associated route table and inspect
                      the configured destinations.
                    </p>
                  </div>
                  <Status tone={selectedSubnet ? "blue" : "neutral"}>
                    {selectedSubnet ? "Subnet selected" : "Awaiting selection"}
                  </Status>
                </div>

                {!selectedSubnet ? (
                  <div className="network-path-empty">
                    Select a subnet from the topology map to inspect its network path.
                  </div>
                ) : (
                  <>
                    <div className="network-path-chain">
                      <div className="network-path-node">
                        <span className="network-path-node-icon"><Network size={15} /></span>
                        <span className="network-path-node-label">VPC</span>
                        <strong>{tagName(vpc) || shortId(vpc.vpc_id || "VPC unavailable")}</strong>
                        <small>{vpc.cidr || "CIDR unavailable"}</small>
                      </div>
                      <div className="network-path-connector"><span>contains</span><i /></div>
                      <div className="network-path-node">
                        <span className="network-path-node-icon"><Server size={15} /></span>
                        <span className="network-path-node-label">SELECTED SUBNET</span>
                        <strong>{tagName(selectedSubnet) || shortId(selectedSubnet.subnet_id)}</strong>
                        <small>{selectedSubnet.cidr || "CIDR unavailable"}</small>
                      </div>
                      <div className="network-path-connector"><span>associated route table</span><i /></div>
                      <button
                        type="button"
                        className="network-path-node network-path-node-button"
                        disabled={!selectedSubnetRouteTable}
                        onClick={() => {
                          if (selectedSubnetRouteTable) {
                            setExpandedRoute(selectedSubnetRouteTable.route_table_id);
                          }
                        }}
                      >
                        <span className="network-path-node-icon"><Router size={15} /></span>
                        <span className="network-path-node-label">ROUTE TABLE</span>
                        <strong>
                          {selectedSubnetRouteTable
                            ? tagName(selectedSubnetRouteTable) || shortId(selectedSubnetRouteTable.route_table_id)
                            : "Not available"}
                        </strong>
                        <small>
                          {selectedSubnetRouteTable
                            ? `${selectedPathRoutes.length} configured route(s) · Click to expand below`
                            : "No matching route table was returned"}
                        </small>
                      </button>
                    </div>

                    <div className="network-path-routes-heading">
                      <strong>Route targets</strong>
                      <span>{selectedPathRoutes.length} reported</span>
                    </div>

                    {selectedPathRoutes.length > 0 ? (
                      <div className="network-path-route-list">
                        {selectedPathRoutes.map((route, index) => {
                          const targetGateway = gateways.find(
                            (gateway) => gateway.gateway_id === route.target
                          );
                          const isActiveIgwRoute =
                            String(route.state ?? "").toLowerCase() === "active" &&
                            String(route.destination ?? "") === "0.0.0.0/0" &&
                            String(route.target ?? "").startsWith("igw-");

                          return (
                            <div className="network-path-route" key={`${route.destination || "route"}-${index}`}>
                              <div className="network-path-route-main">
                                <span className="network-path-node-label">DESTINATION</span>
                                <strong>{route.destination || "Unknown destination"}</strong>
                              </div>
                              <div className="network-path-route-main">
                                <span className="network-path-node-label">TARGET</span>
                                {targetGateway ? (
                                  <button
                                    type="button"
                                    className="network-path-target-link"
                                    onClick={() => setSelectedGateway(targetGateway)}
                                  >
                                    <ExternalLink size={12} />
                                    {route.target}
                                    <span>Inspect gateway</span>
                                  </button>
                                ) : (
                                  <strong>{route.target || "Unknown target"}</strong>
                                )}
                              </div>
                              <div className="network-path-route-state">
                                <Status tone={route.state === "active" ? "green" : "orange"}>
                                  {route.state || "Unknown"}
                                </Status>
                                {isActiveIgwRoute && (
                                  <span className="network-path-route-indicator">Active IPv4 IGW default</span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="network-path-empty">
                        No route entries were returned for this subnet's associated route table.
                      </div>
                    )}

                    {selectedPathGatewayIds.length > 0 && (
                      <div className="network-path-gateway-summary">
                        <span className="network-path-node-icon"><Globe size={15} /></span>
                        <div>
                          <strong>Internet-gateway route target detected</strong>
                          <p>
                            {selectedPathGateways.length > 0
                              ? `${selectedPathGateways.length} matching gateway(s) found in discovery. Select a gateway target above to open its existing inspector.`
                              : "The route references an internet gateway, but no matching gateway was returned by discovery."}
                          </p>
                        </div>
                      </div>
                    )}

                    <p className="panel-footnote">
                      This traces reported configuration only. It does not test end-to-end
                      connectivity or evaluate every route type, network ACL, security-group
                      rule, workload address, or other control.
                    </p>
                  </>
                )}
              </section>
              <div className="panel-footnote">Route classification does not prove workload reachability. Public-route subnets may still lack public IPs.</div>
            </article>

            <article className="panel attack-panel" id="findings">
              <SectionTitle
                eyebrow="02 / THREAT INTELLIGENCE"
                title="Latest risk findings"
                action={<span className="count-badge">{findingCount} TOTAL</span>}
              />

              <div className="finding-summary">
                <div className="finding-summary-icon"><ShieldAlert size={18} /></div>
                <div className="finding-summary-copy">
                  <strong>{highCount > 0 ? "High-priority review required" : mediumCount > 0 ? "Configuration review recommended" : "No reported findings"}</strong>
                  <span>Rule-based configuration analysis</span>
                </div>
              </div>

              <div className="finding-stat-grid">
                <div><span className="severity-mark critical-mark" /><span>High</span><strong>{highCount}</strong></div>
                <div><span className="severity-mark medium-mark" /><span>Medium</span><strong>{mediumCount}</strong></div>
                <div><span className="severity-mark low-mark" /><span>Other</span><strong>{Math.max(0, findingCount - highCount - mediumCount)}</strong></div>
              </div>

              <div className="finding-list">
                {findings.map((finding, index) => {
                  const key = finding.resource_id || finding.code || String(index);
                  const expanded = expandedFinding === key;
                  const relatedGroup = securityGroups.find((group) => group.group_id === finding.resource_id);

                  return (
                    <div
                      className={`finding-item ${
                        ["critical", "high"].includes(
                          String(finding.severity || "").toLowerCase()
                        ) ? "finding-critical" : ""
                      }`}
                      key={`${key}-${index}`}
                    >
                      <button className="finding-item-button" onClick={() => setExpandedFinding(expanded ? null : key)}>
                        <span className={`finding-alert-icon alert-${findingTone(finding.severity)}`}><ShieldAlert size={15} /></span>
                        <span className="finding-item-copy">
                          <strong>{finding.title || finding.code || "Security finding"}</strong>
                          <small>{finding.code || "RULE FINDING"} · {shortId(finding.resource_id || "Resource unavailable")}</small>
                        </span>
                        <span className={`severity-pill severity-${findingTone(finding.severity)}`}>{finding.severity || "REVIEW"}</span>
                        <ChevronDown size={14} className={`finding-chevron ${expanded ? "expanded" : ""}`} />
                      </button>
                      {expanded && (
                        <div className="finding-detail">
                          <div><span>RESOURCE</span><strong>{relatedGroup?.group_name || finding.resource_id || "Not provided"}</strong></div>
                          <div><span>EVIDENCE / SOURCE</span><strong>{finding.source || "See resource rules"}</strong></div>
                          <p>{finding.recommendation || "Review this configuration against documented application requirements."}</p>
                          <div className="detail-read-only"><LockKeyhole size={12} /> Recommendation only — no automatic remediation.</div>
                        </div>
                      )}
                    </div>
                  );
                })}
                {data && findings.length === 0 && <EmptyState>No findings were returned by the current audit.</EmptyState>}
                {!data && loading && <EmptyState>Inspecting AWS configuration…</EmptyState>}
              </div>

              <div className="panel-footnote">Findings are rule-based indicators and require human review.</div>
            </article>
          </section>

          <section className="panel inventory-panel" id="assets">
            <SectionTitle
              eyebrow="03 / ASSET INTELLIGENCE"
              title="Subnet inventory"
              action={<span className="count-badge">{subnets.length} SUBNETS</span>}
            />

            <div className="inventory-toolbar">
              <div className="inventory-search">
                <Search size={15} />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search subnet, CIDR, availability zone or route…"
                />
                {search && <button className="clear-search" onClick={() => setSearch("")} aria-label="Clear search"><X size={13} /></button>}
              </div>
              <span className="inventory-live"><span /> LIVE AWS DATA</span>
            </div>

            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>RESOURCE</th><th>IPv4 CIDR</th><th>AVAILABILITY ZONE</th><th>ROUTE TABLE</th><th>CLASSIFICATION</th><th>AUTO PUBLIC IP</th></tr>
                </thead>
                <tbody>
                  {filteredSubnets.map((subnet) => {
                    const isPublic = subnet.route_access === "public_route";
                    return (
                      <tr
                        key={subnet.subnet_id}
                        className={
                          selectedSubnet?.subnet_id === subnet.subnet_id
                            ? "selected-resource-row"
                            : "selectable-resource-row"
                        }
                        tabIndex={0}
                        aria-label={`Inspect subnet ${tagName(subnet) || subnet.subnet_id}`}
                        onClick={() => setSelectedSubnet(subnet)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelectedSubnet(subnet);
                          }
                        }}
                      >
                        <td><div className="table-resource"><span className="table-resource-icon"><Server size={14} /></span><div><strong>{tagName(subnet) || shortId(subnet.subnet_id)}</strong><small>{subnet.subnet_id}</small></div></div></td>
                        <td className="mono">{subnet.cidr || "—"}</td>
                        <td>{subnet.availability_zone || "—"}</td>
                        <td className="mono">{shortId(subnet.route_table_id || "—")}</td>
                        <td><Status tone={isPublic ? "orange" : "blue"}>{isPublic ? "IGW route" : "Internal route"}</Status></td>
                        <td><Status tone={subnet.map_public_ip_on_launch ? "orange" : "green"}>{subnet.map_public_ip_on_launch ? "Enabled" : "Disabled"}</Status></td>
                      </tr>
                    );
                  })}
                  {filteredSubnets.length === 0 && (
                    <tr><td colSpan="6" className="table-empty">{loading ? "Loading resources…" : "No matching resources."}</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {selectedSubnet && (
              <section className="resource-inspector" aria-label="Subnet investigation details">
                <div className="resource-inspector-heading">
                  <div className="resource-inspector-title">
                    <div className="eyebrow">SELECTED RESOURCE / SUBNET DETAILS</div>
                    <h3>{tagName(selectedSubnet) || selectedSubnet.subnet_id}</h3>
                    <span className="resource-id">{selectedSubnet.subnet_id}</span>
                  </div>
                  <button
                    className="button-outline"
                    onClick={() => setSelectedSubnet(null)}
                  >
                    Close details <X size={13} />
                  </button>
                </div>

                <div className="resource-detail-grid">
                  <div className="resource-detail-cell">
                    <span>IPv4 CIDR</span>
                    <strong>{selectedSubnet.cidr || "Not reported"}</strong>
                  </div>
                  <div className="resource-detail-cell">
                    <span>AVAILABILITY ZONE</span>
                    <strong>{selectedSubnet.availability_zone || "Not reported"}</strong>
                  </div>
                  <div className="resource-detail-cell">
                    <span>ROUTE CLASSIFICATION</span>
                    <strong>
                      {selectedSubnet.route_access === "public_route"
                        ? "IGW default route"
                        : "Internal / no IGW default route"}
                    </strong>
                  </div>
                  <div className="resource-detail-cell">
                    <span>AUTO-ASSIGN PUBLIC IPv4</span>
                    <strong className={selectedSubnet.map_public_ip_on_launch ? "detail-warning" : "detail-safe"}>
                      {selectedSubnet.map_public_ip_on_launch ? "Enabled" : "Disabled"}
                    </strong>
                  </div>
                  <div className="resource-detail-cell resource-detail-wide">
                    <span>ASSOCIATED ROUTE TABLE</span>
                    <strong>{selectedSubnet.route_table_id || "No explicit association reported"}</strong>
                  </div>
                </div>

                {subnetExposureAssessment && (
                  <section
                    className={`exposure-assessment exposure-${subnetExposureAssessment.tone}`}
                    aria-label="Subnet exposure assessment"
                  >
                    <div className="exposure-assessment-heading">
                      <div className="exposure-assessment-icon">
                        <ShieldAlert size={16} />
                      </div>
                      <div className="exposure-assessment-title">
                        <span className="eyebrow">NETWORK SECURITY / CONFIGURATION INDICATORS</span>
                        <h4>{subnetExposureAssessment.title}</h4>
                        <p>{subnetExposureAssessment.summary}</p>
                      </div>
                    </div>

                    <div className="exposure-evidence">
                      <span>OBSERVED EVIDENCE</span>
                      <p>{subnetExposureAssessment.evidence}</p>
                    </div>

                    <div className="exposure-indicators">
                      <div>
                        <span>ACTIVE IGW DEFAULT ROUTE</span>
                        <strong className={hasActiveIgwDefaultRoute ? "detail-warning" : "detail-safe"}>
                          {hasActiveIgwDefaultRoute ? "Detected" : "Not detected"}
                        </strong>
                      </div>
                      <div>
                        <span>AUTO-ASSIGN PUBLIC IPv4</span>
                        <strong className={autoPublicIpv4Enabled ? "detail-warning" : "detail-safe"}>
                          {autoPublicIpv4Enabled ? "Enabled" : "Disabled"}
                        </strong>
                      </div>
                    </div>

                    <p className="panel-footnote">
                      Assessment is based on the discovered subnet and associated route table only.
                      It does not evaluate IPv6, network ACLs, workload addresses, security-group
                      reachability, or every other AWS control. Verify those separately before
                      concluding whether a resource is publicly reachable.
                    </p>
                  </section>
                )}
                <div className="inspector-routes-heading">
                  <Router size={14} />
                  <strong>Route table inspection</strong>
                  <span>
                    {selectedSubnetRouteTable
                      ? `${(selectedSubnetRouteTable.routes || []).length} routes`
                      : "Route details unavailable"}
                  </span>
                </div>

                {selectedSubnetRouteTable ? (
                  <div className="table-scroll">
                    <table className="data-table inspector-route-table">
                      <thead>
                        <tr><th>DESTINATION</th><th>TARGET</th><th>STATE</th></tr>
                      </thead>
                      <tbody>
                        {(selectedSubnetRouteTable.routes || []).map((route, index) => (
                          <tr key={`${route.destination || "route"}-${index}`}>
                            <td className="mono">{route.destination || "Unknown"}</td>
                            <td className="mono">{route.target || "Unknown"}</td>
                            <td>
                              <Status tone={route.state === "active" ? "green" : "orange"}>
                                {route.state || "Unknown"}
                              </Status>
                            </td>
                          </tr>
                        ))}
                        {(selectedSubnetRouteTable.routes || []).length === 0 && (
                          <tr><td colSpan="3" className="table-empty">No route entries were returned.</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted-note">The discovery response did not include a matching route table. Refresh discovery to check the latest AWS configuration.</p>
                )}

                <p className="panel-footnote">
                  Read-only inspection. Route classification alone does not establish end-to-end reachability.
                </p>
              </section>
            )}

            <div className="table-footer"><span>Selected VPC · {vpc.cidr || "CIDR unavailable"}</span><span>{filteredSubnets.length} / {subnets.length} resources</span></div>
          </section>

          <section className="lower-grid">
            <article className="panel lower-panel" id="groups">
              <SectionTitle eyebrow="04 / ACCESS CONTROL" title="Security groups" action={<ShieldCheck size={17} className="heading-icon" />} />
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>SECURITY GROUP</th><th>INBOUND</th><th>OUTBOUND</th><th>FINDINGS</th></tr></thead>
                  <tbody>
                    {securityGroups.map((group) => {
                      const groupFindings = findings.filter((item) => item.resource_id === group.group_id);
                      const inbound = Array.isArray(group.inbound_rules) ? group.inbound_rules.length : 0;
                      const outbound = Array.isArray(group.outbound_rules) ? group.outbound_rules.length : 0;
                      return (
                        <tr key={group.group_id}>
                          <td><div className="table-resource"><span className="table-resource-icon group-icon"><Shield size={14} /></span><div><strong>{group.group_name || "Security group"}</strong><small>{group.group_id}</small></div></div></td>
                          <td>{inbound}</td><td>{outbound}</td>
                          <td><Status tone={groupFindings.length ? "orange" : "green"}>{groupFindings.length ? `${groupFindings.length} finding(s)` : "No findings"}</Status></td>
                        </tr>
                      );
                    })}
                    {securityGroups.length === 0 && <tr><td colSpan="4" className="table-empty">{loading ? "Loading groups…" : "No security groups returned."}</td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="panel-footnote">The AWS default security group is shown as discovered. This dashboard does not alter it.</div>
            </article>

            <article className="panel lower-panel">
              <SectionTitle eyebrow="05 / ROUTING INTELLIGENCE" title="Route tables" action={<Router size={17} className="heading-icon" />} />
              <div className="route-list">
                {routeTables.map((table) => {
                  const expanded = expandedRoute === table.route_table_id;
                  const routes = routesFor(table);
                  return (
                    <div className={`route-entry ${expanded ? "route-entry-selected" : ""}`} key={table.route_table_id}>
                      <button className="route-entry-button" onClick={() => setExpandedRoute(expanded ? null : table.route_table_id)}>
                        <span className="route-icon"><Router size={15} /></span>
                        <span className="route-copy"><strong>{tagName(table) || shortId(table.route_table_id)}</strong><small>{table.route_table_id}{table.is_main ? " · MAIN" : ""}</small></span>
                        <span className="route-count">{routes.length} routes</span>
                        <ChevronDown size={14} className={`finding-chevron ${expanded ? "expanded" : ""}`} />
                      </button>
                      {expanded && (
                        <div className="route-details">
                          <div className="route-associations"><span>ASSOCIATED SUBNETS</span><strong>{(table.associated_subnet_ids || []).length ? table.associated_subnet_ids.map((id) => shortId(id)).join(", ") : "No explicit subnet associations"}</strong></div>
                          {routes.map((route, index) => (
                            <div className="route-detail-row" key={`${route.destination}-${index}`}>
                              <span>{route.destination || "Unknown destination"}</span>
                              <span>{route.target || "Unknown target"}</span>
                              <Status tone={route.state === "active" ? "green" : "orange"}>{route.state || "Unknown"}</Status>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {routeTables.length === 0 && <EmptyState>{loading ? "Inspecting routes…" : "No route tables returned."}</EmptyState>}
              </div>
            </article>
          </section>

          <section className="panel gateway-strip">
            <div className="gateway-strip-title">
              <div className="gateway-strip-icon"><Globe size={17} /></div>
              <div><strong>Internet gateways</strong><span>Gateway attachment inventory</span></div>
            </div>
            <div className="gateway-list">
              {gateways.map((gateway) => (
                <div
                  className={`gateway-record gateway-record-interactive ${
                    selectedGateway?.gateway_id === gateway.gateway_id
                      ? "gateway-record-selected"
                      : ""
                  }`}
                  key={gateway.gateway_id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selectedGateway?.gateway_id === gateway.gateway_id}
                  aria-label={`Inspect gateway ${gateway.gateway_id}`}
                  onClick={() => setSelectedGateway(gateway)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedGateway(gateway);
                    }
                  }}
                >
                  <span className="gateway-record-dot" />
                  <strong>{gateway.gateway_id}</strong>
                  <span>{(gateway.attachments || []).map((attachment) => `${attachment.vpc_id} · ${attachment.state}`).join(" / ") || "No attachment details"}</span>
                  <Status tone={(gateway.attachments || []).some((attachment) => attachment.state === "available") ? "green" : "orange"}>
                    {(gateway.attachments || []).some((attachment) => attachment.state === "available") ? "Attached" : "Check status"}
                  </Status>
                </div>
              ))}
              {gateways.length === 0 && <EmptyState>{loading ? "Inspecting gateways…" : "No gateways returned."}</EmptyState>}
            </div>
            {selectedGateway && (
              <div className="gateway-inspector" aria-label="Gateway inspection details">
                <div className="gateway-inspector-heading">
                  <div>
                    <span className="eyebrow">SELECTED RESOURCE / INTERNET GATEWAY</span>
                    <strong>{selectedGateway.gateway_id}</strong>
                  </div>
                  <button
                    type="button"
                    className="button-outline"
                    onClick={() => setSelectedGateway(null)}
                  >
                    Close details <X size={13} />
                  </button>
                </div>

                <div className="gateway-inspector-grid">
                  <div>
                    <span>ATTACHMENTS REPORTED</span>
                    <strong>{(selectedGateway.attachments || []).length}</strong>
                  </div>
                  <div>
                    <span>ATTACHED VPCS</span>
                    <strong>
                      {(selectedGateway.attachments || []).length
                        ? [...new Set(selectedGateway.attachments.map((item) => item.vpc_id).filter(Boolean))].join(", ")
                        : "None reported"}
                    </strong>
                  </div>
                </div>

                <div className="gateway-attachment-list">
                  <strong>Attachment status</strong>
                  {(selectedGateway.attachments || []).map((attachment, index) => (
                    <div className="gateway-attachment-row" key={`${attachment.vpc_id || "vpc"}-${index}`}>
                      <span>{attachment.vpc_id || "VPC not reported"}</span>
                      <Status tone={attachment.state === "available" ? "green" : "orange"}>
                        {attachment.state || "Unknown"}
                      </Status>
                    </div>
                  ))}
                  {(selectedGateway.attachments || []).length === 0 && (
                    <p className="muted-note">No attachment details were returned by discovery.</p>
                  )}
                </div>

                <p className="panel-footnote">
                  Gateway attachment alone does not prove that a workload is reachable from the internet.
                </p>
              </div>
            )}
          </section>

          <footer className="dashboard-footer">
            <div className="footer-brand"><Shield size={15} /><strong>CLOUDGUARD</strong><span>NETWORK INTELLIGENCE</span></div>
            <span className="footer-disclaimer"><LockKeyhole size={12} /> Read-only discovery · No automated remediation</span>
            <span className="footer-api"><span className={error ? "footer-dot footer-dot-error" : "footer-dot"} /> {error ? "API DISCONNECTED" : loading ? "SCANNING" : "API OPERATIONAL"}</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;