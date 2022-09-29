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
    """ Removes BGP groups in list 'disable_groups' from selected clab devices, and pushes saved BGP and 
        OSPF config to them if it is present. """

    disable_groups = ['Anycast4', 'Anycast6', 'IX4', 'IX6', 'Private-Peer4', 'Private-Peer6', 'Kubernetes4', 'Kubernetes6', 'Kubestage4', 'Kubestage6', 'Kubemlserve4', 'Kubemlserve6', 'Kubedse4', 'Kubedse6', 'Netflow', 'Cloudflare4', 'Switch4', 'Switch6', 'Kubemlstaging4', 'Kubemlstaging6']

    # Only operate on devices which name starts with one of these
    device_prefixes = ('cr')

    with open('output/wmf-lab.yaml', 'r') as wmf_file:
        wmf_lab = yaml.safe_load(wmf_file)

    for node_name in wmf_lab['topology']['nodes'].keys():
        if node_name.startswith(device_prefixes):
            clab_name = f"clab-wmf-lab-{node_name}"
            junos_dev = get_junos_dev(clab_name)

            config = junos_dev.rpc.get_config(options={'format':'json', 'database' : 'committed'})
            del config['configuration']['@']
            changed = False

            # Iterate over BGP groups on device, and set any that we want to disabled in the config.
            existing_bgp_groups = []
            try:
                for bgp_group in config['configuration']['protocols']['bgp']['group']:
                    existing_bgp_groups.append(bgp_group['name'])
                    if bgp_group['name'] in disable_groups and '@' not in bgp_group:
                        bgp_group['@'] = {"inactive": True}
                        changed = True
            except KeyError:
                # No existing groups defined in running conf, pass
                pass

            # If present, load saved config from junos_config dir for this device
            try:
                with open(f"junos_data/config/{node_name}.json", 'r') as json_file:
                    prod_config = json.load(json_file)
                # Add any BGP groups that do no exist on device:
                for bgp_group in prod_config['configuration']['protocols']['bgp']['group']:
                    if bgp_group['name'] not in existing_bgp_groups and bgp_group['name'] not in disable_groups:
                        config['configuration']['protocols']['bgp']['group'].append(bgp_group)
                        changed = True
            except FileNotFoundError:
                pass

            # If present, load OSPF metrics from live device state
            try:
                with open(f"junos_data/ospf_ints/{node_name}.json", 'r') as json_file:
                    live_metrics = json.load(json_file)
                    new_metrics = {}
                    for int_name in live_metrics.keys():
                        if int_name == "lo0.0":
                            crpd_int_name = "lo.0"
                        elif int_name.endswith(".0"):
                            crpd_int_name = int_name.split('.')[0].replace('/', '_').replace(':', '_')
                        else:
                            crpd_int_name = int_name.replace('/', '_').replace(':', '_')
                        

                        if live_metrics[int_name] == 0:
                            new_metrics[crpd_int_name] = 1
                        else:
                            new_metrics[crpd_int_name] = live_metrics[int_name]

                    for ospf_int in config['configuration']['protocols']['ospf']['area'][0]['interface']:
                        if ospf_int['name'] in new_metrics.keys():
                            try:
                                if ospf_int['metric'] < 100:
                                    ospf_int['metric'] = new_metrics[ospf_int['name']]
                                    changed = True
                            except KeyError:
                                ospf_int['metric'] = new_metrics[ospf_int['name']]
                                changed = True
            except FileNotFoundError:
                pass

            # Push modified config back to device if things have changed.
            if changed:
                junos_dev.config.load(json.dumps(config), format="json", overwrite=True)
                junos_dev.config.commit()
                print(f"Pushed revised config for {node_name}.")

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
