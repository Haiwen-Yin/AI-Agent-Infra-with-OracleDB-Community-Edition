"""Apply an exact, reviewed Knowledge plan through authenticated audited APIs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import identity_api, knowledge_maintenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password-file', type=Path, required=True)
    parser.add_argument('--grant-agent-read', action='store_true')
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    actor = identity_api.authenticate_local(args.username, args.password_file.read_text().strip())
    if not actor:
        raise PermissionError('Authentication failed')
    print(json.dumps(knowledge_maintenance.repair(actor['principal_id'], json.loads(args.plan.read_text()),
        grant_agent_read=args.grant_agent_read, reason=args.reason), ensure_ascii=False))


if __name__ == '__main__':
    main()
