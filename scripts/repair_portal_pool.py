"""Repair explicitly selected idle Portal identities using an authorized administrator.

Run from an installed package with its Python and CX_CONFIG_PATH. No broad pool
release, permission override, schema migration or external Agent adoption occurs.
"""
import argparse
import json
from lib import portal_pool_maintenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor', required=True, help='Authorized administrator Principal ID')
    parser.add_argument('--agent', action='append', required=True, help='Exact idle local Portal Agent ID; repeat as needed')
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    print(json.dumps(portal_pool_maintenance.adopt_idle_agents(args.actor, args.agent, args.reason)))


if __name__ == '__main__':
    main()
