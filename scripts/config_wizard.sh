#!/bin/bash
# ============================================================================
# config_wizard.sh — First-run configuration wizard for AI Agent Infra
#
# Detects whether config.json has unresolved <PLACEHOLDER> tokens and, if so,
# interactively prompts the operator to fill in real values. After the wizard
# completes, the resulting config.json is left in plaintext; the web server's
# auto_encrypt_config() will encrypt the sensitive sections on first startup.
#
# Usage: bash scripts/config_wizard.sh
#        (also invoked by start_web_server.sh on first run)
#
# Exit codes:  0 = config ready (either filled or skipped)
#              1 = missing config.example.json template
#              2 = operator chose to abort
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_DIR/config.json"
EXAMPLE_FILE="$PROJECT_DIR/config.example.json"
RUNTIME_HELPER="$SCRIPT_DIR/python_runtime.sh"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

read_masked_secret() {
    local prompt="$1"
    local target="$2"
    local value=""
    local char=""

    # Automated installers provide answers through stdin. Keep that path
    # silent and line-oriented; interactive terminals receive live masking.
    if [ ! -t 0 ]; then
        IFS= read -r value || true
        printf -v "$target" '%s' "$value"
        return
    fi

    printf '%s' "$prompt"
    while IFS= read -r -s -n 1 char; do
        if [ -z "$char" ]; then
            break
        fi
        case "$char" in
            $'\177'|$'\b')
                if [ -n "$value" ]; then
                    value="${value%?}"
                    printf '\b \b'
                fi
                ;;
            *)
                value+="$char"
                printf '*'
                ;;
        esac
    done
    printf '\n'
    printf -v "$target" '%s' "$value"
}

# --- Step 1: ensure config.json exists (copy from template if missing) -------
if [ ! -f "$CONFIG_FILE" ]; then
    if [ ! -f "$EXAMPLE_FILE" ]; then
        echo -e "${RED}[wizard] ERROR: neither config.json nor config.example.json found in $PROJECT_DIR${NC}"
        echo -e "${RED}[wizard]        Release package is incomplete. Re-extract from the zip.${NC}"
        exit 1
    fi
    echo -e "${BLUE}[wizard] config.json not found. Copying from config.example.json...${NC}"
    cp "$EXAMPLE_FILE" "$CONFIG_FILE"
fi

# --- Step 2: detect unresolved placeholders ---------------------------------
has_placeholder() {
    grep -qE '<[A-Z_]+>' "$CONFIG_FILE" 2>/dev/null
}

if ! has_placeholder; then
    exit 0
fi

# --- Step 3: interactive prompt ---------------------------------------------
echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  AI Agent Infra — First-Run Configuration Wizard${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "${YELLOW}[wizard] config.json still contains <PLACEHOLDER> values.${NC}"
echo -e "${YELLOW}[wizard] You need to fill in real values before the server can start.${NC}"
echo -e "${YELLOW}[wizard] Sensitive sections will be auto-encrypted on first startup.${NC}"
echo ""
echo -e "  Project dir:  $PROJECT_DIR"
echo -e "  Config file:  $CONFIG_FILE"
echo ""
read -r -p "Configure now? [Y/n] " yn || yn="n"
case "$yn" in
    [Nn]*)
        echo -e "${YELLOW}[wizard] Skipped. Edit $CONFIG_FILE manually, then re-run.${NC}"
        exit 0
        ;;
esac

# --- Step 4: collect values into a JSON override blob -----------------------
# Detect which connection shape the template uses (dsn vs host/port/dbname)
if grep -q '"dsn"' "$CONFIG_FILE"; then
    DB_SHAPE="dsn"
else
    DB_SHAPE="hostport"
fi

if [ ! -f "$RUNTIME_HELPER" ]; then
    echo -e "${RED}[wizard] ERROR: Python runtime helper is missing${NC}" >&2
    exit 1
fi
source "$RUNTIME_HELPER"
if ! PY_BIN="$(cx_resolve_python "${PYTHON_BIN:-}")"; then
    echo -e "${RED}[wizard] ERROR: Python 3.14+ interpreter was not found${NC}" >&2
    exit 1
fi
cx_prepare_python_environment "$PY_BIN"

mapfile -t SERVER_DEFAULTS < <("$PY_BIN" - "$CONFIG_FILE" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    server = (json.load(stream).get("server") or {})
print(server.get("host") or "0.0.0.0")
print(server.get("port") or 8000)
PYEOF
)
DEFAULT_SERVER_HOST="${SERVER_DEFAULTS[0]:-0.0.0.0}"
DEFAULT_SERVER_PORT="${SERVER_DEFAULTS[1]:-8000}"

echo ""
echo -e "${BLUE}[database]${NC}"
read -r -p "  DB user [aiadmin]: " DB_USER
DB_USER="${DB_USER:-aiadmin}"
read_masked_secret "  DB password: " DB_PASS

if [ "$DB_SHAPE" = "dsn" ]; then
    read -r -p "  DB DSN (host:port/service): " DB_DSN
    DB_DSN="${DB_DSN:-<DB_HOST>:1521/<service>}"
