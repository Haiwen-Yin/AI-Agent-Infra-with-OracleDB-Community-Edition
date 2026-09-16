"""Continuity CLI using the same typed, authenticated Gateway as MCP."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from . import continuity_client as client


def main(argv=None, *, transport=None):
    parser=argparse.ArgumentParser(description='Chuanxu continuity operations and server diagnostics')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('setup','doctor','capabilities','verify-context'):
        command=commands.add_parser(name)
        command.add_argument('--domain',required=True)
        if name=='verify-context':
            command.add_argument('--assembly-id')
            command.add_argument('--sources-file',type=Path)
            command.add_argument('--purpose',required=True)
    command=commands.add_parser('call',help='Submit a typed operation envelope from JSON file or stdin')
    command.add_argument('--request-file',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='call':
            raw=args.request_file.read_text() if args.request_file else sys.stdin.read()
            value=json.loads(raw)
        elif args.command=='capabilities':
            value={'operation':'capabilities','request':{'security_domain_id':args.domain}}
        else:
            checks=['PRINCIPAL','DOMAIN','DATABASE','INSTANCE']
            request={'request_id':uuid.uuid4().hex,'idempotency_key':uuid.uuid4().hex,
                     'security_domain_id':args.domain,'instance_id':os.environ.get('CX_AGENT_INSTANCE_ID') or None,
                     'purpose':'Continuity '+args.command,'checks':checks}
            if args.command=='verify-context':
                if not args.assembly_id and not args.sources_file:
                    raise client.ContinuityClientError('CONTEXT_REFERENCE_REQUIRED')
                request.update(purpose=args.purpose,assembly_id=args.assembly_id)
                if args.sources_file:
                    request['sources']=json.loads(args.sources_file.read_text())
                    checks.append('SOURCE_ACCESS')
                if args.assembly_id:
                    checks.append('CONTEXT_INPUT')
            if args.command=='doctor':
                # A reached CLI route does not certify all other entrypoints.
                checks.append('ENTRYPOINT_PARITY')
            value={'operation':'diagnostics_run','request':request}
        actor=os.environ.get('AI_AGENT_ID') or os.environ.get('MCP_AGENT_ID','')
        result=client.call(actor,value,transport=transport)
        print(json.dumps(result,ensure_ascii=False,default=str))
        if value['operation']=='diagnostics_run':
            return 0 if result.get('status')=='PASS' else 1
        return 0
    except client.ContinuityClientError as exc:
        print(json.dumps({'error':exc.code}))
        return 1
    except (OSError,ValueError,TypeError):
        # Do not expose file paths, input text or environment credentials.
        print(json.dumps({'error':'INVALID_REQUEST'}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
