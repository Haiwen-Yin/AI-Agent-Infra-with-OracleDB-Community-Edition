"""Independent downloaded-archive verification using an operator-pinned key."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .admin_management import _verify_package_manifest


def verify(path,public_key,expected_digest):
    if len(expected_digest)!=64 or any(c not in '0123456789abcdef' for c in expected_digest):
        raise ValueError('Invalid transport digest')
    with Path(path).open('rb') as stream:
        if not hmac.compare_digest(hashlib.file_digest(stream,'sha256').hexdigest(),expected_digest):
            raise ValueError('Transport digest mismatch')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            if sum(item.file_size for item in archive.infolist())>4*1024**3:
                raise ValueError('Expanded archive exceeds supported limit')
            manifest,root=_verify_package_manifest(archive)
            envelope=json.loads(archive.read(root+'release-signature.json').decode('ascii'))
            digest=hashlib.sha256(archive.read(root+'package-files.sha256')).hexdigest()
            if envelope.get('schema')!='chuanxu-release-signature/v1' or envelope.get('algorithm')!='ED25519' or envelope.get('signed_object')!='package-files.sha256' or envelope.get('digest')!=digest:
                raise ValueError('Signature envelope mismatch')
            key=base64.urlsafe_b64decode(public_key+'='*(-len(public_key)%4))
            encoded=envelope['signature']
            signature=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
            Ed25519PublicKey.from_public_bytes(key).verify(signature,b'chuanxu-release-manifest/v1\n'+digest.encode('ascii'))
            if root+'SKILL.md' not in archive.namelist():
                raise ValueError('Skill entrypoint is unavailable')
    return {'verified':True,'received_digest':expected_digest,'package_version':manifest['version'],
            'edition':manifest['edition'],'database':manifest['database']['key']}
