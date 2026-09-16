"""Prevent known Oracle-reserved bind names from returning in shared SQL."""
import ast
from pathlib import Path
import re


def test_sql_uses_portable_bind_names():
    failures=[]
    for path in (Path(__file__).resolve().parents[1]/'lib').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node,ast.Constant) or not isinstance(node.value,str):
                continue
            text=node.value
            if text.lstrip().startswith('(?') or not re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|VALUES|SET|WHERE|JOIN)\b',text,re.I):
                continue
            banned=set(re.findall(r'(?<!:):([a-zA-Z][a-zA-Z0-9_]*)',text)) & {'audit','by','user','grant','level','mode','uid'}
            if banned:
                failures.append((path.name,node.lineno,sorted(banned)))
    assert not failures, 'Oracle ORA-01745 bind names: '+repr(failures)
