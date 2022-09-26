#!/usr/bin/python3

import pynetbox

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

parser = argparse.ArgumentParser()
parser.add_argument('-n', '--netbox', help='Netbox server IP / Hostname', type=str, default="netbox.wikimedia.org")
parser.add_argument('-k', '--key', help='Netbox API Token / Key', type=str, default='')
parser.add_argument('-s', '--sshconfig', help='SSH config file', default='~/.ssh/config.homer')
parser.add_argument('-d', '--outputdir', help='Directory for output YAML files', default='junos_data')
args = parser.parse_args()

def main():
    """ Polls netbox for devices with roles/statues in the vars defined below, then connects 
        to the live prod instances and pulls the BGP config and OSPF interface metrics from 
        them.  These are then saved to files in <output_dir> so they can be used in lab 
        environments, filling the gap of manual / automatic config we can't derive from 
        Netbox / Homer YAML files. """ 

    nb_url = "https://{}".format(args.netbox)
    if args.key:
        nb_key = args.key
    else:
        nb_key = getpass(prompt="Netbox API Key: ")
    nb = pynetbox.api(nb_url, nb_key)

    Path(f"{args.outputdir}/config").mkdir(exist_ok=True, parents=True)
    Path(f"{args.outputdir}/ospf_ints").mkdir(exist_ok=True, parents=True)

    device_roles = ['cr']
    device_statuses = ['active', 'staged']

    for role in device_roles:
        nb_devices = nb.dcim.devices.filter(role=role)
        for nb_device in nb_devices:
            if str(nb_device.status).lower() not in device_statuses:
                continue
            print(f"Connecting to {nb_device.name}... ", end="", flush=True)
            dev_pri_ip = nb.ipam.ip_addresses.get(nb_device.primary_ip.id)
            junos_dev = get_junos_dev(dev_pri_ip.dns_name)

            config_filter = "<protocols><bgp/></protocols>"
            config = junos_dev.rpc.get_config(options={'format':'json'}, filter_xml=config_filter)
            with open(f"{args.outputdir}/config/{nb_device.name}.json", "w") as config_file:
                config_file.write(json.dumps(config))

            ospf_metrics = {}
            ospf_ints = junos_dev.rpc.get_ospf_interface_information({'format':'json'}, detail=True)
            for ospf_int in ospf_ints['ospf-interface-information'][0]['ospf-interface']:
                metric = int(ospf_int['ospf-interface-topology'][0]['ospf-topology-metric'][0]['data'])
                ospf_metrics[ospf_int['interface-name'][0]['data']] = metric

            with open(f"{args.outputdir}/ospf_ints/{nb_device.name}.json", "w") as metric_file:
                metric_file.write(json.dumps(ospf_metrics))

            junos_dev.close()
            print("saved ok.")


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