else
    read -r -p "  DB host: " DB_HOST
    DB_HOST="${DB_HOST:-<DB_HOST>}"
    read -r -p "  DB port [5432]: " DB_PORT
    DB_PORT="${DB_PORT:-5432}"
    read -r -p "  DB name [ai_agent]: " DB_NAME
    DB_NAME="${DB_NAME:-ai_agent}"
fi

echo ""
echo -e "${BLUE}[server]${NC}"
read -r -p "  Listen address [$DEFAULT_SERVER_HOST] (127.0.0.1 is local only): " SERVER_HOST
SERVER_HOST="${SERVER_HOST:-$DEFAULT_SERVER_HOST}"
read -r -p "  Web port [$DEFAULT_SERVER_PORT]: " SERVER_PORT
SERVER_PORT="${SERVER_PORT:-$DEFAULT_SERVER_PORT}"
if [ -z "$SERVER_HOST" ]; then
    echo -e "${RED}[wizard] ERROR: listen address must not be empty${NC}" >&2
    exit 2
fi
if ! [[ "$SERVER_PORT" =~ ^[0-9]+$ ]] || (( SERVER_PORT < 1 || SERVER_PORT > 65535 )); then
    echo -e "${RED}[wizard] ERROR: web port must be an integer from 1 to 65535${NC}" >&2
    exit 2
fi

echo ""
echo -e "${BLUE}[llm]${NC}"
read -r -p "  LLM API URL (leave empty to configure after bootstrap): " LLM_URL
read -r -p "  LLM model ID (provider model identifier; leave empty if URL is empty): " LLM_MODEL
if { [ -n "$LLM_URL" ] && [ -z "$LLM_MODEL" ]; } || { [ -z "$LLM_URL" ] && [ -n "$LLM_MODEL" ]; }; then
    echo -e "${RED}[wizard] ERROR: LLM API URL and model ID must be configured together${NC}" >&2
    exit 2
fi
read_masked_secret "  LLM API key (leave empty if none): " LLM_KEY
if [ -n "$LLM_URL" ]; then
    echo "  Verifying LLM endpoint and model ID (bounded 1-token probe)..."
    export LLM_URL LLM_MODEL LLM_KEY
    if ! "$PY_BIN" <<'PYEOF'
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

url = os.environ["LLM_URL"].strip().rstrip("/")
model = os.environ["LLM_MODEL"].strip()
parsed = urlsplit(url)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit("[wizard] ERROR: LLM API URL must be an absolute HTTP(S) URL")
if parsed.username or parsed.password or parsed.query or parsed.fragment:
    raise SystemExit("[wizard] ERROR: LLM API URL must not contain credentials, a query, or a fragment")

headers = {"Content-Type": "application/json"}
api_key = os.environ.get("LLM_KEY", "")
if api_key:
    headers["Authorization"] = "Bearer " + api_key
request = urllib.request.Request(
    url + "/chat/completions",
    data=json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "health check"}],
        "max_tokens": 1,
        "stream": False,
    }).encode("utf-8"),
    headers=headers,
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
except (urllib.error.URLError, TimeoutError, ValueError):
    raise SystemExit("[wizard] ERROR: LLM endpoint probe failed") from None
if not isinstance(payload, dict) or not payload.get("choices"):
    raise SystemExit("[wizard] ERROR: LLM endpoint returned no completion")
observed = str(payload.get("model") or "").strip().lower()
expected = model.lower()
observed_base = observed.rsplit("/", 1)[-1]
expected_base = expected.rsplit("/", 1)[-1]
exact = bool(observed) and (observed == expected or observed_base == expected_base)
version = observed_base[len(expected_base) + 1:] if observed_base.startswith(expected_base + "-") else ""
versioned_alias = re.fullmatch(r"(?:\d{3,8}|\d{4}-\d{2}-\d{2})", version) is not None
if not exact and not versioned_alias:
    raise SystemExit("[wizard] ERROR: LLM endpoint returned a different model ID")
PYEOF
    then
        exit 2
    fi
    echo -e "${GREEN}  LLM endpoint and model ID verified${NC}"
fi

echo ""
echo -e "${BLUE}[embedding]${NC}"
echo "  Execution mode:"
echo "    1) PLATFORM_MANAGED   Platform calls the configured provider"
echo "    2) ENTERPRISE_DIRECT  Agent calls the enterprise provider directly"
echo "    3) ENTERPRISE_PROXY   Agent calls through an enterprise gateway"
echo "    4) PRECOMPUTED_IMPORT Agent imports precomputed vectors"
echo "    5) NONE               Disable vector generation and vector retrieval"
read -r -p "  Select [1]: " EMB_MODE_SELECT
case "${EMB_MODE_SELECT:-1}" in
    1) EMB_MODE="PLATFORM_MANAGED" ;;
    2) EMB_MODE="ENTERPRISE_DIRECT" ;;
    3) EMB_MODE="ENTERPRISE_PROXY" ;;
    4) EMB_MODE="PRECOMPUTED_IMPORT" ;;
    5) EMB_MODE="NONE" ;;
    *) echo -e "${RED}[wizard] ERROR: invalid Embedding execution mode${NC}"; exit 2 ;;
