"""Pinned LangGraph workflow inside the credential-free, networkless rootfs."""
import hashlib
import importlib.metadata
import json
import os
import socket
import struct
from typing import TypedDict

LIMIT = 4 * 1024 * 1024
FRAMEWORK_VERSION = '1.2.12'


def receive(sock):
    def exact(size):
        value = bytearray()
        while len(value) < size:
            part = sock.recv(size - len(value))
            if not part:
                raise RuntimeError('broker disconnected')
            value.extend(part)
        return bytes(value)
    size = struct.unpack('!I', exact(4))[0]
    if size > LIMIT:
        raise ValueError('message too large')
    return json.loads(exact(size))


def send(sock, value):
    payload = json.dumps(value, ensure_ascii=False).encode()
    if len(payload) > LIMIT:
        raise ValueError('message too large')
    sock.sendall(struct.pack('!I', len(payload)) + payload)


class State(TypedDict):
    messages: list
    binding: str
    content: str


def run_graph(client, task):
    if importlib.metadata.version('langgraph') != FRAMEWORK_VERSION:
        raise ValueError('framework version mismatch')
    from langgraph.graph import StateGraph, START, END
    steps = []
    def prepare(state):
        messages = state['messages']
        if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
            raise ValueError('invalid messages')
        for message in messages:
            if not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] not in {'system', 'user', 'assistant'} or not isinstance(message['content'], str):
                raise ValueError('invalid framework message')
        expected = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if state['binding'] != expected:
            raise ValueError('input binding mismatch')
        steps.append('prepare')
        return {}
    def model(state):
        steps.append('model')
        send(client, {'op': 'model', 'binding': state['binding'], 'messages': state['messages']})
        result = receive(client)
        if set(result) != {'content'} or not isinstance(result['content'], str) or not result['content'].strip():
            raise ValueError('invalid model result')
        return {'content': result['content'].strip()}
    def finalize(state):
        steps.append('finalize')
        return {'content': state['content']}
    graph = StateGraph(State)
    for name, function in [('prepare', prepare), ('model', model), ('finalize', finalize)]:
        graph.add_node(name, function)
    graph.add_edge(START, 'prepare')
    graph.add_edge('prepare', 'model')
    graph.add_edge('model', 'finalize')
    graph.add_edge('finalize', END)
    result = graph.compile().invoke(task, config={'recursion_limit': 8})
    return {'op': 'result', 'binding': result['binding'], 'content': result['content'],
            'framework': 'langgraph', 'framework_version': FRAMEWORK_VERSION, 'steps': steps}


def main():
    # No tracing client, database connection, remote tool or customer code is
    # constructed. The host broker is the sole model transport.
    os.environ['LANGSMITH_TRACING'] = 'false'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(180)
        client.connect('/workspace/broker.sock')
        send(client, {'op': 'ready', 'pid': os.getpid(), 'framework': 'langgraph',
                      'framework_version': importlib.metadata.version('langgraph')})
        send(client, run_graph(client, receive(client)))
        if receive(client).get('op') != 'close':
            raise ValueError('invalid close')


if __name__ == '__main__':
    main()
