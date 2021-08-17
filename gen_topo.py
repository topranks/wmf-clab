#!/usr/bin/python3

import argparse
import pynetbox
import ipaddress
import yaml
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import requests
import sys

parser = argparse.ArgumentParser(description='Stupid Netbox Thing')
parser.add_argument('--netbox', help='Netbox server IP / Hostname', type=str, default='netbox.wikimedia.org')
parser.add_argument('-k', '--key', help='Netbox API Token / Key', type=str)
parser.add_argument('--name', help='Name for clab project, file names based on this.', default='wmf-lab')
#parser.add_argument('-o', '--overwrite', help='Toggle to overwrite existing device conigs.', default=False, action='store_true')
parser.add_argument('-l', '--license', help='License file name for crpd if desired', type=str)
args = parser.parse_args()

devices = {}
links = {}

def main():
    nb_url = "https://{}".format(args.netbox)
    nb_key = get_nb_key()
    global nb
    nb = pynetbox.api(nb_url, token=nb_key)

    global homer_cfg_common
    homer_cfg_common = getWebYaml('https://raw.githubusercontent.com/wikimedia/operations-homer-public/master/config/common.yaml')

    get_info()
    write_files()


def get_nb_key():
    if args.key:
        return args.key
    else:
        from getpass import getpass
        return getpass(prompt="Netbox API Key: ")
        

def get_info():
    core_routers = nb.dcim.devices.filter(role="cr")
    for router in core_routers:
        print("Addding {}...".format(router.name))
        if router.status.value == "active" or router.status.value == "planned":
            router_ints = nb.dcim.interfaces.filter(device_id=router.id)
            for interface in router_ints:
                if interface.enabled and not interface.name.startswith("fxp"):
                    int_addrs = nb.ipam.ip_addresses.filter(interface_id=interface.id)
                    if int_addrs:
                        if interface.type.value == "virtual" and interface.name.startswith("lo"):
                            add_loopback(router, int_addrs)
                            continue

                        # Exclude VRRP VIPs / Special IPs - hence doing loopback int first above
                        int_addrs = [addr for addr in int_addrs if not addr.role]

                        if interface.connected_endpoint_type == "circuits.circuittermination":
                            add_cct_interfaces(router, interface, int_addrs)

                        elif interface.description.startswith("Subnet"):
                            add_sw_subint(router, interface, int_addrs, router_ints)

                        else:
                            add_generic_interfaces(router, interface, int_addrs)


def add_cct_interfaces(router, interface, int_addrs):
    circuit = nb.circuits.circuits.get(interface.connected_endpoint.circuit.id)
    if circuit.type.slug == "transport":
        add_transport_circuit(router, interface, int_addrs, circuit)
    # TODO - Add Transit, Peering.


def add_transport_circuit(router, interface, int_addrs, circuit):
    # Adds device interfaces and entry in links{} for a given transport circuit
    # Gets far-side details from circuit termination, and metric from cct
    descr = "{} Transport {}".format(circuit.provider.name, circuit.cid)
    metric = circuit.custom_fields['metric'] if circuit.custom_fields['metric'] > 0 else 10

    # Get far-side interface and far-side addresses:
    if circuit.termination_a.connected_endpoint.id == interface.id:
        interface_b = nb.dcim.interfaces.get(circuit.termination_z.connected_endpoint.id)
    else:
        interface_b = nb.dcim.interfaces.get(circuit.termination_a.connected_endpoint.id)
    interface_b_addrs = nb.ipam.ip_addresses.filter(interface_id=interface_b.id)

    # Add interfaces to routers either side and link itself
    add_device_interface(router.name, interface.name, int_addrs, "crpd", descr, metric)
    add_device_interface(interface_b.device.name, interface_b.name, interface_b_addrs, "crpd", descr, metric)
    add_ordered_link(router.name, interface, interface_b.device.name, interface_b, descr)


def add_generic_interfaces(router, interface, int_addrs):
    # Adds device interfaces and entry in links{} for a generic L3 p2p link
    # Gets far-side details using link IPs, sets metric based on descr when possible.
    far_side_int = get_addr_far_side(int_addrs)

    if far_side_int:
        far_side_addrs = nb.ipam.ip_addresses.filter(interface_id=far_side_int.id)
        metric = get_p2p_metric(interface, far_side_int)

        add_device_interface(router.name, interface.name, int_addrs, "crpd", interface.description, metric)
        add_device_interface(far_side_int.device.name, far_side_int.name, far_side_addrs, "crpd",
            far_side_int.description, metric)
        add_ordered_link(router.name, interface, far_side_int.device.name, far_side_int)
