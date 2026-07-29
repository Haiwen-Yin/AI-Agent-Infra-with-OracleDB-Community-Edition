#!/usr/bin/env python3.14
"""AI Agent Infra - Pure Python Oracle Schema Deploy Tool

Replaces SQLcl for schema deployment. Uses oracledb driver directly.
Handles SQLcl-specific syntax: PROMPT, DEFINE, && substitution, / block terminator.

Usage:
    python3.14 deploy_oracle.py <user> <password> <dsn> <sql_file> [sql_file...]
    
Example:
    python3.14 deploy_oracle.py <user> <password> <host>:1521/<service> scripts/deploy/1_schema.sql
"""
import sys
import os
import re


def parse_defines(content):
    """Extract DEFINE statements and return (defines_dict, content_without_defines)."""
    defines = {}
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        m = re.match(r"^\s*DEFINE\s+(\w+)\s*=\s*'([^']*)'", line, re.IGNORECASE)
        if m:
            defines[m.group(1)] = m.group(2)
        elif re.match(r"^\s*DEFINE\s+(\w+)\s*=\s*(.+)$", line, re.IGNORECASE):
            m2 = re.match(r"^\s*DEFINE\s+(\w+)\s*=\s*(.+)$", line, re.IGNORECASE)
            defines[m2.group(1)] = m2.group(2).strip()
        else:
            new_lines.append(line)
    return defines, '\n'.join(new_lines)


def substitute_vars(content, defines):
    """Replace &&VAR with defined values."""
    for name, value in defines.items():
        content = content.replace(f"&&{name}", value)
    # Fix double dots from &&SCHEMA_OWNER..TABLE -> SCHEMA_OWNER.TABLE
    content = content.replace("..", ".")
    return content


def remove_prompts(content):
    """Remove PROMPT lines (SQLcl display-only commands)."""
    lines = content.split('\n')
    return '\n'.join(line for line in lines if not re.match(r"^\s*PROMPT\s", line, re.IGNORECASE))


def split_statements(content):
    """Split SQL content into individual executable statements.
    
    Uses a line-by-line state machine:
    - Tracks whether we're inside a PL/SQL block (BEGIN/CREATE OR REPLACE)
    - PL/SQL blocks end at '/' on its own line
    - Regular SQL statements end at ';'
    - Skips PROMPT lines and comment-only blocks
    """
    statements = []
    current_stmt = []
    in_plsql = False
    in_string = False
    plsql_depth = 0
    
    lines = content.split('\n')
    
    for line in lines:
        stripped = line.strip()
        
        # Skip PROMPT lines
        if re.match(r'^PROMPT(\s|$)', stripped, re.IGNORECASE):
            continue
        
        # Skip DEFINE lines (already processed)
        if re.match(r'^DEFINE\s', stripped, re.IGNORECASE):
            continue
        
        # Skip SQLcl-specific commands only at a statement boundary.  A
        # blanket SET match corrupts ordinary DML such as UPDATE ... SET.
        at_statement_boundary = not current_stmt or all(
            not line.strip()
            or line.strip().startswith(("--", "/*", "*"))
            for line in current_stmt
        )
        if (
            not in_plsql
            and at_statement_boundary
            and re.match(r'^(WHENEVER|SET\s|SHOW\s|SPOOL|@|@@|CONNECT|EXIT|QUIT|HOST|\.)', stripped, re.IGNORECASE)
        ):
            continue
        
        # Skip comment lines when not in PL/SQL mode
        if not in_plsql:
            # If current_stmt is empty or only has comments, skip comment lines
            only_comments = all(l.strip().startswith('--') or l.strip().startswith('/*') or l.strip().startswith('*') or not l.strip() for l in current_stmt)
            if only_comments and (stripped.startswith('--') or stripped.startswith('/*') or stripped.startswith('*')):
                continue
        
        # Check for PL/SQL block start
        if not in_plsql and re.match(r'^(BEGIN|DECLARE)\b', stripped, re.IGNORECASE):
            in_plsql = True
        elif re.match(r'^CREATE\s+OR\s+REPLACE\s+(PACKAGE|PROCEDURE|FUNCTION|TRIGGER|TYPE)\b', stripped, re.IGNORECASE):
            if in_plsql:
                # New CREATE OR REPLACE while already in PL/SQL - flush previous statement
                stmt = '\n'.join(current_stmt).strip()
                if stmt and not is_comment_only(stmt):
                    statements.append(stmt)
                current_stmt = []
                plsql_depth = 0
            in_plsql = True
            # Clear any accumulated comment-only lines from current_stmt
            cleaned = []
            found_code = False
            for cl in current_stmt:
                cs = cl.strip()
                if not found_code and (not cs or cs.startswith('--') or cs.startswith('/*') or cs.startswith('*')):
                    continue
                found_code = True
                cleaned.append(cl)
            current_stmt = cleaned
        
        # Check for '/' terminator (PL/SQL block end)
        if stripped == '/':
            if in_plsql:
                stmt = '\n'.join(current_stmt).strip()
                if stmt and not is_comment_only(stmt):
                    statements.append(stmt)
                current_stmt = []
                in_plsql = False
                plsql_depth = 0
            # If not in PL/SQL, just skip the '/' line
            continue
        
        # Handle string state for semicolon detection
        if in_plsql:
            # Inside PL/SQL - accumulate everything until '/'
            current_stmt.append(line)
        else:
            # Regular SQL - check for semicolons
            current_stmt.append(line)
            # Simple check: if line ends with ';' (not inside string), split
            if stripped.endswith(';') and not in_string:
                stmt = '\n'.join(current_stmt).strip()
                if stmt and not is_comment_only(stmt):
                    statements.append(stmt)
                current_stmt = []
    
    # Don't forget trailing content
    stmt = '\n'.join(current_stmt).strip()
    if stmt and not is_comment_only(stmt):
        statements.append(stmt)
    
    return statements


