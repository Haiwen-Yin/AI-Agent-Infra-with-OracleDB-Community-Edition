"""Actual fixed LangGraph worker; uses the existing verified Linux boundary."""
from .isolated_channel_runtime import ChannelWorker

FRAMEWORK_VERSION = '1.2.12'


class FrameworkWorker(ChannelWorker):
    worker_name = 'isolated_framework_worker.py'
    python_executable = '/usr/bin/python3.14'
    memory_bytes = 512 * 1024 * 1024
    pids = 64

    def _ready(self, message):
        return (set(message) == {'op', 'pid', 'framework', 'framework_version'}
                and message['op'] == 'ready' and message['framework'] == 'langgraph'
                and message['framework_version'] == FRAMEWORK_VERSION)

    def _reply(self, reply, binding, content):
        expected = {'op': 'result', 'binding': binding, 'content': content.strip(),
                    'framework': 'langgraph', 'framework_version': FRAMEWORK_VERSION,
                    'steps': ['prepare', 'model', 'finalize']}
        if reply != expected:
            raise PermissionError('framework output or execution binding mismatch')
        self.observation = {key: reply[key] for key in ('framework', 'framework_version', 'steps')}
        return reply['content']