#    else:
#       PNIs, GREs to Cloudflare, External links without attached CCT basically.


def add_sw_subint(router, interface, int_addrs, router_ints):
    # Sub-interfaces which connect to a switch acting as gateway for hosts, i.e. ae1.1001.
    # We extract parent int and add that to router if needed, as well as creating a bridge
    # device to represent switch as required, and link to the router physical.

    # Lastly we record the sub-interface and IPs separately so we can add commands to 
    # the startup script to create matching sub-interfaces in the container netns from the parent.

    add_device(router.name, "crpd")

    parent_int = get_int_object(interface.name.split(".")[0], router_ints)
    unit = interface.name.split(".")[1]

    if parent_int:
        if parent_int.name not in devices[router.name]['phys_ints']:
            # Add new physical int to router, and new bridge dev if required.
            add_sw_physical(parent_int, router, interface, int_addrs, router_ints)

        # Record sub-interface for device, along with IP addresses for it
        clab_parent_dev = devices[router.name]['phys_ints'][parent_int.name]['clab_dev']
        devices[router.name]['subints'][interface.name] = {
            "clab_dev": clab_parent_dev,
            "vlan_id": unit,
            "addrs": int_addrs,
            "metric": get_stub_metric(router.name, interface.name)
        }

    else:
        print("ERROR: No parent int found for {}".format(interface.name))


def get_int_object(int_name, interfaces):
    # Returns element from interfaces with name equivalent to int_name
    for interface in interfaces:
        if interface.name == int_name:
            return interface


def add_sw_physical(phys_int, router, interface, int_addrs, router_ints):
    # Find what it's connected to and add bridge device if needed
    far_side_int = get_link_far_side(phys_int, router_ints)
    if far_side_int:
        far_side_device = nb.dcim.devices.get(far_side_int.device.id)
        sw_name = far_side_device.virtual_chassis.name.split(".")[0] \
            if far_side_device.virtual_chassis else far_side_device.name.split(".")[0]

        # Linux netdev name length is limited to 15 characters, so:
        sw_name = sw_name.replace("cloud", "c")[:15]

        add_device_interface(sw_name, far_side_int.name, [], "bridge", "Link to {}".format(router.name), 10)
        add_device_interface(router.name, phys_int.name, [], "crpd", "Link to {}".format(sw_name), 10)

        link_descr = "{} {} to {} {}".format(router.name, phys_int, sw_name, far_side_int)
        add_ordered_link(router.name, phys_int, sw_name, far_side_int, link_descr)

    else:
        print("ERROR: No far-side dev found for {} on {}".format(phys_int.name, router.name))


def get_link_far_side(interface, router_ints):
    # Gets far side interface when passed interface object.
    if interface.type.value == "lag":
        # Get physical that is member and work out other side
        for router_int in router_ints:
            if router_int.lag:
                if router_int.lag.name == interface.name:
                    if router_int.connected_endpoint_type == "dcim.interface":
                        phys_int_b = nb.dcim.interfaces.get(router_int.connected_endpoint.id)
                        return nb.dcim.interfaces.get(phys_int_b.lag.id)
                    else:
                        print("ERROR: Connection to {} is not dcim.interface as expected".format(router_int.name))
    else:
        # No LAG, nice and simple
        return nb.dcim.interfaces.get(interface.connected_endpoint.id)


def get_p2p_metric(int_a, int_b):
    # Gets metrics for non cct interfaces from YAML data
    r1 = "{}.wikimedia.org".format(int_a.device.name)
    r2 = "{}.wikimedia.org".format(int_b.device.name)
    r1_int = int_a.name if "." in int_a.name else "{}.0".format(int_a.name)
    r2_int = int_a.name if "." in int_b.name else "{}.0".format(int_b.name)
 
    for link in homer_cfg_common['ospf']['p2p']:
        if r1 in link.keys() and r2 in link.keys():
            if link[r1] == r1_int and link[r2] == r2_int:
                if "metric" in link.keys():
                    return link['metric']
                else: # default metric of 10
                    return 10

    # Interface not in YAML, return -1 to indicate we don't run OSPF on this
    return -1


def get_stub_metric(device_name, int_name):
    r1 = "{}.wikimedia.org".format(device_name)

    if r1 in homer_cfg_common['ospf']['stub']:
        if int_name in homer_cfg_common['ospf']['stub'][r1]:
            return 2

    return -1