def split_by_semicolon(text):
    """Split by semicolons, respecting single-quoted strings."""
    statements = []
    current = []
    in_string = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "'":
            in_string = not in_string
            current.append(char)
        elif char == ';' and not in_string:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)
        i += 1
    # Don't forget the last statement
    last = ''.join(current).strip()
    if last:
        statements.append(last)
    return statements


def is_comment_only(text):
    """Check if text is only comments or whitespace."""
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('--') or line.startswith('/*') or line.startswith('*') or line.startswith('PROMPT'):
            continue
        return False
    return True


def execute_sql_file(conn, sql_file, verbose=True):
    """Execute all statements in a SQL file."""
    with open(sql_file, 'r') as f:
        content = f.read()
    
    # Preprocess
    defines, content = parse_defines(content)
    content = substitute_vars(content, defines)
    content = remove_prompts(content)
    
    # Convert SQLcl EXEC to PL/SQL BEGIN...END;
    content = re.sub(
        r'^EXEC\s+(.+?);?\s*$', r'BEGIN \1; END;\n/', content,
        flags=re.MULTILINE,
    )
    
    # Split into statements
    statements = split_statements(content)
    
    if verbose:
        print(f"  [{os.path.basename(sql_file)}] {len(statements)} statements to execute")
    
    success = 0
    failed = 0
    
    for i, stmt in enumerate(statements, 1):
        # Get first line for logging
        first_line = stmt.split('\n')[0][:80].strip()
        
        try:
            cur = conn.cursor()
            cur.execute(stmt)
            conn.commit()
            success += 1
            if verbose and (i % 20 == 0 or i <= 3):
                print(f"    [{i}/{len(statements)}] OK: {first_line}")
        except Exception as e:
            failed += 1
            err = str(e).replace('\n', ' ')[:120]
            # Skip "already exists" errors (expected during re-deployment)
            if "ORA-00955" in str(e) or "already exists" in str(e).lower():
                if verbose:
                    print(f"    [{i}/{len(statements)}] SKIP (exists): {first_line}")
                success += 1
                failed -= 1
            elif "ORA-01430" in str(e) or "ORA-02260" in str(e):
                if verbose:
                    print(f"    [{i}/{len(statements)}] SKIP (exists): {first_line}")
                success += 1
                failed -= 1
            else:
                print(f"    [{i}/{len(statements)}] ERROR: {first_line}")
                print(f"           {err}")
    
    if verbose:
        print(f"  [{os.path.basename(sql_file)}] Done: {success} success, {failed} failed")
    
    return failed == 0


def main():
    # Keep parser helpers usable in offline tooling and tests.  The Oracle
    # driver is needed only when a real connection is requested.
    try:
        import oracledb
    except ImportError as exc:
        print("oracledb is required to execute Oracle deployment", file=sys.stderr)
        raise SystemExit(2) from exc
    if len(sys.argv) < 5:
        print("Usage: python3.14 deploy_oracle.py [--sysdba] <user> <password> <dsn> <sql_file> [sql_file...]")
        print("Example: python3.14 deploy_oracle.py <user> <password> <host>:1521/<service> scripts/deploy/1_schema.sql")
        print("         python3.14 deploy_oracle.py --sysdba sys <password> <host>:1521/<service> scripts/deploy/4_grants.sql")
        sys.exit(1)
    
    args = sys.argv[1:]
    use_sysdba = False
    if args[0] == '--sysdba':
        use_sysdba = True
        args = args[1:]
    
    user = args[0]
    password = args[1]
    dsn = args[2]
    sql_files = args[3:]
    
    print(f"[deploy] Connecting to {user}@{dsn}{' (SYSDBA)' if use_sysdba else ''}...")
    
    try:
        if use_sysdba:
            conn = oracledb.connect(user=user, password=password, dsn=dsn, mode=oracledb.SYSDBA)
        else:
            conn = oracledb.connect(user=user, password=password, dsn=dsn)
    except Exception as e:
        print(f"[deploy] Connection failed: {e}")
        sys.exit(1)
    
    print(f"[deploy] Connected. Processing {len(sql_files)} SQL file(s)...")
    print()
    
    total_failed = 0
    for sql_file in sql_files:
        if not os.path.isfile(sql_file):
            print(f"  [ERROR] File not found: {sql_file}")
            total_failed += 1
            continue
        
        print(f"[deploy] Executing: {sql_file}")
        ok = execute_sql_file(conn, sql_file)
        if not ok:
            total_failed += 1
        print()
    
    conn.close()
    
    if total_failed == 0:
        print(f"[deploy] All SQL files executed successfully.")
        sys.exit(0)
    else:
        print(f"[deploy] Completed with {total_failed} file(s) having errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
