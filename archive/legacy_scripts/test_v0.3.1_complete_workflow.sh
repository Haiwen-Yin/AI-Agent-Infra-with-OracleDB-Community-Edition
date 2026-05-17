#!/bin/bash
# test_v0.3.1_complete_workflow.sh - Complete workflow demonstration for v0.3.1

set -e

echo "========================================"
echo "Oracle Memory System v0.3.1 Test Suite"
echo "========================================"
echo ""

NODE_ID=10020  # Start from this ID to avoid conflicts

# Test Case 1: Chinese text (1024 dimensions)
echo "=== Test 1: Chinese Text ==="
python scripts/generate_vector_insert_sql.py \
    "Oracle AI Database Memory System v0.3.1 测试 - 中文文本向量导入验证" \
    --node-id $NODE_ID \
    --node-type "test_chinese_v0.3.1"

echo ""

# Test Case 2: English text (1024 dimensions)
echo "=== Test 2: English Text ==="
python scripts/generate_vector_insert_sql.py \
    "Oracle AI Database Memory System v0.3.1 Complete Workflow Test - English text vector import validation using CLOB + TO_VECTOR() method for full 1024 dimensional vectors." \
    --node-id $((NODE_ID+1)) \
    --node-type "test_english_v0.3.1"

echo ""

# Test Case 3: Mixed content (1024 dimensions)
echo "=== Test 3: Mixed Content ==="
python scripts/generate_vector_insert_sql.py \
    "混合文本测试 - Oracle AI Database + PostgreSQL + MySQL 数据库专家知识图谱构建，支持 BGE-M3 embedding model 和 Active Data Guard 容灾方案。" \
    --node-id $((NODE_ID+2)) \
    --node-type "test_mixed_v0.3.1"

echo ""
echo "========================================"
echo "All SQL files generated successfully!"
echo "Executing batch insert..."
echo "========================================"
echo ""

# Execute all inserts
/root/sqlcl/bin/sql -S openclaw/hermes@//10.10.10.130:1521/openclaw <<EOF
-- Batch execute all generated SQL files
@@generate_10020.sql
@@generate_10021.sql
@@generate_10022.sql

-- Verify insertions
SELECT 
    node_id,
    node_type,
    vector_dimension_count(embedding) as dimensions,
    CASE WHEN vector_dimension_count(embedding) = 1024 THEN '✅ SUCCESS' ELSE '❌ FAILED' END as status,
    TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS') as insert_time
FROM openclaw.memory_nodes
WHERE node_id BETWEEN 10020 AND 10022
ORDER BY node_id;

-- Summary statistics
SELECT 
    COUNT(*) as total_records,
    SUM(CASE WHEN vector_dimension_count(embedding) = 1024 THEN 1 ELSE 0 END) as successful_1024,
    ROUND(100.0 * SUM(CASE WHEN vector_dimension_count(embedding) = 1024 THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM openclaw.memory_nodes
WHERE node_id BETWEEN 10020 AND 10022;

EXIT;
EOF

echo ""
echo "========================================"
echo "Test Suite Complete!"
echo "========================================"
