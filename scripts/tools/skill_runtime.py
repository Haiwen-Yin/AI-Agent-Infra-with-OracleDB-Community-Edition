"""Explicit cooperative Agent Skill synchronization and turn wrapper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote,urlsplit
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.skill_runtime_installation import SkillRuntime,SkillRuntimeError


def sync(runtime,*,gateway,actor,instance,token,upgrade_id,public_key,database,edition):
    parsed=urlsplit(gateway)
    if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or not all((actor,instance,token)):
        raise SkillRuntimeError('GATEWAY_CONFIGURATION_REQUIRED')
    headers={'Authorization':'Bearer '+token,'X-Agent-ID':actor,'X-Agent-Instance':instance}
    with httpx.Client(base_url=gateway.rstrip('/')+'/',headers=headers,timeout=120,trust_env=False,follow_redirects=False) as client:
        def pending():
            response=client.get('upgrades/skill-pending')
            if response.status_code!=200: raise SkillRuntimeError('CURRENT_DISTRIBUTION_DENIED')
            rows=[item for item in response.json()['items'] if item['upgrade_id']==upgrade_id]
            if len(rows)>1: raise SkillRuntimeError('ASSIGNED_UPDATE_REQUIRED')
            return rows[0] if rows else None
        selected=pending()
        current=None
        try:
            with runtime.read_turn() as turn: current=turn['receipt']
        except FileNotFoundError:
            pass
        if selected is None:
            # Recover an uncertain final ACK only for the currently verified
            # local bytes. Download rechecks the explicitly requested plan's
            # recipient, version and present server trust before any ACK.
            if current is None: raise SkillRuntimeError('ASSIGNED_UPDATE_REQUIRED')
            selected=dict(package_digest=current['received_digest'],skill_version=current['package_version'])
        digest=selected['package_digest'];version=selected['skill_version']
        path='upgrades/'+quote(upgrade_id,safe='')+'/skill-archive'
        def download(destination=None):
            hasher=hashlib.sha256()
            size=0
            with client.stream('GET',path,params={'skill_version':version}) as response:
                if response.status_code!=200: raise SkillRuntimeError('CURRENT_DISTRIBUTION_DENIED')
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>4*1024**3: raise SkillRuntimeError('ARCHIVE_TOO_LARGE')
                    hasher.update(chunk)
                    if destination: destination.write(chunk)
            if hasher.hexdigest()!=digest: raise SkillRuntimeError('TRANSPORT_DIGEST_CHANGED')
        with tempfile.TemporaryFile() as stream:
            download(stream);stream.seek(0)
            with tempfile.NamedTemporaryFile(prefix='download-',dir=runtime.root/'staging') as copied:
                import shutil
                shutil.copyfileobj(stream,copied);copied.flush()
                receipt=runtime.receive(copied.name,public_key,digest)
        if (receipt['package_version']!=version or receipt['database']!=database or receipt['edition'].lower()!=edition.lower()):
            raise SkillRuntimeError('PACKAGE_TARGET_MISMATCH')
        # Receipt acknowledgement keeps the old version until an actual managed
        # safe point. A retry after uncertain ACK is safe and uses exact bytes.
        body=dict(upgrade_id=upgrade_id,skill_version=version,verified=True,safe_point=False,received_digest=digest)
        if current is None or current['received_digest']!=digest:
            response=client.post('upgrades/skill-ack',json=body)
            if response.status_code!=200: raise SkillRuntimeError('RECEIPT_ACKNOWLEDGEMENT_PENDING')
        def authorize(receipt):
            download()
            return True
        result=runtime.activate(digest,authorize=authorize)
        response=client.post('upgrades/skill-ack',json={**body,'safe_point':True})
        if response.status_code!=200:
            raise SkillRuntimeError('LOCAL_ACTIVE_SERVER_ACK_PENDING')
        result['server_acknowledgement']=response.json()['activation_state']
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='Dedicated private runtime directory')
    parser.add_argument('--public-key-file',type=Path,required=True,help='Operator-pinned Ed25519 public key')
    commands=parser.add_subparsers(dest='operation',required=True)
    commands.add_parser('status')
    command=commands.add_parser('sync')
    command.add_argument('--upgrade-id',required=True)
    command.add_argument('--database',choices=['oracle','pg','yashandb'],required=True)
    command.add_argument('--edition',choices=['community','enterprise'],required=True)
    command=commands.add_parser('run')
    command.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    try:
        runtime=SkillRuntime(args.root,args.public_key_file.read_text().strip())
        if args.operation=='sync':
            result=sync(runtime,gateway=os.environ.get('CX_AGENT_GATEWAY_URL',''),actor=os.environ.get('AI_AGENT_ID',''),
                instance=os.environ.get('CX_AGENT_INSTANCE_ID',''),token=os.environ.get('CX_AGENT_ACCESS_TOKEN',''),
                upgrade_id=args.upgrade_id,public_key=args.public_key_file.read_text().strip(),database=args.database,edition=args.edition)
        else:
            with runtime.read_turn() as turn:
                if args.operation=='run':
                    command=args.command[1:] if args.command[:1]==['--'] else args.command
                    if not command: raise SkillRuntimeError('RUNTIME_COMMAND_REQUIRED')
                    environment=dict(os.environ,CX_ACTIVE_SKILL_PATH=str(turn['skill_path']),CX_ACTIVE_SKILL_DIGEST=turn['receipt']['received_digest'])
                    # The child retains the flock if this wrapper exits
                    # unexpectedly; switching must still wait for that turn.
                    return subprocess.run(command,env=environment,check=False,pass_fds=(turn['lock_fd'],)).returncode
                result={key:turn['receipt'][key] for key in ('received_digest','package_version','database','edition')}
                result['observation']='LOCAL_COOPERATIVE_RUNTIME'
        print(json.dumps(result))
        return 0
    except SkillRuntimeError as exc:
        print(json.dumps({'error':str(exc)}));return 1
    except Exception:
        print(json.dumps({'error':'SKILL_RUNTIME_OPERATION_FAILED'}));return 1


if __name__=='__main__':
    raise SystemExit(main())
