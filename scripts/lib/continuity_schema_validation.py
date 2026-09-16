"""Read-only native structure verification for the continuity migration ledger."""
import re


def check_expression(value):
    """Canonical AST for the limited SQL CHECK grammar used by these entities."""
    value=re.sub(r'::(?:character varying|character|text|bpchar|integer)(?:\[\])?', '', value, flags=re.I)
    value=re.sub(r'=\s*ANY\s*\(\s*\(\s*ARRAY\s*\[([^]]*)\]\s*\)\s*\)',r' IN (\1)',value,flags=re.I)
    value=re.sub(r'=\s*ANY\s*\(\s*ARRAY\s*\[([^]]*)\]\s*\)',r' IN (\1)',value,flags=re.I)
    value=value.replace('"','')
    tokens=re.findall(r"'(?:[^']|'')*'|[A-Za-z_][A-Za-z_0-9]*|\d+|<>|>=|<=|!=|[(),=<>]",value)
    if ''.join(tokens)!=re.sub(r'\s+','',value):
        # Comparison ignores whitespace outside literals only; schema values
        # contain no spaces. Unsupported expressions fail closed.
        raise ValueError('Unsupported CHECK expression')
    tokens=[token if token.startswith("'") else token.upper() for token in tokens]
    position=0
    def expression(minimum=0):
        nonlocal position
        if position>=len(tokens):
            raise ValueError('Incomplete CHECK expression')
        token=tokens[position]
        position+=1
        if token=='(':
            left=expression()
            if tokens[position]!=')': raise ValueError('Unbalanced CHECK expression')
            position+=1
        elif token.startswith("'") or token.isdecimal() or re.fullmatch(r'[A-Z_][A-Z_0-9]*',token):
            left=('VALUE',token)
        else:
            raise ValueError('Unsupported CHECK operand')
        while position<len(tokens):
            op=tokens[position]
            priority={'OR':1,'AND':2,'=':3,'<>':3,'!=':3,'>':3,'<':3,'>=':3,'<=':3,'IN':3,'IS':3}.get(op,-1)
            if priority<minimum: break
            position+=1
            if op=='IS':
                negative=tokens[position]=='NOT'
                position+=int(negative)
                if tokens[position]!='NULL': raise ValueError('Unsupported IS predicate')
                position+=1
                left=('IS_NOT_NULL' if negative else 'IS_NULL',left)
            elif op=='IN':
                if tokens[position]!='(': raise ValueError('Unsupported IN predicate')
                position+=1
                values=[]
                while True:
                    values.append(expression(4))
                    separator=tokens[position]
                    position+=1
                    if separator==')': break
                    if separator!=',': raise ValueError('Unsupported IN list')
                left=('IN',left,tuple(sorted(values)))
            else:
                left=(op,left,expression(priority+1))
        return left
    result=expression()
    if position!=len(tokens): raise ValueError('Trailing CHECK expression')
    return result


def default_expression(value):
    if hasattr(value,'read'): value=value.read()
    if value is None: return None
    value=re.sub(r'::(?:character varying|character|text|bpchar)(?:\(\d+\))?\s*$', '',str(value),flags=re.I)
    tokens=re.findall(r"'(?:[^']|'')*'|[^']+",value)
    return ''.join(token if token.startswith("'") else re.sub(r'[\s()]','',token).upper() for token in tokens)


