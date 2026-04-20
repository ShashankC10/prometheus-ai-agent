from .promql_query import promql_query_tool
from .anomaly_detection import anomaly_detection_tool
from .metric_explorer import metric_explorer_tool
from .alert_rules import alert_rules_tool
from .metric_catalog import metric_catalog_tool
from .promql_validator import promql_validator_tool
from .incident_packs import incident_pack_tool

ALL_TOOLS = [
    metric_catalog_tool,
    promql_validator_tool,
    promql_query_tool,
    anomaly_detection_tool,
    incident_pack_tool,
    metric_explorer_tool,
    alert_rules_tool,
]
