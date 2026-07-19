"""AI Agent Infra v4.0.0 - Enterprise Edition - Tool Registry + DAG Chains

OpenAPI import, tool versioning, tool DAG composition, tool invocation.
Tables: TOOL_REGISTRY, TOOL_CHAINS, TOOL_CHAIN_STEPS
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert,
    execute_insert_returning_id,
    sanitize_row,
)

logger = logging.getLogger(__name__)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    return sanitize_row(row)


def import_openapi(spec: Dict[str, Any], namespace: str) -> List[str]:
    paths = spec.get("paths", {})
    version = spec.get("info", {}).get("version", "1.0.0")
    created: List[str] = []

    for path, methods in paths.items():
        for method, endpoint in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            operation_id = endpoint.get("operationId") or f"{method}_{path}".replace("/", "_")
            tool_name = f"{namespace}_{operation_id}"

            input_schema = {"path": path, "method": method.upper(), "parameters": endpoint.get("parameters", [])}
            if "requestBody" in endpoint:
                input_schema["requestBody"] = endpoint["requestBody"]
            output_schema = {}
            for code, resp in endpoint.get("responses", {}).items():
                if str(code).startswith("2"):
                    output_schema = resp.get("content", {}).get("application/json", {}).get("schema", {})
                    break

            tool_id = execute_insert_returning_id(
                """INSERT INTO TOOL_REGISTRY
                   (TOOL_ID, TOOL_NAME, TOOL_NAMESPACE, TOOL_VERSION, DESCRIPTION,
                    INPUT_SCHEMA, OUTPUT_SCHEMA, TOOL_TYPE, STATUS)
                   VALUES (RAWTOHEX(SYS_GUID()), :name, :ns, :ver, :descr,
                           :in_schema, :out_schema, 'API', 'ACTIVE')
                   RETURNING TOOL_ID INTO :ret_id""",
                {
                    "name": tool_name, "ns": namespace, "ver": version,
                    "descr": endpoint.get("summary", f"{method.upper()} {path}"),
                    "in_schema": json.dumps(input_schema), "out_schema": json.dumps(output_schema),
                },
            )
            created.append(tool_id)

    logger.info("Imported %d tools from OpenAPI namespace %s", len(created), namespace)
    return created


def import_from_url(url: str, namespace: str, auth_header: Optional[str] = None) -> List[str]:
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if auth_header:
        req.add_header("Authorization", auth_header)
    with urllib.request.urlopen(req, timeout=30) as resp:
        spec = json.loads(resp.read().decode("utf-8"))
    return import_openapi(spec, namespace)


def import_from_file(path: str, namespace: str) -> List[str]:
    with open(path, "r") as f:
        spec = json.load(f)
    return import_openapi(spec, namespace)


def list_tools(namespace: Optional[str] = None, tool_type: Optional[str] = None) -> List[Dict[str, Any]]:
    clauses = ["STATUS != 'RETIRED'"]
    params: Dict[str, Any] = {}
    if namespace:
        clauses.append("TOOL_NAMESPACE = :ns")
        params["ns"] = namespace
    if tool_type:
        clauses.append("TOOL_TYPE = :ttype")
        params["ttype"] = tool_type

    rows = execute_query(
        f"""SELECT * FROM (
              SELECT t.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
              FROM TOOL_REGISTRY t WHERE {' AND '.join(clauses)}
            ) WHERE rn <= 100""",
        params,
    )
    return [_row_to_dict(r) for r in rows]


def get_tool(tool_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one(
        "SELECT * FROM TOOL_REGISTRY WHERE TOOL_ID = :tid",
        {"tid": tool_id},
    )
    return _row_to_dict(row) if row else None


def refresh_tool(tool_id: str, spec: Dict[str, Any]) -> bool:
    tool = get_tool(tool_id)
    if not tool:
        return False
    affected = execute(
        """UPDATE TOOL_REGISTRY SET OUTPUT_SCHEMA = :schema, UPDATED_AT = SYSTIMESTAMP
           WHERE TOOL_ID = :tid""",
        {"schema": json.dumps(spec), "tid": tool_id},
    )
    return affected > 0


def delete_tool(tool_id: str) -> bool:
    affected = execute(
        "UPDATE TOOL_REGISTRY SET STATUS = 'RETIRED', UPDATED_AT = SYSTIMESTAMP WHERE TOOL_ID = :tid",
        {"tid": tool_id},
    )
    return affected > 0


def create_tool_chain(name: str, steps: List[Dict[str, Any]], description: Optional[str] = None) -> str:
    chain_id = execute_insert_returning_id(
        """INSERT INTO TOOL_CHAINS (CHAIN_ID, CHAIN_NAME, DESCRIPTION)
           VALUES (RAWTOHEX(SYS_GUID()), :name, :descr)
           RETURNING CHAIN_ID INTO :ret_id""",
        {"name": name, "descr": description},
    )
    for order, step in enumerate(steps, 1):
        execute_insert(
            """INSERT INTO TOOL_CHAIN_STEPS
               (CHAIN_STEP_ID, CHAIN_ID, STEP_ORDER, TOOL_ID,
                INPUT_MAPPING, OUTPUT_MAPPING, PARALLEL_GROUP, TIMEOUT_SECONDS)
               VALUES (RAWTOHEX(SYS_GUID()), :cid, :p_order, :tid,
                       :in_map, :out_map, :pgroup, :timeout)""",
            {
                "cid": chain_id, "p_order": order,
                "tid": step.get("tool_id"),
                "in_map": json.dumps(step.get("input_mapping", {})),
                "out_map": json.dumps(step.get("output_mapping", {})),
                "pgroup": step.get("parallel_group"),
                "timeout": step.get("timeout_seconds"),
            },
        )
    return chain_id


def get_tool_chain(chain_id: str) -> Optional[Dict[str, Any]]:
    chain = execute_query_one(
        "SELECT * FROM TOOL_CHAINS WHERE CHAIN_ID = :cid",
        {"cid": chain_id},
    )
    if not chain:
        return None
    steps = execute_query(
        """SELECT tcs.*, tr.TOOL_NAME, tr.INPUT_SCHEMA, tr.OUTPUT_SCHEMA
           FROM TOOL_CHAIN_STEPS tcs
           JOIN TOOL_REGISTRY tr ON tr.TOOL_ID = tcs.TOOL_ID
           WHERE tcs.CHAIN_ID = :cid ORDER BY tcs.STEP_ORDER""",
        {"cid": chain_id},
    )
    result = _row_to_dict(chain)
    result["steps"] = [_row_to_dict(s) for s in steps]
    return result


def list_tool_chains(limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT c.*, (SELECT COUNT(*) FROM TOOL_CHAIN_STEPS s WHERE s.CHAIN_ID = c.CHAIN_ID) AS step_count
           FROM TOOL_CHAINS c ORDER BY c.CREATED_AT DESC
           FETCH FIRST :limit ROWS ONLY""",
        {"limit": limit},
    )
    return [_row_to_dict(r) for r in rows]


