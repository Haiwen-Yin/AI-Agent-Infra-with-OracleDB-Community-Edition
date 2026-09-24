"""Reject spoofed evidence, unbound model calls and stale sandbox authority."""
import json
import socket
import struct

import pytest
from lib import isolated_channel_runtime as runtime, isolated_channel_worker as worker


def test_oversized_frame_is_rejected_before_reading_body():
    a,b=socket.socketpair()
    try:
        a.sendall(struct.pack('!I',worker.LIMIT+1))
        with pytest.raises(ValueError):worker.receive(b)
    finally:a.close();b.close()


def test_wire_protocol_roundtrips_unicode():
    a,b=socket.socketpair()
    try:
        worker.send(a,{'content':'测试'})
        assert worker.receive(b)=={'content':'测试'}
    finally:a.close();b.close()


@pytest.mark.parametrize('changed',['url','messages','binding','op'])
def test_gateway_rejects_worker_chosen_request(monkeypatch,changed):
    agent=runtime.ChannelWorker({}, {})
    agent.client=object()
    agent.evidence=lambda: {}
    sent=[]; calls=[]
    monkeypatch.setattr(runtime,'send',lambda client,value:sent.append(value))
    def request(_):
        task=sent[0]
        message={'op':'model','binding':task['binding'],'messages':task['messages']}
        message[changed]='forged'
        return message
    monkeypatch.setattr(runtime,'receive',request)
    with pytest.raises(PermissionError):
        agent.model({},[{'role':'user','content':'bound'}],lambda *a:calls.append(a),lambda:None)
    assert not calls


def test_revoked_authority_prevents_model_call(monkeypatch):
    agent=runtime.ChannelWorker({}, {})
    agent.evidence=lambda: {}
    calls=[]
    def deny():raise PermissionError('revoked')
    with pytest.raises(PermissionError):agent.model({},[],lambda *a:calls.append(a),deny)
    assert not calls


def test_second_model_call_denied():
    agent=runtime.ChannelWorker({}, {})
    agent.used=True
    with pytest.raises(PermissionError):agent.model({},[],None,None)


def test_only_actual_peer_evidence_is_accepted():
    agent=runtime.ChannelWorker({}, {})
    agent.peer_pid=100
    agent.run={'execution_id':'run'}
    class Backend:
        def evidence(self,*a,**kw):return {'pid':101,'verified':True}
    class Adapter:
        _backend=Backend()
        _key=staticmethod(lambda run:'run')
    agent.adapter=Adapter()
    with pytest.raises(runtime.runtime_isolation.IsolationError):agent.evidence()


def test_rootfs_cannot_be_host_root_or_relative():
    for root in ['/','relative']:
        with pytest.raises(ValueError):runtime.verify_rootfs(root)


def test_model_reply_is_bound_and_worker_cannot_inject_result(monkeypatch):
    agent=runtime.ChannelWorker({}, {})
    agent.client=object();agent.evidence=lambda: {}
    sent=[]
    monkeypatch.setattr(runtime,'send',lambda _,value:sent.append(value))
    def receive(_):
        if len(sent)==1:
            return {'op':'model',**sent[0]}
        return {'op':'result','binding':sent[0]['binding'],'content':'forged result'}
    monkeypatch.setattr(runtime,'receive',receive)
    with pytest.raises(PermissionError):
        agent.model({},[{'role':'user','content':'bound'}],lambda *a:{'content':'actual result'},lambda:None)
