"""Persisted server-observed diagnostics; client assertions cannot create PASS."""
from . import connection,identity_api,continuity_work as work
from .continuity_contracts import NewDiagnosticRun,DiagnosticCheck,CapabilitiesRequest,Family,request_digest
from .continuity_state import diagnostic_status,ContinuityError,require_idempotent_request
import re


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    return [
        "CREATE TABLE CX_DIAGNOSTIC_RUNS (RUN_ID VARCHAR(128) PRIMARY KEY, REQUEST_ID VARCHAR(128) NOT NULL, "
        "PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('PASS','FAIL','UNAVAILABLE','UNOBSERVED')), "
        "CHECK_COUNT INTEGER NOT NULL CHECK(CHECK_COUNT>0), PURPOSE VARCHAR(1000) NOT NULL, "
        "IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UNIQUE(PRINCIPAL_ID,IDEMPOTENCY_KEY))",
        "CREATE TABLE CX_DIAGNOSTIC_CHECKS (RUN_ID VARCHAR(128) NOT NULL REFERENCES CX_DIAGNOSTIC_RUNS(RUN_ID), "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), CHECK_CODE VARCHAR(64) NOT NULL, "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('PASS','FAIL','UNAVAILABLE','UNOBSERVED')), OBSERVED CHAR(1) NOT NULL CHECK(OBSERVED IN ('Y','N')), "
        "DETAIL_CODE VARCHAR(128) NOT NULL, PRIMARY KEY(RUN_ID,ITEM_NO), UNIQUE(RUN_ID,CHECK_CODE), "
        "CHECK((STATUS IN ('PASS','FAIL') AND OBSERVED='Y') OR (STATUS='UNOBSERVED' AND OBSERVED='N') OR STATUS='UNAVAILABLE'))",
    ]


def _result(code,status,detail):
    return DiagnosticCheck(check_code=code,status=status,observed=status in {'PASS','FAIL'},detail_code=detail)


def capabilities(actor,value):
    """Report implemented contracts only after current domain authorization.

    Availability of an operation is distinct from authority over any resource
    and from runtime observation of that operation's success.
    """
    request=CapabilitiesRequest.model_validate(value)
    def perform(tx):
        work._lock_actor(tx,actor)
        work._authorize(tx,actor,request.security_domain_id,write=False)
        from .continuity_client import OPERATIONS
        version={'status':'UNAVAILABLE','detail_code':'SERVER_VERSION_NOT_OBSERVED'}
        try:
            observed=connection.database_version_observation()
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,5}',observed):
                version={'status':'PASS','version':observed,'detail_code':'DATABASE_SERVER_METADATA'}
        except Exception:
            pass
        return {'security_domain_id':request.security_domain_id,
                'database':connection.DATABASE_DIALECT,
                'database_version':version,
                'entrypoints':{name:'IMPLEMENTED' for name in ('DASHBOARD','PORTAL','GATEWAY','MCP','CLI')},
                'entrypoint_parity':'UNOBSERVED',
                'managed_skill_runtime':'COOPERATIVE_LINUX',
                'operations':sorted(OPERATIONS),
                'sources':{family.value:('EXACT_VERSION' if family.value in {'MEMORY','HANDOFF','HANDOFF_OUTCOME'}
                          else 'PROMOTED_ARTIFACT_ONLY' if family.value in {'KNOWLEDGE','EXPERIENCE','SKILL'}
                          else 'CAPTURED_NATIVE_PROJECTION' if family.value in {'TASK','GRAPH','DB4A2A','AUDIT'}
                          else 'UNAVAILABLE') for family in Family},
                'direct_agent_sql':'DENIED',
                'runtime_verification':'UNOBSERVED',
                'resource_authorization':'RECHECKED_PER_OPERATION'}
    return connection.execute_transaction_callback(perform)


