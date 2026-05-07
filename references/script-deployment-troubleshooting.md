# Python CLI Script Deployment & Dependency Troubleshooting Guide

**Version**: v1.0  
**Author**: Haiwen Yin (胖头鱼 🐟)  
**Applicable Scenarios**: Oracle Memory System Python CLI tool deployment, debugging and troubleshooting

---

## 🔍 Common Issues Identification

### Issue A: hermes_tools Import Error
**Symptoms**:
- Python script execution fails with: `ModuleNotFoundError: No module named 'hermes_tools'`
- Script contains `from hermes_tools import terminal, read_file, write_file`

**Root Cause**:
Hermes Agent's Python CLI tools are **independently running tools** and should NOT depend on the Hermes Agent runtime library.

### Issue B: Oracle Database Connection Format Error
**Symptom**: ORA-12263: Failed to access tnsnames.ora

---

## 🛠️ Fix Steps

### Step 1: Identify Incorrect Imports

```bash
grep -r "from hermes_tools import" scripts/
```

**Expected Output** (if there's an issue):
```
scripts/memory_embedding_manager.py:from hermes_tools import terminal, read_file, write_file
scripts/memory_read_splitter.py:from hermes_tools import terminal
```

### Step 2: Remove Incorrect Imports and Replace with Standard Libraries

**Original Code** (Incorrect):
```python
import json
import requests
from hermes_tools import terminal, read_file, write_file
```

**Replace With**:
```python
import json
import os
import sys
import subprocess
import requests
```

### Step 3: Replace `terminal()` Function Calls

**Original Code** (Incorrect):
```python
result = terminal(f"/root/sqlcl/bin/sql-mcp.sh {conn_string} << 'EOF'\n{sql}\nEXIT;", timeout=30)
output = result.get('output', '')
```

**Replace With** (Correct):
```python
def run_sql_command(conn_string, sql_query):
    """Execute SQL query using SQLcl and return output."""
    import subprocess
    cmd = f"/root/sqlcl/bin/sql-mcp.sh {conn_string} << 'EOF'\n{sql_query}\nEXIT;"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return {'output': result.stdout + result.stderr, 'returncode': result.returncode}

# Usage:
result = run_sql_command(PRIMARY_CONN, sql)
output = result['output']
```

### Step 4: Verify the Fix

```bash
# Check syntax
python3 -m py_compile /path/to/script.py && echo "✅ OK" || echo "❌ Error"

# Verify no hermes_tools imports remain
grep -r "from hermes_tools import" scripts/ && echo "⚠️ Still found!" || echo "✅ Clean"
```

---

## 📋 Oracle Database Connection Format

### ❌ Incorrect Format (Will Fail)
```bash
PRIMARY_CONN="openclaw@//host:port/service"
# ORA-12263: Failed to access tnsnames.ora
```

### ✅ Correct Format (Recommended)
```bash
PRIMARY_CONN="user/password@//host:port/service"
# Example: openclaw/hermes@//10.10.10.130:1521/openclaw
```

---

## 🚨 Script Corruption Detection Criteria

When any of the following conditions occur, **rewrite the script directly** instead of fixing:

- ✅ Content duplication > 50% (e.g., `def run_sql_command` defined twice)
- ✅ More than 3 syntax errors
- ✅ Chaotic file structure (function boundaries unidentifiable)
- ✅ Git repository unavailable and no backup exists

---

## 📝 Related Resources

- [Oracle AI Database Memory System v0.4.1](https://github.com/Haiwen-Yin/oracle-memory-by-yhw)
- [SQLcl Documentation](https://docs.oracle.com/en/database/sqlcl/)
- [Python subprocess.run() Reference](https://docs.python.org/3/library/subprocess.html#subprocess.run)

---

*Last Updated: 2026-05-07 | Author: Haiwen Yin (胖头鱼 🐟)*
