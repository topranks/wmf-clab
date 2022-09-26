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
args = parser.parse_args()

def main():
    """ Reads a local file 'crpd_lvs_config.json', which should be a crpd-compatible 
        JunOS configuration file in JSON format.  Pushes that config to any containerlab 
        devices defined in local file 'wmf-lab.yaml' with name starting 'lvs' """

    with open('crpd_lvs_config.json', 'r') as json_config:
        lvs_config = json.loads(json_config.read())

    with open('wmf-lab.yaml', 'r') as wmf_file:
        wmf_lab = yaml.safe_load(wmf_file)

    for node_name in wmf_lab['topology']['nodes'].keys():
        if node_name.startswith('lvs'):
            clab_name = f"clab-wmf-lab-{node_name}"

            junos_dev = get_junos_dev(clab_name)

            junos_dev.config.load(json.dumps(lvs_config), format="json", overwrite=True)
            junos_dev.config.commit()
            print(f"Pushed LVS config for {node_name}.")

            junos_dev.close()

    print()


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