def _check(tx,actor,request,code):
    if code=='PRINCIPAL':
        row=tx.query_one("SELECT STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor",{'actor':actor})
        return _result(code,'PASS' if row and row['status']=='ACTIVE' else 'FAIL','PRINCIPAL_STATUS')
    if code=='DOMAIN':
        work._authorize(tx,actor,request.security_domain_id,write=False)
        return _result(code,'PASS','CURRENT_DOMAIN_AUTHORITY')
    if code=='DATABASE':
        row=tx.query_one('SELECT CURRENT_TIMESTAMP AS OBSERVED_AT'+connection.scalar_select_suffix(),{})
        return _result(code,'PASS' if row and row['observed_at'] is not None else 'FAIL','DATABASE_QUERY')
    if code=='SOURCE_ACCESS':
        if not request.sources:
            return _result(code,'UNOBSERVED','NO_SOURCES_REQUESTED')
        from .continuity_sources import resolve
        for source in request.sources:
            resolve(tx,actor,request.security_domain_id,source,purpose=request.purpose)
        return _result(code,'PASS','EXACT_SOURCES_AUTHORIZED')
    if code=='CONTEXT_INPUT':
        if not request.assembly_id:
            return _result(code,'UNOBSERVED','NO_ASSEMBLY_REQUESTED')
        from .continuity_assembly import _read
        assembly=_read(tx,actor,request.assembly_id)
        domain=tx.query_one("SELECT SECURITY_DOMAIN_ID FROM CX_CONTEXT_ASSEMBLIES WHERE ASSEMBLY_ID=:assembly",{'assembly':request.assembly_id})
        if domain['security_domain_id']!=request.security_domain_id:
            raise PermissionError('Diagnostic scope mismatch')
        use=tx.query_one("SELECT STATUS,CONTENT_DIGEST,ITEM_COUNT FROM CX_CONTEXT_INPUT_USES WHERE ASSEMBLY_ID=:assembly AND PRINCIPAL_ID=:actor",
                         {'assembly':request.assembly_id,'actor':actor})
        if not use or use['status']!='SENT' or assembly['status']!='SENT':
            return _result(code,'UNOBSERVED','NO_COMPLETED_INPUT_OBSERVATION')
        valid=use['content_digest']==assembly['content_digest'] and int(use['item_count'])==assembly['item_count']
        return _result(code,'PASS' if valid else 'FAIL','EXACT_INPUT_RECEIPT')
    if code=='INSTANCE':
        if not request.instance_id:
            return _result(code,'UNOBSERVED','NO_INSTANCE_REQUESTED')
        row=tx.query_one("SELECT STATUS FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance AND AGENT_ID=:actor "
                         "AND SECURITY_DOMAIN_ID=:domain AND STATUS='ACTIVE' AND REVOKED_AT IS NULL AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
                         {'instance':request.instance_id,'actor':actor,'domain':request.security_domain_id})
        return _result(code,'PASS' if row else 'FAIL','CURRENT_INSTANCE_LEASE')
    if code=='SKILL_DELIVERY':
        if not request.distribution_id:
            return _result(code,'UNOBSERVED','NO_DISTRIBUTION_REQUESTED')
        row=tx.query_one("SELECT d.MESSAGE_STATE,d.ACKNOWLEDGEMENT_STATE,d.ACTIVATION_STATE,d.DRIFT_STATE,d.SKILL_VERSION,p.SIGNATURE_STATE,p.PACKAGE_VERSION,p.PACKAGE_DIGEST "
                         "FROM CX_SKILL_DISTRIBUTION d JOIN CX_UPGRADE_PLANS p ON p.UPGRADE_ID=d.UPGRADE_ID "
                         "WHERE d.DISTRIBUTION_ID=:distribution AND d.AGENT_ID=:actor",
                         {'distribution':request.distribution_id,'actor':actor})
        if not row:
            return _result(code,'FAIL','DISTRIBUTION_ACCESS_DENIED')
        valid=(row['message_state']=='SENT' and row['acknowledgement_state']=='ACKNOWLEDGED' and row['activation_state']=='ACTIVE'
               and row['drift_state']=='IN_SYNC' and row['signature_state']=='VERIFIED'
               and row['skill_version']==row['package_version'] and len(str(row['package_digest'] or ''))==64
               and all(char in '0123456789abcdef' for char in str(row['package_digest'] or '')))
        # Activation state is an authenticated Agent attestation. It is not an
        # independent observation that the external runtime switched files.
        return _result(code,'UNOBSERVED' if valid else 'FAIL',
                       'RUNTIME_SWITCH_NOT_OBSERVED' if valid else 'INVALID_DISTRIBUTION_STATE')
    # A reached HTTP route alone is not evidence that MCP/CLI/Skill use the
    # same authorization. Only an integrated entrypoint gate may attest that.
    return _result(code,'UNOBSERVED','ENTRYPOINT_PARITY_NOT_OBSERVED')