def get_metric_from_descr(*interfaces):
    # Tries to find NNNms in description and returns (NNN * 10)
    for interface in interfaces:
        # All links involving MR routers get 20000 metric
        if interface.device.name.startswith("mr"):
            return 20000
        for word in interface.description.split():
            if re.match('^\d+ms', word):
                return int(word.split("ms")[0]) * 10

    # Default to 10: 2 seen in real life so....
    return 10


def get_addr_far_side(int_addrs):
    # Uses IP addrs as the most generic way to get far side, works for directly connected
    # ints as well as those via L2VPN, intermediate switch or GRE / tunnel ints.
    for ip_addr in int_addrs:
        address = ipaddress.ip_interface(ip_addr.address)
        subnet_ips = nb.ipam.ip_addresses.filter(parent=str(address.network))
        for subnet_ip in subnet_ips:
            if subnet_ip != ip_addr:
                if subnet_ip.assigned_object:
                    return nb.dcim.interfaces.get(subnet_ip.assigned_object.id)


def add_device_interface(router_name, int_name, int_addrs, router_kind, descr, metric):
    add_device(router_name, router_kind)

    # bridges are in default netns and thus need unique names
    if router_kind == "bridge":
        # Using first few digits of hash only - risky, but be unlikely to get collision
        router_hash = hash(router_name) % 100000000
        netdev = "eth{}{}".format(router_hash, len(devices[router_name]['phys_ints'])+1)
    else:
        netdev = "eth{}".format(len(devices[router_name]['phys_ints'])+1)

    if int_name not in devices[router_name]['phys_ints']:
        devices[router_name]['phys_ints'][int_name] = { 
            "addrs": int_addrs,
            "clab_dev": netdev,
            "descr": descr,
            "metric": metric
        }
        

def add_device(router_name, kind):
    if router_name not in devices.keys():
        devices[router_name] = {}
        devices[router_name]['kind'] = kind
        devices[router_name]['phys_ints'] = {}
        devices[router_name]['subints'] = {}


def add_ordered_link(router1, int1, router2, int2, descr=""):
    # Pass router 'A' and 'B' based on lowest interface ID, so we'll always get same hash
    if int1.id < int2.id:
        add_link(router1, int1.name, router2, int2.name, descr)
    else:
        add_link(router2, int2.name, router1, int1.name, descr)


def add_link(router_a, int_a, router_b, int_b, descr=""):
    # Set a generic description if none passed
    if not descr:
        descr = "{} {} to {} {}".format(router_a, int_a, router_b, int_b)        

    link_id = hash((router_a, int_a, router_b, int_b))
    links[link_id] = {
        "dev_a": router_a,
        "int_a": devices[router_a]['phys_ints'][int_a]['clab_dev'],
        "dev_b": router_b,
        "int_b": devices[router_b]['phys_ints'][int_b]['clab_dev'],
        "descr": descr
    }
        

def add_loopback(router, int_addrs):
    # Adds loopback IP details for device
    add_device(router.name, "crpd") 
    devices[router.name]['loop_addrs'] = int_addrs

     
def write_files():
    '''
    # For debugging purposes
    print()
    for device_name, device_vars in devices.items():
        print("{} - {}".format(device_name, device_vars))
    print()
    for link in links.values():
        print(link)
    '''

    print()
    p = Path('output')
    p.mkdir(exist_ok=True)
    write_clab_topology()
    write_start_script()
    write_stop_script()
    print()


def write_clab_topology():
    out_data = {
        "name": args.name,
        "topology": {
            "nodes": {},
            "links": []
        }
    }

    print("Building clab topology and creating device base configs...")
    for device_name, device_vars in devices.items():
        out_data['topology']['nodes'][device_name] = {
            "kind": device_vars['kind']
        }
        if device_vars['kind'] == "crpd":
            out_data['topology']['nodes'][device_name]['image'] = "crpd"
            if args.license:
                out_data['topology']['nodes'][device_name]['license'] = args.license
            out_data['topology']['nodes'][device_name]['config'] = "configs/crpd/{}.cfg".format(device_name)

            file_loader = FileSystemLoader('templates')
            env = Environment(loader=file_loader)
            template = env.get_template('crpd.j2')
            p = Path('output/configs/crpd')
            p.mkdir(parents=True, exist_ok=True)
            conf_file = (p / '{}.cfg'.format(device_name)).open('w')
            conf_file.write(template.render(device_name=device_name, config=device_vars))
            conf_file.close()
    
    for link in links.values():
        out_data['topology']['links'].append({
            "endpoints": [
                "{}:{}".format(link['dev_a'], link['int_a']),
                "{}:{}".format(link['dev_b'], link['int_b'])
        ]})

    print("Writing clab topology file {}.yaml...".format(args.name))
    out_file = open('output/{}.yaml'.format(args.name), 'w')    
    yaml.safe_dump(out_data, out_file)
    out_file.close()            


