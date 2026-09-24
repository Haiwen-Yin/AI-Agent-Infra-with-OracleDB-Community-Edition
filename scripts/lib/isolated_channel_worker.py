"""One-turn Agent worker. Runs inside a networkless, credential-free sandbox."""
import json
import os
import socket
import struct

LIMIT = 4 * 1024 * 1024


def receive(sock):
    def exact(n):
        data = bytearray()
        while len(data) < n:
            part = sock.recv(n - len(data))
            if not part:
                raise RuntimeError('broker disconnected')
            data.extend(part)
        return bytes(data)
    size = struct.unpack('!I', exact(4))[0]
    if size > LIMIT:
        raise ValueError('message too large')
    return json.loads(exact(size))


def send(sock, value):
    payload = json.dumps(value, ensure_ascii=False).encode()
    if len(payload) > LIMIT:
        raise ValueError('message too large')
    sock.sendall(struct.pack('!I', len(payload)) + payload)


def main():
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(180)
        client.connect('/workspace/broker.sock')
        send(client, {'op': 'ready', 'pid': os.getpid()})
        task = receive(client)
        messages = task['messages']
        if not isinstance(messages, list) or not messages or len(messages) > 100:
            raise ValueError('invalid messages')
        for message in messages:
            if message.get('role') not in {'system', 'user', 'assistant'} or not isinstance(message.get('content'), str):
                raise ValueError('invalid message')
        # The broker accepts this exact, bound call once. It never accepts a
        # URL, model, credential or Tool choice from this process.
        send(client, {'op': 'model', 'binding': task['binding'], 'messages': messages})
        result = receive(client)
        content = str(result['content']).strip()
        if not content:
            raise ValueError('empty model result')
        send(client, {'op': 'result', 'binding': task['binding'], 'content': content})
        # Remain alive until the host rechecks the actual worker's evidence.
        if receive(client).get('op') != 'close':
            raise ValueError('invalid close')


if __name__ == '__main__':
    main()