def _read(tx,actor,run_id):
    row=tx.query_one("SELECT RUN_ID,REQUEST_ID,SECURITY_DOMAIN_ID,STATUS,CHECK_COUNT,CREATED_AT FROM CX_DIAGNOSTIC_RUNS WHERE RUN_ID=:run_id AND PRINCIPAL_ID=:actor",
                     {'run_id':run_id,'actor':actor})
    if not row:
        raise PermissionError('Diagnostic access denied')
    work._authorize(tx,actor,row['security_domain_id'],write=False)
    checks=tx.query("SELECT CHECK_CODE,STATUS,OBSERVED,DETAIL_CODE FROM CX_DIAGNOSTIC_CHECKS WHERE RUN_ID=:run_id ORDER BY ITEM_NO",{'run_id':run_id})
    validated=[DiagnosticCheck(check_code=item['check_code'],status=item['status'],observed=item['observed']=='Y',detail_code=item['detail_code']) for item in checks]
    if len(validated)!=int(row['check_count']) or diagnostic_status([item.status for item in validated])!=row['status']:
        raise ContinuityError('INTEGRITY_ERROR','Diagnostic observation records are inconsistent')
    return dict(row,checks=[item.model_dump(mode='json') for item in validated])


def run_diagnostics(actor,value):
    request=value if isinstance(value,NewDiagnosticRun) else NewDiagnosticRun.model_validate(value)
    def perform(tx):
        work._authorize(tx,actor,request.security_domain_id,write=False)
        prior=tx.query_one("SELECT RUN_ID,REQUEST_DIGEST FROM CX_DIAGNOSTIC_RUNS WHERE PRINCIPAL_ID=:actor AND IDEMPOTENCY_KEY=:key",
                           {'actor':actor,'key':request.idempotency_key})
        if prior:
            require_idempotent_request(prior['request_digest'],request_digest(actor,'DIAGNOSTIC_RUN',request))
            return dict(_read(tx,actor,prior['run_id']),replayed=True)
        checks=[]
        for code in request.checks:
            tx.execute('SAVEPOINT continuity_diagnostic_check',{})
            try:
                checks.append(_check(tx,actor,request,code))
            except PermissionError:
                tx.execute('ROLLBACK TO SAVEPOINT continuity_diagnostic_check',{})
                checks.append(_result(code,'FAIL','ACCESS_DENIED'))
            except ContinuityError as exc:
                tx.execute('ROLLBACK TO SAVEPOINT continuity_diagnostic_check',{})
                checks.append(_result(code,'UNAVAILABLE' if exc.code.endswith('_UNAVAILABLE') else 'FAIL',exc.code))
            except Exception:
                tx.execute('ROLLBACK TO SAVEPOINT continuity_diagnostic_check',{})
                checks.append(_result(code,'UNAVAILABLE','CHECK_SERVICE_UNAVAILABLE'))
        run_id=work._id('DR')
        status=diagnostic_status([item.status for item in checks])
        tx.execute("INSERT INTO CX_DIAGNOSTIC_RUNS(RUN_ID,REQUEST_ID,PRINCIPAL_ID,SECURITY_DOMAIN_ID,STATUS,CHECK_COUNT,PURPOSE,IDEMPOTENCY_KEY,REQUEST_DIGEST) "
                   "VALUES(:run_id,:request_id,:actor,:domain,:status,:check_count,:purpose,:key,:digest)",
                   {'run_id':run_id,'request_id':request.request_id,'actor':actor,'domain':request.security_domain_id,'status':status,
                    'check_count':len(checks),'purpose':request.purpose,'key':request.idempotency_key,'digest':request_digest(actor,'DIAGNOSTIC_RUN',request)})
        for index,item in enumerate(checks,1):
            tx.execute("INSERT INTO CX_DIAGNOSTIC_CHECKS(RUN_ID,ITEM_NO,CHECK_CODE,STATUS,OBSERVED,DETAIL_CODE) VALUES(:run_id,:item_no,:code,:status,:observed,:detail)",
                       {'run_id':run_id,'item_no':index,'code':item.check_code,'status':item.status,'observed':'Y' if item.observed else 'N','detail':item.detail_code})
        identity_api._audit_tx(tx,actor,'DIAGNOSTIC_RUN','DIAGNOSTIC_RUN',run_id,'ALLOW',request.purpose)
        return dict(_read(tx,actor,run_id),replayed=False)
    return connection.execute_transaction_callback(perform)


def read_run(actor,run_id):
    return connection.execute_transaction_callback(lambda tx:_read(tx,actor,run_id))
