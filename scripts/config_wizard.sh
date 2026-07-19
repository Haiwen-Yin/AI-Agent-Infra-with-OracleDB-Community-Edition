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

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

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

echo ""
echo -e "${BLUE}[database]${NC}"
read -r -p "  DB user [aiadmin]: " DB_USER
DB_USER="${DB_USER:-aiadmin}"
read -r -s -p "  DB password: " DB_PASS
echo

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
echo -e "${BLUE}[llm]${NC}"
read -r -p "  LLM API URL: " LLM_URL
LLM_URL="${LLM_URL:-<LLM_API_URL>}"
read -r -p "  LLM model name: " LLM_MODEL
LLM_MODEL="${LLM_MODEL:-<LLM_MODEL_NAME>}"
read -r -s -p "  LLM API key (leave empty if none): " LLM_KEY
echo

echo ""
echo -e "${BLUE}[embedding]${NC}"
read -r -p "  Embedding API URL: " EMB_URL
EMB_URL="${EMB_URL:-<EMBEDDING_API_URL>}"
read -r -p "  Embedding model [text-embedding-bge-m3]: " EMB_MODEL
EMB_MODEL="${EMB_MODEL:-text-embedding-bge-m3}"
read -r -p "  Embedding dimension [1024]: " EMB_DIM
EMB_DIM="${EMB_DIM:-1024}"

# --- Step 5: write back via python ------------------------------------------
# Build the override as a JSON object, then merge into config.json. We pass
# values via environment variables to avoid quoting pitfalls in the heredoc.
export DB_USER DB_PASS DB_SHAPE DB_DSN DB_HOST DB_PORT DB_NAME
export LLM_URL LLM_MODEL LLM_KEY
export EMB_URL EMB_MODEL EMB_DIM
export CONFIG_FILE

PY_BIN=$(command -v python3.14 || command -v python3)
"$PY_BIN" <<'PYEOF'
import json, os

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

c.setdefault("llm", {})
c["llm"]["api_url"] = os.environ["LLM_URL"]
c["llm"]["model"] = os.environ["LLM_MODEL"]
c["llm"]["api_key"] = os.environ["LLM_KEY"]

c.setdefault("embedding", {})
c["embedding"]["api_url"] = os.environ["EMB_URL"]
c["embedding"]["model"] = os.environ["EMB_MODEL"]
c["embedding"]["dimension"] = int(os.environ["EMB_DIM"])

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
echo -e "${YELLOW}[wizard] Sensitive sections will be auto-encrypted when the server starts.${NC}"
exit 0
