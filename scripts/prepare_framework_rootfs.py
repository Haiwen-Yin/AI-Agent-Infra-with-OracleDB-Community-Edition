"""Prepare a new immutable Python 3.14 / pinned LangGraph rootfs offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def prepare(root, worker, wheelhouse, python):
    if os.geteuid() != 0:
        raise PermissionError('root is required to prepare the isolation image')
    root = Path(root)
    if root.is_symlink() or not root.is_absolute() or not root.resolve().is_relative_to('/var/lib/chuanxu') or root.exists():
        raise ValueError('use a new versioned rootfs under /var/lib/chuanxu')
    if Path(worker).name != 'isolated_framework_worker.py' or not Path(worker).is_file():
        raise ValueError('the packaged framework worker is required')
    wheelhouse = Path(wheelhouse).resolve()
    lock = json.loads((wheelhouse / 'framework-lock.json').read_text())
    if (lock.get('schema'), lock.get('framework'), lock.get('version'), lock.get('python')) != ('chuanxu-framework-lock/1', 'langgraph', '1.2.12', '3.14'):
        raise ValueError('unsupported framework lock')
    expected = {item['wheel'] for item in lock['packages']}
    if expected != {path.name for path in wheelhouse.glob('*.whl')}:
        raise ValueError('framework wheel inventory differs')
    for package in lock['packages']:
        if Path(package['wheel']).name != package['wheel'] or hashlib.sha256((wheelhouse / package['wheel']).read_bytes()).hexdigest() != package['sha256']:
            raise ValueError('framework wheel digest differs')
    paths = json.loads(subprocess.check_output([python, '-I', '-c', 'import json,sys,sysconfig;print(json.dumps({"version":list(sys.version_info[:2]),"paths":sysconfig.get_paths()}))'], text=True))
    if paths['version'] != [3, 14]:
        raise ValueError('a supported Python 3.14 executable is required')
    root.mkdir(parents=True, mode=0o755)
    for directory in ('tmp', 'workspace', 'proc', 'dev', 'opt', 'etc'):
        (root / directory).mkdir(mode=0o755)
    for directory in {paths['paths']['stdlib'], paths['paths']['platstdlib']}:
        source = Path(directory)
        shutil.copytree(source, root / source.relative_to('/'), symlinks=False, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'ensurepip'))
    # ``-I`` uses the system site directory from the interpreter build.  Keep
    # the wheel closure there so the isolated worker receives no ambient host
    # site-packages and still imports the pinned framework.
    purelib = root / 'usr/lib64/python3.14/site-packages'
    subprocess.run([python, '-m', 'pip', 'install', '--no-index', '--no-compile', '--only-binary=:all:',
        '--require-hashes', '--find-links', str(wheelhouse), '--target', str(purelib),
        '-r', str(wheelhouse / 'requirements.lock')], check=True, env={**os.environ, 'PIP_DISABLE_PIP_VERSION_CHECK': '1'})
    binaries = {str(Path(python).resolve())}
    for source in [Path(python).resolve(), *root.rglob('*.so')]:
        result = subprocess.run(['ldd', str(source)], capture_output=True, text=True)
        if result.returncode and 'not a dynamic executable' not in result.stderr + result.stdout:
            raise ValueError('failed to resolve worker shared libraries')
        binaries.update(re.findall(r'(?:=>\s+)?(/[^\s()]+)', result.stdout))
    for filename in binaries:
        source = Path(filename)
        destination = root / source.relative_to('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.resolve(), destination)
    destination = root / 'usr/bin/python3.14'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(python).resolve(), destination)
    shutil.copy2(worker, root / 'opt/isolated_framework_worker.py')
    shutil.copy2(wheelhouse / 'framework-lock.json', root / 'opt/framework-lock.json')
    # Pip's bin links are unnecessary: only the pinned Python entrypoint runs.
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('rootfs must not contain symbolic links')
        os.chmod(path, 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        os.chown(path, 0, 0)
    manifest = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(root)) + '\n'
        for path in sorted(root.rglob('*')) if path.is_file())
    (root / '.cx-rootfs-manifest.sha256').write_text(manifest)
    os.chmod(root / '.cx-rootfs-manifest.sha256', 0o644)
    return {'rootfs': str(root), 'rootfs_digest': 'sha256:' + hashlib.sha256(manifest.encode()).hexdigest(),
            'framework': 'langgraph', 'version': '1.2.12', 'files': len(manifest.splitlines())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--python', default='/usr/bin/python3.14')
    parser.add_argument('--worker', type=Path, default=Path(__file__).parents[1] / 'lib/isolated_framework_worker.py')
    parser.add_argument('--wheelhouse', type=Path, default=Path(__file__).parents[1] / 'vendor/framework-langgraph')
    args = parser.parse_args()
    print(json.dumps(prepare(args.rootfs, args.worker, args.wheelhouse, args.python)))


if __name__ == '__main__':
    main()
