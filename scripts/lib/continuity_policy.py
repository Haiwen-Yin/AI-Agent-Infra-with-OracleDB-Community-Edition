"""Versioned, explicit handoff concurrency policy; serial remains the default."""
from . import connection,continuity_work as work
from .continuity_contracts import Contract,Revision,Reason,Identifier,WorkContent
from .continuity_state import ContinuityError,ContinuityConflict,require_version
from pydantic import Field,StrictInt
from typing import Annotated


class HandoffPolicyChange(Contract):
    expected_version: Revision
    max_active_recipients: Annotated[StrictInt,Field(ge=1,le=16)]
    reason: Reason
    idempotency_key: Identifier


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('Unsupported database adapter')
    return ["CREATE TABLE CX_WORK_HANDOFF_POLICIES (WORK_CONTRACT_ID VARCHAR(128) NOT NULL, "
            "REVISION_NO INTEGER NOT NULL, MAX_ACTIVE_RECIPIENTS INTEGER NOT NULL "
            "CHECK(MAX_ACTIVE_RECIPIENTS>=1 AND MAX_ACTIVE_RECIPIENTS<=16), "
            "PRIMARY KEY(WORK_CONTRACT_ID,REVISION_NO), FOREIGN KEY(WORK_CONTRACT_ID,REVISION_NO) "
            "REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))"]


def read(tx,work_id,revision):
    row=tx.query_one('SELECT MAX_ACTIVE_RECIPIENTS FROM CX_WORK_HANDOFF_POLICIES '
                     'WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision',
                     {'work_id':work_id,'revision':revision})
    if not row or not 1<=int(row['max_active_recipients'])<=16:
        raise ContinuityError('POLICY_UNAVAILABLE','The exact handoff policy is unavailable')
    limit=int(row['max_active_recipients'])
    return {'max_active_recipients':limit,'ownership_mode':'TRANSFER_ON_ACK' if limit==1 else 'COORDINATOR_RETAINS'}


def snapshot(tx,work_id,revision,limit=None):
    if limit is None:
        limit=1 if revision==1 else read(tx,work_id,revision-1)['max_active_recipients']
    tx.execute('INSERT INTO CX_WORK_HANDOFF_POLICIES(WORK_CONTRACT_ID,REVISION_NO,MAX_ACTIVE_RECIPIENTS) '
               'VALUES(:work_id,:revision,:limit_value)',{'work_id':work_id,'revision':revision,'limit_value':limit})


def change(actor,work_id,value):
    request=value if isinstance(value,HandoffPolicyChange) else HandoffPolicyChange.model_validate(value)
    def perform(tx):
        from . import continuity_handoff as handoff
        root=handoff._lock_work(tx,actor,work_id)
        prior=work._receipt(tx,actor,'WORK_HANDOFF_POLICY',request)
        if prior:
            if prior['work_contract_id']!=work_id:
                raise ContinuityConflict('IDEMPOTENCY_CONFLICT','The key belongs to another work contract')
            return prior
        if root['owner_principal_id']!=actor:
            raise PermissionError('Only the current owner can change handoff policy')
        require_version(int(root['version']),request.expected_version)
        if root['status'] in {'COMPLETED','CANCELLED','EXPIRED'}:
            raise ContinuityConflict('TERMINAL_WORK','Closed work policy cannot change')
        handoff._expire_active(tx,work_id)
        if tx.query_one('SELECT HANDOFF_ID FROM CX_HANDOFFS WHERE ACTIVE_WORK_ID=:work_id',{'work_id':work_id}):
            raise ContinuityConflict('ACTIVE_RECIPIENT','Finish or expire active handoffs before changing policy')
        current=work._read_work(tx,actor,work_id)
        revision=request.expected_version+1
        work._content(tx,work_id,revision,WorkContent.model_validate(current['content']),actor,request.reason,
                      max_active_recipients=request.max_active_recipients)
        tx.execute('UPDATE CX_WORK_CONTRACTS SET VERSION=:revision,UPDATED_AT=CURRENT_TIMESTAMP WHERE WORK_CONTRACT_ID=:work_id',
                   {'work_id':work_id,'revision':revision})
        return work._record(tx,actor,'WORK_HANDOFF_POLICY',request,work_id,revision)
    return connection.execute_transaction_callback(perform)