def errors(cursor,db,facts):
    failures=[]
    pg=db in {'pg','postgresql'}
    def query(sql,table):
        cursor.execute(sql, (table.lower(),) if pg else {'table_name':table})
        return cursor.fetchall()
    def key(value):
        kind,columns,parent,refs=value
        return kind,tuple(columns),parent,tuple(refs)
    def default(value):
        return default_expression(value)
    for table,expected in facts.items():
        if pg:
            rows=query("SELECT upper(a.attname),format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a "
                       "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                       "WHERE a.attrelid=to_regclass(%s) AND a.attnum>0 AND NOT a.attisdropped",table)
            columns={str(name):[str(dtype).upper().replace('CHARACTER VARYING','VARCHAR').replace('CHARACTER','CHAR').replace('TIMESTAMP WITHOUT TIME ZONE','TIMESTAMP'),bool(required),default(value)] for name,dtype,required,value in rows}
        else:
            rows=query("SELECT COLUMN_NAME,DATA_TYPE,CHAR_LENGTH,NULLABLE,DATA_PRECISION,DATA_SCALE,DATA_DEFAULT FROM USER_TAB_COLUMNS WHERE TABLE_NAME=:table_name",table)
            columns={}
            for name,dtype,length,nullable,precision,scale,value in rows:
                dtype=str(dtype)
                if dtype in {'VARCHAR2','VARCHAR','CHAR'}:
                    dtype=('VARCHAR' if dtype.startswith('VARCHAR') else 'CHAR')+'('+str(length)+')'
                elif dtype.startswith('TIMESTAMP'):
                    dtype='TIMESTAMP'
                elif dtype=='NUMBER' and precision in {None,38} and scale==0:
                    dtype='INTEGER'
                elif dtype=='NUMBER' and precision is not None and scale==0:
                    dtype='NUMBER('+str(precision)+')'
                columns[str(name)]=[dtype,nullable=='N',default(value)]
        if columns!={name:[value['type'],value['not_null'],value['default']] for name,value in expected['columns'].items()}:
            failures.append(table+':COLUMNS')
        actual=[]
        check_count=0
        check_expressions=[]
        if pg:
            rows=query("SELECT c.contype,ARRAY(SELECT upper(a.attname) FROM unnest(c.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord), "
                       "COALESCE(upper((SELECT relname FROM pg_class WHERE oid=c.confrelid)),''),"
                       "ARRAY(SELECT upper(a.attname) FROM unnest(c.confkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY k.ord),c.convalidated,pg_get_expr(c.conbin,c.conrelid) "
                       "FROM pg_constraint c WHERE c.conrelid=to_regclass(%s)",table)
            for kind,names,parent,refs,validated,condition in rows:
                if not validated:
                    failures.append(table+':UNVALIDATED')
                if kind in {'p','u','f'}:
                    actual.append(['R' if kind=='f' else kind.upper(),names,parent,refs])
                if kind=='c':
                    check_count+=1
                    check_expressions.append(condition)
            triggers=query("SELECT tgname,tgenabled FROM pg_trigger WHERE tgrelid=to_regclass(%s) AND NOT tgisinternal",table)
            if (expected['trigger'].lower(),'O') not in triggers:
                failures.append(table+':IMMUTABILITY_TRIGGER')
            grants=query("SELECT grantee,privilege_type FROM information_schema.table_privileges WHERE table_schema=current_schema() AND table_name=%s AND grantee<>current_user",table)
        else:
            rows=query("SELECT CONSTRAINT_NAME,CONSTRAINT_TYPE,STATUS,VALIDATED,R_CONSTRAINT_NAME,SEARCH_CONDITION FROM USER_CONSTRAINTS WHERE TABLE_NAME=:table_name",table)
            for name,kind,status,validated,parent_constraint,condition in rows:
                if status!='ENABLED' or validated!='VALIDATED':
                    failures.append(table+':UNVALIDATED')
                if kind in {'P','U','R'}:
                    cursor.execute("SELECT COLUMN_NAME FROM USER_CONS_COLUMNS WHERE CONSTRAINT_NAME=:constraint_name ORDER BY POSITION",{'constraint_name':name})
                    names=[item[0] for item in cursor.fetchall()]
                    parent=''
                    refs=[]
                    if kind=='R':
                        cursor.execute("SELECT TABLE_NAME,COLUMN_NAME FROM USER_CONS_COLUMNS WHERE CONSTRAINT_NAME=:constraint_name ORDER BY POSITION",{'constraint_name':parent_constraint})
                        parent_rows=cursor.fetchall()
                        parent=parent_rows[0][0] if parent_rows else ''
                        refs=[item[1] for item in parent_rows]
                    actual.append([kind,names,parent,refs])
                if kind=='C':
                    condition=condition.read() if hasattr(condition,'read') else str(condition or '')
                    if not re.fullmatch(r'\s*"?\w+"?\s+IS\s+NOT\s+NULL\s*',condition,re.I):
                        check_count+=1
                        check_expressions.append(condition)
            triggers=query("SELECT TRIGGER_NAME,STATUS FROM USER_TRIGGERS WHERE TABLE_NAME=:table_name",table)
            if (expected['trigger'],'ENABLED') not in triggers:
                failures.append(table+':IMMUTABILITY_TRIGGER')
            catalogue='ALL_TAB_PRIVS WHERE OWNER=USER AND' if db=='yashandb' else 'USER_TAB_PRIVS_MADE WHERE'
            grants=query("SELECT GRANTEE,PRIVILEGE FROM "+catalogue+" TABLE_NAME=:table_name",table)
            if db=='yashandb':
                # YashanDB lists role grants separately; ALL_TAB_PRIVS alone
                # must not certify a control-plane table as inaccessible.
                grants+=query("SELECT ROLE,PRIVILEGE FROM ROLE_TAB_PRIVS WHERE OWNER=USER AND TABLE_NAME=:table_name",table)
        if {key(item) for item in actual}!={key(item) for item in expected['keys']}:
            failures.append(table+':RELATIONAL_KEYS')
        if check_count!=expected['checks']:
            failures.append(table+':CHECK_CONSTRAINTS')
        try:
            if {check_expression(value) for value in check_expressions}!={check_expression(value) for value in expected['check_expressions']}:
                failures.append(table+':CHECK_EXPRESSIONS')
        except (ValueError,IndexError):
            failures.append(table+':CHECK_EXPRESSIONS')
        if grants:
            failures.append(table+':END_USER_GRANTS')
    return failures
