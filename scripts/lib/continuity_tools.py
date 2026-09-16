"""Authenticated dynamic Tool proposals with immutable execution provenance."""
import hashlib
import json
from decimal import Decimal
import math

from . import connection, identity_api, tool_registry
from . import continuity_work as work, continuity_bindings as bindings
from .continuity_contracts import ToolInvocation, request_digest
from .continuity_state import ContinuityConflict


def schema_statements(dialect):
    return ["CREATE TABLE CX_MCP_TOOL_REQUESTS (REQUEST_ID VARCHAR(128) PRIMARY KEY, "
        "JOB_ID VARCHAR(128) NOT NULL UNIQUE REFERENCES EXECUTION_JOBS(JOB_ID), TOOL_ID VARCHAR(128) NOT NULL, "
        "PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "INSTANCE_ID VARCHAR(128) NOT NULL REFERENCES CX_AGENT_INSTANCES(INSTANCE_ID), "
        "TOKEN_DIGEST VARCHAR(64) NOT NULL REFERENCES CX_AGENT_ACCESS_TOKENS(TOKEN_DIGEST), "
        "FENCING_TOKEN INTEGER NOT NULL CHECK(FENCING_TOKEN>0), CONTRACT_DIGEST VARCHAR(64) NOT NULL, "
        "PAYLOAD_DIGEST VARCHAR(64) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "UNIQUE(PRINCIPAL_ID,IDEMPOTENCY_KEY))"]


def _numbers(value):
    if isinstance(value,dict):
        return {key:_numbers(item) for key,item in value.items()}
    if isinstance(value,list):
        return [_numbers(item) for item in value]
    if isinstance(value,Decimal):
        if not value.is_finite():
            raise ValueError('Non-finite JSON number')
        return int(value) if value==value.to_integral_value() else float(value)
    if isinstance(value,float):
        if not math.isfinite(value):
            raise ValueError('Non-finite JSON number')
        return int(value) if value.is_integer() else value
    return value