def delete_tool_chain(chain_id: str) -> bool:
    affected = execute(
        "DELETE FROM TOOL_CHAINS WHERE CHAIN_ID = :cid",
        {"cid": chain_id},
    )
    return affected > 0


def record_tool_call(tool_id: str) -> bool:
    affected = execute(
        """UPDATE TOOL_REGISTRY SET CALL_COUNT = CALL_COUNT + 1, LAST_CALLED_AT = SYSTIMESTAMP
           WHERE TOOL_ID = :tid""",
        {"tid": tool_id},
    )
    return affected > 0


def get_tool_stats() -> Dict[str, Any]:
    rows = execute_query(
        """SELECT TOOL_TYPE, STATUS, COUNT(*) AS CNT, SUM(CALL_COUNT) AS TOTAL_CALLS
           FROM TOOL_REGISTRY GROUP BY TOOL_TYPE, STATUS""",
    )
    stats: Dict[str, Any] = {"by_type": {}, "by_status": {}, "total_tools": 0, "total_calls": 0}
    for r in rows:
        ttype = r.get("tool_type", "UNKNOWN")
        stat = r.get("status", "UNKNOWN")
        cnt = r.get("cnt", 0)
        calls = r.get("total_calls", 0) or 0
        stats["by_type"][ttype] = stats["by_type"].get(ttype, 0) + cnt
        stats["by_status"][stat] = stats["by_status"].get(stat, 0) + cnt
    stats["total_tools"] += cnt
    stats["total_calls"] += calls
    return stats


def invoke_tool(tool_id: str, input_params: Optional[Dict[str, Any]] = None,
                timeout: int = 30) -> Dict[str, Any]:
    """Execute a registered tool by making an HTTP call to its endpoint.

    Reads the tool's INPUT_SCHEMA (which contains path, method, parameters)
    and constructs an HTTP request accordingly.

    Returns a dict with: success, status_code, body, error
    """
    tool = get_tool(tool_id)
    if not tool:
        return {"success": False, "error": f"Tool {tool_id} not found"}
    if tool.get("status", "ACTIVE") != "ACTIVE":
        return {"success": False, "error": f"Tool {tool_id} is not active"}

    input_schema = tool.get("input_schema", {})
    if isinstance(input_schema, str):
        try:
            input_schema = json.loads(input_schema)
        except (json.JSONDecodeError, TypeError):
            input_schema = {}

    path = input_schema.get("path", "/")
    method = input_schema.get("method", "GET").upper()
    parameters = input_schema.get("parameters", [])
    request_body = input_schema.get("requestBody", {})

    input_params = input_params or {}

    url = path
    query_parts = []
    body_data = None
    headers = {"Content-Type": "application/json"}

    for param in parameters:
        pname = param.get("name", "")
        pin = param.get("in", "query")
        if pname in input_params:
            if pin == "path":
                url = url.replace(f"{{{pname}}}", str(input_params[pname]))
            elif pin == "query":
                query_parts.append(f"{pname}={input_params[pname]}")
            elif pin == "header":
                headers[pname] = str(input_params[pname])

    if query_parts:
        url += "?" + "&".join(query_parts)

    if method in ("POST", "PUT", "PATCH") and request_body:
        body_data = json.dumps(input_params).encode()

    if method == "GET" and input_params:
        for k, v in input_params.items():
            if k not in [p.get("name") for p in parameters]:
                query_parts.append(f"{k}={v}")
        if query_parts:
            url += ("?" if "?" not in url else "&") + "&".join(query_parts)

    try:
        req = urllib.request.Request(url, data=body_data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            record_tool_call(tool_id)
            return {
                "success": True,
                "status_code": resp.status,
                "body": resp_body,
                "url": url,
                "method": method,
            }
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8", errors="replace")
        return {
            "success": False,
            "status_code": e.code,
            "body": resp_body,
            "error": str(e),
            "url": url,
            "method": method,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "url": url,
            "method": method,
        }
