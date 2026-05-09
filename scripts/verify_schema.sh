#!/bin/bash
# Oracle Memory System v1.0.0 - Schema Verification Script
# Author: 胖头鱼 🐟 (Haiwen Yin)
# Usage: bash verify_schema.sh
# Purpose: Verify actual database schema before writing Python API code

SQLCL="/root/sqlcl/sqlcl/bin/sql"
DB="openclaw/hermes@//10.10.10.130:1521/openclaw"

echo "=========================================="
echo "Oracle Memory System - Schema Verification"
echo "=========================================="
echo ""

# List all tables
echo "--- All User Tables ---"
echo "SELECT table_name FROM user_tables ORDER BY table_name" | $SQLCL $DB 2>/dev/null | grep -v "^$" | grep -v "Connected to" | grep -v "Copyright" | grep -v "SQLcl" | grep -v "Last Successful" | grep -v "Release" | grep -v "Version" | grep -v "Disconnected"

echo ""
echo "--- KNOWLEDGE_CONCEPTS Columns ---"
echo "DESCRIBE KNOWLEDGE_CONCEPTS" | $SQLCL $DB 2>/dev/null | grep -E "^[A-Z]" | head -25

echo ""
echo "--- KNOWLEDGE_GRAPH Columns ---"
echo "DESCRIBE KNOWLEDGE_GRAPH" | $SQLCL $DB 2>/dev/null | grep -E "^[A-Z]" | head -15

echo ""
echo "--- KNOWLEDGE_TAGS Columns ---"
echo "DESCRIBE KNOWLEDGE_TAGS" | $SQLCL $DB 2>/dev/null | grep -E "^[A-Z]" | head -10

echo ""
echo "--- KNOWLEDGE_VERSIONS Columns ---"
echo "DESCRIBE KNOWLEDGE_VERSIONS" | $SQLCL $DB 2>/dev/null | grep -E "^[A-Z]" | head -15

echo ""
echo "--- Record Counts ---"
echo "SELECT 'KNOWLEDGE_CONCEPTS' as tbl, COUNT(*) as cnt FROM KNOWLEDGE_CONCEPTS UNION ALL SELECT 'KNOWLEDGE_GRAPH', COUNT(*) FROM KNOWLEDGE_GRAPH UNION ALL SELECT 'KNOWLEDGE_TAGS', COUNT(*) FROM KNOWLEDGE_TAGS" | $SQLCL $DB 2>/dev/null | grep -E "KNOWLEDGE|^[0-9]"

echo ""
echo "=========================================="
echo "Schema verification complete."
echo "Use these actual column names in your Python API code."
echo "=========================================="