def _json(value):
    # Oracle native JSON returns Decimal, including for integer-valued fields.
    # Canonical numeric values must survive the native JSON storage round-trip.
    return json.dumps(_numbers(value),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _contract(tool):
    schema=tool['input_schema']
    if hasattr(schema,'read'):
        schema=schema.read()
    if isinstance(schema,str):
        schema=json.loads(schema)
    return dict(tool_id=str(tool['tool_id']),input_schema=schema)


def _authorize(tx,actor,domain,context):
    if not context:
        raise PermissionError('An authenticated Agent transport is required')
    work._authorize(tx,actor,domain,write=False)
    for action in ('tools.read','actions.propose'):
        if identity_api.effective_access(actor,action,resource={'security_domain_id':domain}).get('decision')!='ALLOW':
            raise PermissionError('Tool proposal denied')
    valid=tx.query_one("SELECT t.TOKEN_DIGEST FROM CX_AGENT_ACCESS_TOKENS t "
        "JOIN CX_AGENT_INSTANCES i ON i.INSTANCE_ID=t.INSTANCE_ID "
        "WHERE t.TOKEN_DIGEST=:token AND t.AGENT_ID=:actor AND t.INSTANCE_ID=:instance "
        "AND t.FENCING_TOKEN=:fence AND i.FENCING_TOKEN=t.FENCING_TOKEN "
        "AND t.REVOKED_AT IS NULL AND t.EXPIRES_AT>CURRENT_TIMESTAMP "
        "AND i.AGENT_ID=:actor AND i.SECURITY_DOMAIN_ID=:domain AND i.STATUS='ACTIVE' "
        "AND i.LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
        {'token':context['token_digest'],'actor':actor,'instance':context['instance_id'],
         'fence':context['fencing_token'],'domain':domain})
    if not valid:
        raise PermissionError('Tool proposal authority expired or was revoked')


def propose(actor,tool_id,value):
    request=value if isinstance(value,ToolInvocation) else ToolInvocation.model_validate(value)
    context=bindings._transport.get()
    def perform(tx):
        _authorize(tx,actor,request.security_domain_id,context)
        tool=tx.query_one("SELECT TOOL_ID,INPUT_SCHEMA FROM TOOL_REGISTRY WHERE TOOL_ID=:tool "
                          "AND STATUS='ACTIVE' AND MCP_EXPOSED='Y' FOR UPDATE",{'tool':tool_id})
        if not tool:
            raise PermissionError('MCP tool is unavailable')
        digest=request_digest(actor,'MCP_TOOL:'+str(tool_id),request)
        previous=tx.query_one("SELECT REQUEST_DIGEST,JOB_ID,REQUEST_ID FROM CX_MCP_TOOL_REQUESTS "
                              "WHERE PRINCIPAL_ID=:actor AND IDEMPOTENCY_KEY=:key",
                              {'actor':actor,'key':request.idempotency_key})
        if previous:
            if previous['request_digest']!=digest:
                raise ContinuityConflict('IDEMPOTENCY_CONFLICT','Tool request key was already used with different input')
            return dict(success=True,status='QUEUED',job_id=previous['job_id'],request_id=previous['request_id'],replayed=True)
        contract=_contract(tool)
        payload=tool_registry.prepare_http_request(contract,request.arguments,request.timeout)
        job_id=work._id('MJ')
        request_id=work._id('MT')
        key='MCP:'+_digest({'actor':actor,'key':request.idempotency_key})
        tx.execute("INSERT INTO EXECUTION_JOBS(JOB_ID,JOB_TYPE,STATUS,AGENT_ID,PAYLOAD_JSON,IDEMPOTENCY_KEY,"
                   "MAX_ATTEMPTS,REQUIRES_APPROVAL,CANCEL_REQUESTED,CREATED_AT,UPDATED_AT) "
                   "VALUES(:job,'TOOL_HTTP','WAITING_APPROVAL',:actor,:payload,:key,1,'Y','N',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                   {'job':job_id,'actor':actor,'payload':_json(payload),'key':key})
        tx.execute("INSERT INTO CX_MCP_TOOL_REQUESTS(REQUEST_ID,JOB_ID,TOOL_ID,PRINCIPAL_ID,SECURITY_DOMAIN_ID,"
                   "INSTANCE_ID,TOKEN_DIGEST,FENCING_TOKEN,CONTRACT_DIGEST,PAYLOAD_DIGEST,REQUEST_DIGEST,IDEMPOTENCY_KEY) "
                   "VALUES(:request,:job,:tool,:actor,:domain,:instance,:token,:fence,:contract,:payload,:digest,:key)",
                   {'request':request_id,'job':job_id,'tool':str(tool_id),'actor':actor,'domain':request.security_domain_id,
                    'instance':context['instance_id'],'token':context['token_digest'],'fence':context['fencing_token'],
                    'contract':_digest(contract),'payload':_digest(payload),'digest':digest,'key':request.idempotency_key})
        tx.execute("INSERT INTO EXECUTION_AUDIT(AUDIT_ID,JOB_ID,ACTION_TYPE,ACTOR_ID,DETAIL_JSON,CREATED_AT) "
                   "VALUES(:audit_id,:job,'CREATED',:actor,:detail,CURRENT_TIMESTAMP)",
                   {'audit_id':work._id('MA'),'job':job_id,'actor':actor,'detail':_json({'status':'WAITING_APPROVAL','request_id':request_id})})
        identity_api._audit_tx(tx,actor,'MCP_TOOL_PROPOSE','TOOL',str(tool_id),'ALLOW',request.reason)
        return dict(success=True,status='QUEUED',job_id=job_id,request_id=request_id,replayed=False)
    return connection.execute_transaction_callback(perform)


def validate_execution(job, *, require_claim=True):
    """Recheck pending authority and contract immediately before HTTP execution."""
    def perform(tx):
        binding=tx.query_one("SELECT * FROM CX_MCP_TOOL_REQUESTS WHERE JOB_ID=:job",{'job':job['job_id']})
        if not binding:
            return
        if binding['principal_id']!=job['agent_id']:
            raise PermissionError('Tool execution identity changed')
        if require_claim:
            claimed=tx.query_one("SELECT JOB_ID FROM EXECUTION_JOBS WHERE JOB_ID=:job "
                "AND STATUS='RUNNING' AND CANCEL_REQUESTED='N' AND LEASE_TOKEN=:lease "
                "AND LEASE_UNTIL>CURRENT_TIMESTAMP",
                {'job':job['job_id'],'lease':job.get('lease_token')})
            if not claimed:
                raise PermissionError('Tool worker lease is no longer current')
        _authorize(tx,binding['principal_id'],binding['security_domain_id'],binding)
        tool=tx.query_one("SELECT TOOL_ID,INPUT_SCHEMA FROM TOOL_REGISTRY WHERE TOOL_ID=:tool "
                          "AND STATUS='ACTIVE' AND MCP_EXPOSED='Y'",{'tool':binding['tool_id']})
        if not tool or _digest(_contract(tool))!=binding['contract_digest']:
            raise PermissionError('Tool exposure or contract changed')
        if _digest(job['payload_json'])!=binding['payload_digest']:
            raise PermissionError('Tool execution payload changed')
    connection.execute_transaction_callback(perform)