esac
if [ "$EMB_MODE" = "NONE" ]; then
    EMB_URL=""
    EMB_MODEL=""
    EMB_DIM="0"
    EMB_KEY=""
    EMB_PROFILE_KEY="platform-default"
    EMB_DISTANCE="COSINE"
    EMB_NORMALIZE="true"
    EMB_SECRET_REF=""
else
    read -r -p "  Embedding API URL (leave empty for Agent-side secret reference): " EMB_URL
    read -r -p "  Embedding model [text-embedding-bge-m3]: " EMB_MODEL
    EMB_MODEL="${EMB_MODEL:-text-embedding-bge-m3}"
    read -r -p "  Embedding dimension [1024]: " EMB_DIM
    EMB_DIM="${EMB_DIM:-1024}"
    read_masked_secret "  Embedding API key (leave empty if none or Agent-side): " EMB_KEY
    read -r -p "  Profile key [platform-default]: " EMB_PROFILE_KEY
    EMB_PROFILE_KEY="${EMB_PROFILE_KEY:-platform-default}"
    read -r -p "  Distance metric [COSINE]: " EMB_DISTANCE
    EMB_DISTANCE="${EMB_DISTANCE:-COSINE}"
    read -r -p "  Normalize vectors? [Y/n]: " EMB_NORMALIZE_ANSWER
    case "${EMB_NORMALIZE_ANSWER:-Y}" in
        [Nn]*) EMB_NORMALIZE="false" ;;
        *) EMB_NORMALIZE="true" ;;
    esac
    read -r -p "  Enterprise secret reference (optional): " EMB_SECRET_REF
fi

# --- Step 5: write back via python ------------------------------------------
# Build the override as a JSON object, then merge into config.json. We pass
# values via environment variables to avoid quoting pitfalls in the heredoc.
export DB_USER DB_PASS DB_SHAPE DB_DSN DB_HOST DB_PORT DB_NAME
export SERVER_HOST SERVER_PORT
export LLM_URL LLM_MODEL LLM_KEY
export EMB_URL EMB_MODEL EMB_DIM EMB_KEY EMB_MODE EMB_PROFILE_KEY EMB_DISTANCE EMB_NORMALIZE EMB_SECRET_REF
export CONFIG_FILE

"$PY_BIN" <<'PYEOF'
import json, os, secrets

cfg_path = os.environ["CONFIG_FILE"]
with open(cfg_path) as f:
    c = json.load(f)

c["database"]["user"] = os.environ["DB_USER"]
c["database"]["password"] = os.environ["DB_PASS"]
if os.environ["DB_SHAPE"] == "dsn":
    c["database"]["dsn"] = os.environ["DB_DSN"]
else:
    c["database"]["host"] = os.environ["DB_HOST"]
    c["database"]["port"] = int(os.environ["DB_PORT"])
    c["database"]["database"] = os.environ["DB_NAME"]

c.setdefault("server", {})
c["server"]["host"] = os.environ["SERVER_HOST"]
c["server"]["port"] = int(os.environ["SERVER_PORT"])

c.setdefault("llm", {})
c["llm"]["api_url"] = os.environ["LLM_URL"]
c["llm"]["model"] = os.environ["LLM_MODEL"]
c["llm"]["api_key"] = os.environ["LLM_KEY"]

c.setdefault("security", {})
if not c["security"].get("secret_key") or str(c["security"]["secret_key"]).startswith("<"):
    c["security"]["secret_key"] = secrets.token_urlsafe(48)

c.setdefault("embedding", {})
c["embedding"]["api_url"] = os.environ["EMB_URL"]
c["embedding"]["model"] = os.environ["EMB_MODEL"]
c["embedding"]["dimension"] = int(os.environ["EMB_DIM"])
c["embedding"]["api_key"] = os.environ["EMB_KEY"]
c["embedding"]["execution_mode"] = os.environ["EMB_MODE"]
c["embedding"]["profile_key"] = os.environ["EMB_PROFILE_KEY"]
c["embedding"]["distance_metric"] = os.environ["EMB_DISTANCE"].upper()
c["embedding"]["normalize_vectors"] = os.environ["EMB_NORMALIZE"].lower() == "true"
c["embedding"]["secret_reference"] = os.environ["EMB_SECRET_REF"]

with open(cfg_path, "w") as f:
    json.dump(c, f, indent=4)
print("[wizard] config.json written")
PYEOF

# --- Step 6: verify ---------------------------------------------------------
if ! [ -f "$CONFIG_FILE" ] || has_placeholder; then
    echo -e "${RED}[wizard] ERROR: failed to write config.json or placeholders remain.${NC}"
    exit 2
fi

echo ""
echo -e "${GREEN}[wizard] Done. config.json is ready.${NC}"
echo -e "${GREEN}[wizard] Web service binding: ${SERVER_HOST}:${SERVER_PORT}${NC}"
echo -e "${YELLOW}[wizard] Sensitive sections will be auto-encrypted when the server starts.${NC}"
exit 0