def write_start_script():
    print("Writing start_{}.sh...".format(args.name))
    out_file = open("output/start_{}.sh".format(args.name), 'w')
    out_file.write("#!/bin/bash\n")
    out_file.write("set -x\n")
    
    for device_name, device_vars in devices.items():
        if device_vars['kind'] == "bridge":
            out_file.write("sudo brctl addbr {}\n".format(device_name))
            out_file.write("sudo ip link set dev {} mtu 9212\n".format(device_name))
            out_file.write("sudo ip link set dev {} up\n\n".format(device_name))

    out_file.write("sudo clab deploy -t {}.yaml\n\n".format(args.name))
    
    for device_name, device_vars in devices.items():
        if device_vars['kind'] != "bridge":
            if "loop_addrs" in device_vars.keys():
                for address in device_vars['loop_addrs']:
                    out_file.write("sudo ip netns exec clab-{}-{} ip addr add {} dev lo\n".format(
                        args.name, device_name, address))

            for int_name, int_vars in device_vars['phys_ints'].items():
                out_file.write("sudo ip netns exec clab-{}-{} ip link set alias \"{}\" dev {}\n".format(
                    args.name, device_name, int_name, int_vars['clab_dev']))
                if int_vars['addrs']:
                    for address in int_vars['addrs']:
                        out_file.write("sudo ip netns exec clab-{}-{} ip addr add {} dev {}\n".format(
                            args.name, device_name, address, int_vars['clab_dev']))
                else:
                    # Only parent for sub-ints, delete IPv6 Link Local addr
                    out_file.write("sudo ip netns exec clab-{}-{} ip addr flush dev {}\n".format(
                         args.name, device_name, int_vars['clab_dev']))

            for subint_name, subint_vars in device_vars['subints'].items():
                out_file.write("sudo ip netns exec clab-{0}-{1} ip link add link {2} name {2}.{3} type vlan id {3}\n".format(
                    args.name, device_name, subint_vars['clab_dev'], subint_vars['vlan_id']))
                for address in subint_vars['addrs']:
                    out_file.write("sudo ip netns exec clab-{}-{} ip addr add {} dev {}.{}\n".format(
                        args.name, device_name, address, subint_vars['clab_dev'], subint_vars['vlan_id']))
                out_file.write("sudo ip netns exec clab-{}-{} ip link set dev {}.{} up\n".format(
                    args.name, device_name, subint_vars['clab_dev'], subint_vars['vlan_id']))
                out_file.write("sudo ip netns exec clab-{}-{} ip link set alias \"{}\" dev {}.{}\n".format(
                    args.name, device_name, subint_name, subint_vars['clab_dev'], subint_vars['vlan_id']))

            out_file.write("\n")

    out_file.close()
    os.chmod("output/start_{}.sh".format(args.name), 0o755)
    

def write_stop_script():
    print("Writing stop_{}.sh...".format(args.name))
    out_file = open("output/stop_{}.sh".format(args.name), 'w')
    out_file.write("#!/bin/bash\n")
    out_file.write("set -x\n")

    out_file.write("sudo clab destroy -t {}.yaml\n\n".format(args.name))

    for device_name, device_vars in devices.items():
        if device_vars['kind'] == "bridge":
            out_file.write("sudo ip link set dev {} down\n".format(device_name))
            out_file.write("sudo brctl delbr {}\n\n".format(device_name))

    out_file.close()
    os.chmod("output/stop_{}.sh".format(args.name), 0o755)


def getWebYaml(url):
    try:
        response = requests.get(url)
    except Exception as e:
        print("Error connecting to {}: {}\n".format(url, e))
        sys.exit(1)

    if response.status_code == 200:
        return yaml.load(response.text, Loader=yaml.SafeLoader)
    else:
        print("Error, HTTP return code {0} received trying to get {1}\n".format(response.status_code, url))
        sys.exit(1)


if __name__=="__main__":
    main()

