from .promql_query import promql_query_tool
from .anomaly_detection import anomaly_detection_tool
from .metric_explorer import metric_explorer_tool
from .alert_rules import alert_rules_tool

ALL_TOOLS = [
    promql_query_tool,
    anomaly_detection_tool,
    metric_explorer_tool,
    alert_rules_tool,
]
