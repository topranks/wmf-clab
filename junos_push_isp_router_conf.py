#!/usr/bin/python3

from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import ConnectError

from getpass import getpass
import argparse
import os
import sys
import re

from pathlib import Path
import json
import yaml

import warnings
warnings.filterwarnings(action='ignore',module='.*paramiko.*')

parser = argparse.ArgumentParser()
parser.add_argument('-s', '--sshconfig', help='SSH config file', default='~/.ssh/config')
parser.add_argument('-c', '--conffile', help='Path to JSON-formatted JunOS config gile', default='output/isp_route_conf.json')
args = parser.parse_args()

def main():
    """ Pushes generated config to dummy isp_router node once it is spun up """
    # Get existing JunOS config
    junos_dev = get_junos_dev('clab-wmf-lab-isp_router')
    config = junos_dev.rpc.get_config(options={'format':'json', 'database' : 'committed'})
    del config['configuration']['@']

    # Load generated JunOS config
    with open(args.conffile, 'r') as json_file:
        add_config = json.load(json_file)

    config['configuration'].update(add_config)

    # Push modified config back to device if things have changed.
    junos_dev.config.load(json.dumps(config), format="json", overwrite=True)
    junos_dev.config.commit()
    print(f"Pushed config to dummy isp_router node.")

    junos_dev.close()
    '''
    from pprintpp import pprint as pp
    pp(config)

    print()
    '''


def get_junos_dev(dev_name):
    # Initiates NETCONF session to router
    try:
        device = Device(dev_name, username=os.getlogin(), ssh_config=args.sshconfig, port=22)
        device.open()
    except ConnectError as err:
        print(f"Cannot connect to device: {err}")
        sys.exit(1)

    # Get config object
    device.bind(config=Config)

    return device


if __name__ == '__main__':
    main()
