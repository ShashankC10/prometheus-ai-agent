"""
Tool that provides service topology and dependency context.

Helps the agent understand which services are involved in an incident,
what their upstream/downstream dependencies are, and which metrics
represent their health — enabling root-cause isolation across services.
"""

import json
import os
from pathlib import Path

import yaml
from langchain_core.tools import tool

TOPOLOGY_PATH = os.getenv("TOPOLOGY_PATH", "topology/service_topology.yml")


def _load_topology() -> dict:
    path = Path(TOPOLOGY_PATH)
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


@tool
def topology_tool(action: str, service_name: str = "", metric_name: str = "") -> str:
    """Query the service topology to understand dependencies and affected blast radius.

    Use this tool to:
    - Identify which service owns a metric that is anomalous
    - Find upstream dependencies that could be causing a downstream issue
    - Understand which services are affected when a shared dependency fails
    - Get the health query and primary metrics for a specific service

    Args:
        action: One of:
            - 'list_services': List all services in the topology with their type and health query.
            - 'service_info': Get full details for a specific service including
              dependencies, metrics, and alert rules. Requires `service_name`.
            - 'dependencies': Get upstream (depends_on) and downstream (depended_on_by)
              services for a given service. Requires `service_name`.
            - 'metric_owner': Find which service owns a given metric name. Requires `metric_name`.
            - 'affected_services': Given a failing service, list all services that
              depend on it (blast radius). Requires `service_name`.
        service_name: Service name for service-specific actions.
        metric_name: Metric name for 'metric_owner' action.

    Returns:
        JSON with the requested topology information.
    """
    try:
        topology = _load_topology()
        if not topology:
            return json.dumps({"error": f"No topology found at {TOPOLOGY_PATH}"})

        services = topology.get("services", [])
        metric_map = topology.get("metric_to_service", {})

        if action == "list_services":
            summary = [
                {
                    "name": s["name"],
                    "type": s.get("type"),
                    "description": s.get("description"),
                    "health_query": s.get("health_query"),
                    "depends_on": s.get("depends_on", []),
                }
                for s in services
            ]
            return json.dumps({"services": summary}, indent=2)

        elif action == "service_info":
            if not service_name:
                return json.dumps({"error": "'service_name' is required"})
            svc = next((s for s in services if s["name"].lower() == service_name.lower()), None)
            if not svc:
                available = [s["name"] for s in services]
                return json.dumps({"error": f"Service '{service_name}' not found", "available": available})
            return json.dumps({"service": svc}, indent=2)

        elif action == "dependencies":
            if not service_name:
                return json.dumps({"error": "'service_name' is required"})
            svc = next((s for s in services if s["name"].lower() == service_name.lower()), None)
            if not svc:
                return json.dumps({"error": f"Service '{service_name}' not found"})
            return json.dumps({
                "service": service_name,
                "depends_on": svc.get("depends_on", []),
                "depended_on_by": svc.get("depended_on_by", []),
            }, indent=2)

        elif action == "metric_owner":
            if not metric_name:
                return json.dumps({"error": "'metric_name' is required"})
            owner = metric_map.get(metric_name)
            if not owner:
                # Fuzzy: check if metric_name is a prefix of any known metric
                matches = {m: s for m, s in metric_map.items() if metric_name in m}
                if matches:
                    return json.dumps({"metric": metric_name, "owner": None, "partial_matches": matches}, indent=2)
                return json.dumps({"metric": metric_name, "owner": None, "message": "Metric not in topology"})
            svc = next((s for s in services if s["name"] == owner), None)
            return json.dumps({
                "metric": metric_name,
                "owner_service": owner,
                "service_health_query": svc.get("health_query") if svc else None,
                "service_alert_rules": svc.get("alert_rules", []) if svc else [],
            }, indent=2)

        elif action == "affected_services":
            if not service_name:
                return json.dumps({"error": "'service_name' is required"})
            affected = [
                s["name"] for s in services
                if service_name in s.get("depends_on", [])
            ]
            return json.dumps({
                "failing_service": service_name,
                "directly_affected": affected,
                "message": f"{len(affected)} service(s) depend on {service_name}",
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action '{action}'. Use list_services, service_info, dependencies, metric_owner, or affected_services."
            })

    except Exception as e:
        return json.dumps({"error": str(e)})
