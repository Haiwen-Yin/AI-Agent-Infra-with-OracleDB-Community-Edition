#!/usr/bin/env python3
"""AI Agent Infra v4.0.1 - Enterprise Edition - Agent Bootstrap CLI

Command-line tool for Business Agent registration and configuration.
Connects to Admin Agent API, registers with admin token,
receives encrypted End User credentials, and saves to agent_config.json.

Usage:
    python agent_bootstrap.py register --agent-id MY_AGENT --agent-name "My Agent" \
        --admin-token AT_xxx --admin-url http://<ADMIN_HOST>:<PORT>

    python agent_bootstrap.py test --config agent_config.json

    python agent_bootstrap.py recover --agent-id MY_AGENT --recovery-code RC-XXXX-XXXX-XXXX \
        --admin-token AT_xxx --admin-url http://<ADMIN_HOST>:<PORT>

    python agent_bootstrap.py skill-list --admin-token AT_xxx --admin-url http://<ADMIN_HOST>:<PORT>

    python agent_bootstrap.py skill-acquire --skill-id SKILL_XXX --admin-token AT_xxx \
        --admin-url http://<ADMIN_HOST>:<PORT>
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def _api_post(url: str, data: dict, timeout: int = 30) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        try:
            error_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            error_body = {"error": str(e)}
        return {"error": f"HTTP {e.code}", "detail": error_body}
    except URLError as e:
        return {"error": f"Connection failed: {e}"}


def cmd_register(args):
    admin_url = args.admin_url.rstrip("/")
    register_url = f"{admin_url}/api/admin/agent/register"

    payload = {
        "agent_id": args.agent_id,
        "agent_name": args.agent_name,
        "admin_token": args.admin_token,
    }
    if args.agent_type:
        payload["agent_type"] = args.agent_type
    if args.description:
        payload["description"] = args.description

    print(f"Registering agent '{args.agent_id}' via Admin API...")
    result = _api_post(register_url, payload)

    if "error" in result:
        print(f"Registration failed: {result}")
        return 1

    agent_id = result.get("agent_id")
    end_user = result.get("end_user", {})
    encrypted_cred = end_user.get("credential_encrypted")
    salt = end_user.get("salt")

    if not encrypted_cred or not salt:
        print(f"Registration succeeded but no credentials returned: {result}")
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.connection_crypto import decrypt_credential_from_distribution, save_agent_config

    try:
        creds = decrypt_credential_from_distribution(encrypted_cred, salt, args.admin_token)
    except Exception as e:
        print(f"Failed to decrypt credentials: {e}")
        return 1

    config_path = Path(args.config) if args.config else Path(__file__).resolve().parent / "agent_config.json"
    save_agent_config(agent_id, creds, config_path)

    print(f"Agent '{agent_id}' registered successfully.")
    print(f"End User credentials saved to: {config_path}")
    print(f"  Username: {creds.get('username')}")
    print(f"  DSN: {creds.get('dsn')}")

    recovery_codes = result.get("recovery_codes", [])
    if recovery_codes:
        print(f"\n*** RECOVERY CODES - SAVE SECURELY (shown only once) ***")
        for i, rc in enumerate(recovery_codes, 1):
            print(f"  {i}. {rc}")
        print(f"*** Use these codes to recover agent if lost/crashed ***")

    return 0


def cmd_recover(args):
    admin_url = args.admin_url.rstrip("/")
    recover_url = f"{admin_url}/api/admin/agent/recover"

    payload = {
        "agent_id": args.agent_id,
        "recovery_code": args.recovery_code,
        "admin_token": args.admin_token,
    }

    print(f"Recovering agent '{args.agent_id}' via Admin API...")
    result = _api_post(recover_url, payload)

    if "error" in result:
        print(f"Recovery failed: {result}")
        return 1

    agent_id = result.get("agent_id")
    end_user = result.get("end_user", {})
    encrypted_cred = end_user.get("credential_encrypted")
    salt = end_user.get("salt")

    if not encrypted_cred or not salt:
        print(f"Recovery succeeded but no credentials returned: {result}")
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.connection_crypto import decrypt_credential_from_distribution, save_agent_config

    try:
        creds = decrypt_credential_from_distribution(encrypted_cred, salt, args.admin_token)
    except Exception as e:
        print(f"Failed to decrypt credentials: {e}")
        return 1

    config_path = Path(args.config) if args.config else Path(__file__).resolve().parent / "agent_config.json"
    save_agent_config(agent_id, creds, config_path)

    print(f"Agent '{agent_id}' recovered successfully.")
    print(f"New End User credentials saved to: {config_path}")
    print(f"  Username: {creds.get('username')}")
    print(f"  DSN: {creds.get('dsn')}")
    print(f"  Note: Old password has been invalidated. Old process cannot reconnect.")
    return 0


def cmd_test(args):
    config_path = Path(args.config) if args.config else Path(__file__).resolve().parent / "agent_config.json"
    if not config_path.exists():
        print(f"Agent config not found: {config_path}")
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.connection_crypto import load_agent_config

    creds = load_agent_config(config_path)
    print(f"Testing connection for agent: {creds.get('agent_id')}")
    print(f"  Username: {creds.get('username')}")
    print(f"  DSN: {creds.get('dsn')}")

    # Detect adapter from the DSN shape or an explicit db_type marker saved by
    # the server. PostgreSQL DSNs look like "host:port:database" (two colons),
    # Oracle/YashanDB DSNs look like "host:port/service" (slash).
    dsn = creds.get("dsn", "")
    db_type = creds.get("db_type")
    if not db_type:
        if dsn.count(":") == 2 and "/" not in dsn.split(":")[-1]:
            db_type = "pg"
        elif dsn.count(":") == 2 and "/" in dsn.split(":")[-1]:
            # Could be Oracle or YashanDB — both work via their respective
            # drivers; default to oracledb (the more common case).
            db_type = "oracle"

    try:
        if db_type == "pg":
            import psycopg2
            host, port, dbname = dsn.split(":")
            conn = psycopg2.connect(
                user=creds["username"],
                password=creds["password"],
                host=host,
                port=int(port),
                dbname=dbname,
            )
            cur = conn.cursor()
            cur.execute("SET app.current_agent_id = %s", (creds.get("agent_id", ""),))
            cur.execute("SELECT COUNT(*) FROM agent_registry")
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
        else:
            # Oracle or YashanDB — both use a "host:port/service" DSN.
            if db_type == "yashandb":
                import yaspy
                driver_connect = yaspy.connect
            else:
                import oracledb
                driver_connect = oracledb.connect
            conn = driver_connect(
                user=creds["username"],
                password=creds["password"],
                dsn=dsn,
            )
            with conn.cursor() as cur:
                if db_type == "oracle":
                    cur.execute("ALTER SESSION SET CURRENT_SCHEMA = AIADMIN")
                cur.execute("SELECT COUNT(*) FROM AGENT_REGISTRY")
                count = cur.fetchone()[0]
            conn.close()
        print(f"  Connection OK! Agent count: {count}")
        return 0
    except Exception as e:
        print(f"  Connection FAILED: {e}")
        return 1


def cmd_skill_list(args):
    admin_url = args.admin_url.rstrip("/")
    admin_token = args.admin_token
    url = f"{admin_url}/api/admin/skill/list?admin_token={admin_token}"
    if args.type:
        url += f"&type={args.type}"
    if args.keyword:
        url += f"&keyword={args.keyword}"

    print("Fetching skill list from Admin API...")
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Failed: {e}")
        return 1

    skills = result.get("skills", [])
    if not skills:
        print("No skills found.")
        return 0

    print(f"Found {len(skills)} skill(s):")
    print(f"{'ID':<40} {'Name':<25} {'Type':<10} {'Runtime':<10} {'Version':<8}")
    print("-" * 95)
    for s in skills:
        print(f"{s.get('entity_id', ''):<40} {s.get('skill_name', ''):<25} {s.get('skill_type', ''):<10} {s.get('runtime', ''):<10} {s.get('skill_version', ''):<8}")
    return 0


def cmd_skill_acquire(args):
    admin_url = args.admin_url.rstrip("/")
    admin_token = args.admin_token
    skill_id = args.skill_id
    resource = "1" if args.resource else "0"
    url = f"{admin_url}/api/admin/skill/{skill_id}/acquire?admin_token={admin_token}&resource={resource}"

    print(f"Acquiring skill '{skill_id}' from Admin API...")
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Failed: {e}")
        return 1

    if "error" in result:
        print(f"Error: {result['error']}")
        return 1

    print(f"Skill: {result.get('skill_name')} v{result.get('skill_version')}")
    print(f"Type: {result.get('skill_type')} | Runtime: {result.get('runtime')}")
    print(f"Description: {result.get('description', '')[:100]}")

    text_content = result.get("text_content", "")
    if text_content and args.output:
        with open(args.output, "w") as f:
            f.write(text_content)
        print(f"Text content saved to: {args.output}")
    elif text_content:
        print(f"\nText content ({len(text_content)} chars):")
        print(text_content[:500])
        if len(text_content) > 500:
            print(f"... ({len(text_content) - 500} more chars)")

    resource_zip = result.get("resource_zip")
    if resource_zip and args.resource:
        import base64
        zip_data = base64.b64decode(resource_zip) if isinstance(resource_zip, str) else resource_zip
        out_path = args.output or f"{skill_id}.zip"
        with open(out_path, "wb") as f:
            f.write(zip_data)
        print(f"Resource ZIP saved to: {out_path} ({len(zip_data)} bytes)")

    return 0


def cmd_skill_create(args):
    import base64
    admin_url = args.admin_url.rstrip("/")
    admin_token = args.admin_token
    url = f"{admin_url}/api/admin/skill/create"
    payload = {"admin_token": admin_token, "title": args.title, "skill_name": args.skill_name}
    for opt_field in ["skill_version", "skill_type", "skill_format", "text_content",
                      "skill_description", "runtime", "parameters", "dependencies",
                      "category", "owned_by_agent", "visibility"]:
        val = getattr(args, opt_field, None)
        if val is not None:
            payload[opt_field] = val
    if args.skill_file:
        with open(args.skill_file, "r") as f:
            payload["text_content"] = f.read()
    if args.resource_file:
        with open(args.resource_file, "rb") as f:
            payload["filename"] = os.path.basename(args.resource_file)
            payload["content_base64"] = base64.b64encode(f.read()).decode("ascii")
    print(f"Creating skill '{args.skill_name}' via Admin API...")
    result = _api_post(url, payload)
    if "error" in result:
        print(f"Failed: {result}")
        return 1
    skill_id = result.get("skill_id")
    print(f"Skill created: {skill_id}")
    print(f"  Name: {result.get('skill', {}).get('skill_name')}")
    return 0


def cmd_skill_update(args):
    admin_url = args.admin_url.rstrip("/")
    admin_token = args.admin_token
    url = f"{admin_url}/api/admin/skill/update"
    payload = {"admin_token": admin_token, "skill_id": args.skill_id}
    for opt_field in ["title", "skill_name", "skill_version", "skill_type", "skill_format",
                      "text_content", "skill_description", "runtime", "parameters",
                      "dependencies", "category", "owned_by_agent", "visibility", "skill_status"]:
        val = getattr(args, opt_field, None)
        if val is not None:
            payload[opt_field] = val
    print(f"Updating skill '{args.skill_id}' via Admin API...")
    result = _api_post(url, payload)
    if "error" in result:
        print(f"Failed: {result}")
        return 1
    print(f"Skill updated: {result.get('skill_id')}")
    return 0


def cmd_skill_delete(args):
    admin_url = args.admin_url.rstrip("/")
    admin_token = args.admin_token
    url = f"{admin_url}/api/admin/skill/delete"
    payload = {"admin_token": admin_token, "skill_id": args.skill_id}
    print(f"Deleting skill '{args.skill_id}' via Admin API...")
    result = _api_post(url, payload)
    if "error" in result:
        print(f"Failed: {result}")
        return 1
    if result.get("deleted"):
        print(f"Skill '{args.skill_id}' deleted.")
        return 0
    print(f"Skill not found.")
    return 1


def main():
    parser = argparse.ArgumentParser(description="AI Agent Infra - Agent Bootstrap CLI")
    sub = parser.add_subparsers(dest="command")

    reg = sub.add_parser("register", help="Register agent via Admin API")
    reg.add_argument("--agent-id", required=True, help="Unique agent identifier")
    reg.add_argument("--agent-name", required=True, help="Display name")
    reg.add_argument("--admin-token", required=True, help="Admin registration token")
    reg.add_argument("--admin-url", required=True, help="Admin API URL (e.g. http://host:18080)")
    reg.add_argument("--agent-type", default=None, help="Agent type (e.g. BUSINESS)")
    reg.add_argument("--description", default=None, help="Agent description")
    reg.add_argument("--config", default=None, help="Output agent_config.json path")

    rec = sub.add_parser("recover", help="Recover agent via Admin API using recovery code")
    rec.add_argument("--agent-id", required=True, help="Agent identifier to recover")
    rec.add_argument("--recovery-code", required=True, help="One-time recovery code (RC-XXXX-XXXX-XXXX)")
    rec.add_argument("--admin-token", required=True, help="Admin registration token")
    rec.add_argument("--admin-url", required=True, help="Admin API URL")
    rec.add_argument("--config", default=None, help="Output agent_config.json path")

    test = sub.add_parser("test", help="Test agent connection")
    test.add_argument("--config", default=None, help="Path to agent_config.json")

    skl = sub.add_parser("skill-list", help="List available skills via Admin API")
    skl.add_argument("--admin-token", required=True, help="Admin registration token")
    skl.add_argument("--admin-url", required=True, help="Admin API URL")
    skl.add_argument("--type", default=None, help="Filter by skill type")
    skl.add_argument("--keyword", default=None, help="Search keyword")

    ska = sub.add_parser("skill-acquire", help="Acquire a skill via Admin API")
    ska.add_argument("--skill-id", required=True, help="Skill entity ID")
    ska.add_argument("--admin-token", required=True, help="Admin registration token")
    ska.add_argument("--admin-url", required=True, help="Admin API URL")
    ska.add_argument("--resource", action="store_true", help="Include resource files (ZIP)")
    ska.add_argument("--output", default=None, help="Output file path for text or resource")

    skc = sub.add_parser("skill-create", help="Create a skill via Admin API")
    skc.add_argument("--title", required=True, help="Skill title")
    skc.add_argument("--skill-name", required=True, help="Skill name")
    skc.add_argument("--admin-token", required=True, help="Admin registration token")
    skc.add_argument("--admin-url", required=True, help="Admin API URL")
    skc.add_argument("--skill-version", default=None, help="Version (default 1.0.0)")
    skc.add_argument("--skill-type", default=None, help="Type (default CUSTOM)")
    skc.add_argument("--skill-format", default=None, help="Format (default TEXT)")
    skc.add_argument("--skill-description", default=None, help="Description")
    skc.add_argument("--runtime", default=None, help="Runtime (default PYTHON)")
    skc.add_argument("--skill-file", default=None, help="Path to SKILL.md for text_content")
    skc.add_argument("--resource-file", default=None, help="Path to resource ZIP (base64 encoded in API)")
    skc.add_argument("--category", default=None, help="Category")
    skc.add_argument("--owned-by-agent", default=None, help="Owning agent ID")
    skc.add_argument("--visibility", default=None, help="PRIVATE/SHARED/PUBLIC")

    sku = sub.add_parser("skill-update", help="Update a skill via Admin API")
    sku.add_argument("--skill-id", required=True, help="Skill entity ID")
    sku.add_argument("--admin-token", required=True, help="Admin registration token")
    sku.add_argument("--admin-url", required=True, help="Admin API URL")
    sku.add_argument("--title", default=None, help="New title")
    sku.add_argument("--skill-name", default=None, help="New skill name")
    sku.add_argument("--skill-version", default=None, help="New version")
    sku.add_argument("--skill-status", default=None, help="ACTIVE/DEPRECATED")
    sku.add_argument("--skill-description", default=None, help="New description")
    sku.add_argument("--visibility", default=None, help="PRIVATE/SHARED/PUBLIC")

    skd = sub.add_parser("skill-delete", help="Delete a skill via Admin API")
    skd.add_argument("--skill-id", required=True, help="Skill entity ID")
    skd.add_argument("--admin-token", required=True, help="Admin registration token")
    skd.add_argument("--admin-url", required=True, help="Admin API URL")

    args = parser.parse_args()
    if args.command == "register":
        return cmd_register(args)
    elif args.command == "recover":
        return cmd_recover(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "skill-list":
        return cmd_skill_list(args)
    elif args.command == "skill-acquire":
        return cmd_skill_acquire(args)
    elif args.command == "skill-create":
        return cmd_skill_create(args)
    elif args.command == "skill-update":
        return cmd_skill_update(args)
    elif args.command == "skill-delete":
        return cmd_skill_delete(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
