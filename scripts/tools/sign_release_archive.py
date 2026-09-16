"""Sign a verified release file manifest with an operator-owned Ed25519 key.

Creates a separate archive; never overwrites the input or an existing output.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lib.admin_management import _verify_package_manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--private-key',type=Path,required=True,help='Operator-owned unencrypted Ed25519 PEM; never included in the archive')
    parser.add_argument('--key-id',required=True)
    args=parser.parse_args()
    if args.output.exists() or args.input.resolve()==args.output.resolve():
        raise ValueError('A new output path is required')
    key=serialization.load_pem_private_key(args.private_key.read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):
        raise ValueError('An Ed25519 private key is required')
    with zipfile.ZipFile(args.input) as source:
        _,root=_verify_package_manifest(source)
        if root+'release-signature.json' in source.namelist():
            raise ValueError('Input is already signed; use the original unsigned package')
        digest=hashlib.sha256(source.read(root+'package-files.sha256')).hexdigest()
        envelope={'schema':'chuanxu-release-signature/v1','algorithm':'ED25519','signed_object':'package-files.sha256',
                  'digest':digest,'key_id':args.key_id,
                  'signature':base64.urlsafe_b64encode(key.sign(b'chuanxu-release-manifest/v1\n'+digest.encode('ascii'))).decode('ascii')}
        with zipfile.ZipFile(args.output,'x',compression=zipfile.ZIP_DEFLATED) as destination:
            for item in source.infolist():
                destination.writestr(item,source.read(item))
            destination.writestr(root+'release-signature.json',json.dumps(envelope,sort_keys=True).encode('ascii'))
    print('Signed archive created: '+str(args.output))


if __name__=='__main__':
    main()
