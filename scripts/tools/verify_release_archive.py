"""Independently verify downloaded release bytes using a locally pinned key."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.release_archive_verification import verify


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--public-key-file',type=Path,required=True,help='Locally pinned URL-safe Base64 Ed25519 public key')
    parser.add_argument('--expected-digest',required=True)
    args=parser.parse_args()
    try:
        result=verify(args.input,args.public_key_file.read_text().strip(),args.expected_digest)
    except Exception:
        print(json.dumps({'verified':False,'error':'RELEASE_VERIFICATION_FAILED'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
