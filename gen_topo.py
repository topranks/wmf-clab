#!/usr/bin/python3

import argparse
import pynetbox
import ipaddress
import yaml
import os
from pathlib import Path
import sys
import json

parser = argparse.ArgumentParser(description='WMF Container Lab Topology Generator')
parser.add_argument('--netbox', help='Netbox server IP / Hostname', type=str, default='netbox.wikimedia.org')
parser.add_argument('-k', '--key', help='Netbox API Token / Key', type=str)
parser.add_argument('--name', help='Name for clab project, file names based on this.', default='wmf-lab')
parser.add_argument('-l', '--license', help='License file name for crpd if available', type=str)
args = parser.parse_args()

def main():
    global nb, devices, links, yaml_data, device_transits, dummy_routes
    devices, links, yaml_data, device_transits = {}, {}, {}, {}
    nb_url = "https://{}".format(args.netbox)
    nb_key = get_nb_key()
    nb = pynetbox.api(nb_url, token=nb_key, threading=True)

    prep_homer_repo()
    get_device_transits()
    add_isp_router()
    get_info()

    add_lvs_devices()

    # Load list of random routes we announce from fake isp router node
    with open('dummy_routes.yaml', 'r') as yaml_file:
        dummy_routes = yaml.safe_load(yaml_file)

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
        print(f"Gathering Netbox data for {router.name}...")
        if router.status.value in ('active', 'planned'):
            router_ints = list(nb.dcim.interfaces.filter(device_id=router.id))
            # router_ints = [router_int for router_int in nb_ints]
            for interface in router_ints:
                if interface.enabled and not interface.name.startswith("fxp"):
                    int_addrs = list(nb.ipam.ip_addresses.filter(interface_id=interface.id))
                    if int_addrs:
                        if interface.type.value == "virtual" and interface.name.startswith("lo"):
                            add_loopback(router, int_addrs)
                            continue

                        # Exclude VRRP VIPs / Special IPs - hence doing loopback int first above
                        int_addrs = [addr for addr in int_addrs if not addr.role]

                        # if interface.connected_endpoint_type = 'dcim.frontport':
                        # https://gerrit.wikimedia.org/r/c/operations/software/homer/+/813604

                        if interface.link_peer_type == "circuits.circuittermination":
                            circuit = interface.link_peer.circuit
                            add_circuit_interface(router, interface, int_addrs, circuit)
                        
                        elif interface.link_peer_type == "dcim.frontport":
                            if interface.link_peer.rear_port.link_peer_type == "circuits.circuittermination":
                                circuit = interface.link_peer.rear_port.link_peer.circuit
                                add_circuit_interface(router, interface, int_addrs, circuit)

                        # Gateway interfaces facing L2 switches
                        elif interface.description.lower().startswith("subnet"):
                            add_sw_subint(router, interface, int_addrs, router_ints)

                        else:
                            # Remaining transports over VPLS, GRE etc.
                            add_generic_transport(router, interface, int_addrs)


def add_circuit_interface(router, interface, int_addrs, circuit):
    if circuit.type.slug == "transit":
        add_transit_circuit(router, interface, int_addrs, circuit)
    else:
        add_generic_transport(router, interface, int_addrs)


def add_transit_circuit(router, interface, int_addrs, circuit):
    """ Adds device interface to WMF device terminating transit circuit, plus a 
        link from it to the 'isp_router' node and an interface there to terminate 
        it and simulate the ISP side """

    # Add WMF node interface    
    descr = f"{circuit.provider} Transit CCT {str(circuit)}"
    add_device_interface(router.name, interface.name, int_addrs, "crpd", descr)

    # Add 'isp_router' interface and record WMF peer IP + required ASN
    isp_rtr_int = get_next_eth_int(devices['isp_router'])
    descr = f"Peering to {router.name} {interface.name}"
    isp_rtr_addrs = []
    for nb_ip in int_addrs:
        wmf_ip = ipaddress.ip_interface(str(nb_ip))
        for peer_ip in device_transits[router.name].keys():
            if peer_ip in wmf_ip.network:
                isp_rtr_addrs.append(f"{peer_ip}/{wmf_ip.network.prefixlen}")
                local_as = device_transits[router.name][peer_ip]['AS']
                if local_as not in devices['isp_router']['bgp_groups']:
                    devices['isp_router']['bgp_groups'][local_as] = {
                        'provider': device_transits[router.name][peer_ip]['provider'],
                        'wmf_peers': []
                }
                devices['isp_router']['bgp_groups'][local_as]['wmf_peers'].append(str(wmf_ip.ip))
                break
    add_device_interface('isp_router', isp_rtr_int, isp_rtr_addrs, "crpd", descr)

    # Add link
    add_link(router.name, interface.name, 'isp_router', isp_rtr_int)
 

def add_generic_transport(router, interface, int_addrs):
    """ Adds device interfaces and entry in links{} for a generic L3 p2p link
        Gets far-side details using link IPs """
    far_side_int = get_addr_far_side(int_addrs)

    if far_side_int:
        far_side_addrs = list(nb.ipam.ip_addresses.filter(interface_id=far_side_int.id))

        add_device_interface(router.name, interface.name, int_addrs, "crpd", interface.description)
        add_device_interface(far_side_int.device.name, far_side_int.name, far_side_addrs, "crpd",
            far_side_int.description)
        add_ordered_link(router.name, interface, far_side_int.device.name, far_side_int)
#    else:
#       PNIs, GREs to Cloudflare, External links without attached CCT basically.


def add_sw_subint(router, interface, int_addrs, router_ints):
    """ Sub-interfaces which connect to a switch acting as gateway for hosts, i.e. ae1.1001.
        We extract parent int and add that to router if needed, as well as creating a linux
        container to act as switch as required, and link to the router physical.

        Lastly we record the sub-interface and IPs separately so we can add commands to 
        the startup script to create matching sub-interfaces in the container netns from the parent. """

    add_device(router.name, "crpd")

    parent_int = get_int_object(interface.name.split(".")[0], router_ints)
    unit = interface.name.split(".")[1]

    if parent_int:
        if parent_int.name not in devices[router.name]['phys_ints']:
            # Add new physical int to router, and new bridge dev if required.
            add_sw_physical(parent_int, router, router_ints)

        # Record sub-interface for device, along with IP addresses for it
        clab_parent_dev = devices[router.name]['phys_ints'][parent_int.name]['clab_dev']
        devices[router.name]['subints'][interface.name] = {
            "clab_dev": clab_parent_dev,
            "vlan_id": unit,
            "addrs": int_addrs,
        }

        # Record Vlan id against switch port to allow it
        sw_int, sw_name = get_far_side_sw(parent_int, router, router_ints)
        devices[sw_name]['phys_ints'][sw_int.name]['vlans'].append(unit)

    else:
        print("ERROR: No parent int found for {}".format(interface.name))


def get_int_object(int_name, interfaces):
    """ Returns element from interfaces with name equivalent to int_name """
    for interface in interfaces:
        if interface.name == int_name:
            return interface


def add_sw_physical(phys_int, router, router_ints):
    """ Find what phys_int is connected to and add the device as needed """
    far_side_int, sw_name = get_far_side_sw(phys_int, router, router_ints)

    add_device_interface(sw_name, far_side_int.name, [], "linux", "Link to {}".format(router.name))
    add_device_interface(router.name, phys_int.name, [], "crpd", "Link to {}".format(sw_name))

    link_descr = "{} {} to {} {}".format(router.name, phys_int, sw_name, far_side_int)
    add_ordered_link(router.name, phys_int, sw_name, far_side_int, link_descr)


def get_far_side_sw(phys_int, router, router_ints):
    """ Return device object connected to phys_int """
    far_side_int = get_link_far_side(phys_int, router_ints)
    if far_side_int:
        far_side_device = nb.dcim.devices.get(far_side_int.device.id)
        sw_name = far_side_device.virtual_chassis.name.split(".")[0] \
            if far_side_device.virtual_chassis else far_side_device.name.split(".")[0]
        return far_side_int, sw_name
    else:
        print("ERROR: No far-side dev found for {} on {}".format(phys_int.name, router.name))


def get_link_far_side(interface, router_ints):
    """ Gets far side interface when passed interface object. """
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


def get_addr_far_side(int_addrs):
    """ Uses IP addrs as the most generic way to get far side, works for directly connected
        ints as well as those via L2VPN, intermediate switch or GRE / tunnel ints. """
    for ip_addr in int_addrs:
        address = ipaddress.ip_interface(ip_addr.address)
        subnet_ips = nb.ipam.ip_addresses.filter(parent=str(address.network))
        for subnet_ip in subnet_ips:
            if subnet_ip != ip_addr:
                if subnet_ip.assigned_object:
                    return nb.dcim.interfaces.get(subnet_ip.assigned_object.id)


def add_device_interface(router_name, int_name, int_addrs, router_kind, descr):
    """ Adds required details for a container interface to internal devices dict.
        Will also add the device itself if it is not already there."""
    
    add_device(router_name, router_kind)

    if int_name not in devices[router_name]['phys_ints']:
        devices[router_name]['phys_ints'][int_name] = { 
            "addrs": int_addrs,
            "clab_dev": int_name.replace('/', '_').replace(':', '_'),
            "descr": descr,
            "vlans": []
        }
        

def add_isp_router():
    devices['isp_router'] = {}
    devices['isp_router']['kind'] = "crpd"
    devices['isp_router']['phys_ints'] = {}
    devices['isp_router']['subints'] = {}
    devices['isp_router']['sub_type'] = "isp_router"
    devices['isp_router']['bgp_groups'] = {}


def add_device(router_name, kind, sub_type=None):
    if router_name not in devices.keys():
        devices[router_name] = {}
        devices[router_name]['kind'] = kind
        devices[router_name]['phys_ints'] = {}
        devices[router_name]['subints'] = {}
        devices[router_name]['sub_type'] = sub_type

        # Homer connects to the FQDN of primary IP, not Netbox name, so get that
        nb_device = nb.dcim.devices.get(name=router_name)
        if nb_device:
            if nb_device.primary_ip4 is not None and nb_device.primary_ip4.dns_name:
                devices[router_name]['fqdn'] = nb_device.primary_ip4.dns_name
            elif nb_device.primary_ip6 is not None and nb_device.primary_ip6.dns_name:
                devices[router_name]['fqdn'] = nb_device.primary_ip6.dns_name
        else:
            # This can happen with VC as names are full FQDN for those in NB
            vc = nb.dcim.virtual_chassis.filter(name__startswith=router_name)
            if vc:
                devices[router_name]['sub_type'] = "bridge"


def add_ordered_link(router1, int1, router2, int2, descr=""):
    """ Pass router 'A' and 'B' based on lowest Netbox interface ID.  This ensures 
        if we try to add a link a second time (parsing far-side router) the details 
        are the same and we avoid duplication. """

    if int1.id < int2.id:
        add_link(router1, int1.name, router2, int2.name, descr)
    else:
        add_link(router2, int2.name, router1, int1.name, descr)


def add_link(router_a, int_a, router_b, int_b, descr=""):
    # Set a generic description if none passed
    if not descr:
        descr = "{} {} to {} {}".format(router_a, int_a, router_b, int_b)        

    # Key on hash of router and port IDs, ensures uniqueness
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
    # For debugging purposes
    '''
    from pprintpp import pprint as pp
    pp(devices)
    print("\n\n")
    pp(links)
    print("\n\n")
    pp(dummy_routes)
    '''

    p = Path('output')
    p.mkdir(exist_ok=True)
    write_clab_topology()
    write_start_script()
    write_stop_script()
    write_fqdn_map()
    write_isp_rtr_config()
    print()
    

def write_clab_topology():
    out_data = {
        "name": args.name,
        "mgmt": {
            "network": "wmf_lab",
            "bridge": "wmf_lab",
            "external-access": False
        },
        "topology": {
            "nodes": {},
            "links": []
    } }

    print("Building clab topology...")
    for device_name, device_vars in devices.items():
        out_data['topology']['nodes'][device_name] = {
            "kind": device_vars['kind'],
            "binds": ["~/.ssh/id_ed25519.pub:/root/.ssh/authorized_keys"]
        }
        if device_vars['kind'] == "crpd":
            out_data['topology']['nodes'][device_name]['image'] = "crpd"
            if args.license:
                out_data['topology']['nodes'][device_name]['license'] = args.license
        else:
            out_data['topology']['nodes'][device_name]['image'] = "debian:latest"

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


def write_fqdn_map():
    print("Writing fqdn.yaml...")
    out_file = open("output/fqdn.yaml".format(args.name), 'w')
    
    fqdn_map = {}
    for device_name, device_vars in devices.items():
        if "fqdn" in device_vars:
            fqdn_map[device_name] = device_vars['fqdn']

    yaml.safe_dump(fqdn_map, out_file)
    out_file.close()


def write_start_script():
    print("Writing start_{}.sh...".format(args.name))
    out_file = open("output/start_{}.sh".format(args.name), 'w')
    out_file.write("#!/bin/bash\n")
    out_file.write("set -x\n")
    
    out_file.write("sudo clab deploy -t {}.yaml\n".format(args.name))
    out_file.write("../add_fqdn_hosts.py\n\n") 
    
    dns_resolvers = get_dns_resolvers()

    for device_name, device_vars in devices.items():
        if "loop_addrs" in device_vars.keys():
            for address in device_vars['loop_addrs']:
                out_file.write("sudo ip netns exec clab-{}-{} ip addr add {} dev lo\n".format(
                    args.name, device_name, address))

        out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip route del default via 172.20.20.1\n")
        out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip -6 route del default via 2001:172:20:20::1\n")
            
        for resolver in dns_resolvers:
            # Should be changed to detect v4/v6 IP and use appropriate next-hop, also discover GW IP and not assume default
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip route add {resolver} via 172.20.20.1\n")

        if device_vars['sub_type'] == "bridge":
            # This container should have a vlan-aware bridge created, which we'll attach all physicals to
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                            "ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q " \
                            "vlan_stats_enabled 1 vlan_stats_per_port 1\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip link set dev br0 mtu 9212\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip link set dev br0 up\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip addr flush dev br0\n\n")

        for int_name, int_vars in device_vars['phys_ints'].items():
            out_file.write("sudo ip netns exec clab-{}-{} ip link set alias \"{}\" dev {}\n".format(
                args.name, device_name, int_name, int_vars['clab_dev']))

            if device_vars['sub_type'] == "bridge":
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                               f"ip link set dev {int_vars['clab_dev']} master br0\n")
                # Vlan 1 defaults to native VLAN.  Delete to block untagged frames.
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                               f"bridge vlan del dev {int_vars['clab_dev']} vid 1\n")
                for vlan in int_vars['vlans']:
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                                   f"bridge vlan add dev {int_vars['clab_dev']} vid {vlan}\n")
                if "access_vlan" in int_vars:
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                                   f"bridge vlan add dev {int_vars['clab_dev']} vid {int_vars['access_vlan']} " \
                                   f"pvid untagged\n")

            if int_vars['addrs']:
                for address in int_vars['addrs']:
                    out_file.write("sudo ip netns exec clab-{}-{} ip addr add {} dev {}\n".format(
                        args.name, device_name, address, int_vars['clab_dev']))
            else:
                # No unicast address - best to delete v6 link local too.
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

        if device_vars['sub_type'] == "lvs":
            # Add default via .2 address on eth1 subnet to allow peering to CRs
            lvs_eth1_ip = ipaddress.ip_interface(device_vars['phys_ints']['eth1']['addrs'][0])
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip route add default via {lvs_eth1_ip.network[2]}\n")

        out_file.write("\n")

    out_file.write('\n../junos_push_lvs_conf.py -c ../lvs_config.json\n\n')
    out_file.write('../junos_push_isp_router_conf.py -c ./isp_router_conf.json\n')

    out_file.close()
    os.chmod("output/start_{}.sh".format(args.name), 0o755)
   
 
def get_dns_resolvers():
    resolvers = []
    with open('/etc/resolv.conf', 'r') as resolvconf:
        for line in resolvconf.readlines():
            if line.startswith("nameserver"):
                resolvers.append(line.split()[1])

    return resolvers
    

def write_stop_script():
    print("Writing stop_{}.sh...".format(args.name))
    out_file = open("output/stop_{}.sh".format(args.name), 'w')
    out_file.write("#!/bin/bash\n")
    out_file.write("set -x\n")

    out_file.write("sudo clab destroy -t {}.yaml\n\n".format(args.name))

    out_file.close()
    os.chmod("output/stop_{}.sh".format(args.name), 0o755)


def get_device_transits():
    """ Parses devices.yaml and extracts transit peer data for each device """
    for device_name, device_vars in yaml_data['devices'].items():
        if "transits" in device_vars['config'].keys():
            short_name = device_name.split(".")[0]
            device_transits[short_name] = {}
            for peer_ip_str, peer_vars in device_vars['config']['transits'].items():
                peer_ip = ipaddress.ip_address(peer_ip_str)
                device_transits[short_name][peer_ip] = {}
                device_transits[short_name][peer_ip]['provider'] = peer_vars['provider']
                device_transits[short_name][peer_ip]['AS'] = \
                    yaml_data['common']['transit_providers'][peer_vars['provider']]['AS']


def prep_homer_repo():
    """ Clones homer public repo and makes some modifications to allow it to work with crpd rather
        than MX. """
    # clone the repo using git
    clone_homer_repo()

    # Remove capirca key from devices and roles so firewall filters won't be generated
    remove_capirca_key("operations-homer-public/config/devices.yaml")
    remove_capirca_key("operations-homer-public/config/roles.yaml")

    # Remove prefix-lists from common-prefix-lists.conf with incompatible 'apply-groups'
    remove_pfx_list = ['loopback4', 'loopback6', 'system-ntp']
    remove_prefix_lists_j2file('operations-homer-public/templates/includes/policies/common-prefix-lists.conf', remove_pfx_list)
    # Same for cr/policy-options.conf
    remove_prefix_lists_j2file('operations-homer-public/templates/cr/policy-options.conf', ['system-nameservers'])

    # Replace top-level cr.conf template with crpd template
    os.system("rm -f operations-homer-public/templates/cr.conf && cp templates/crpd.j2 operations-homer-public/templates/cr.conf")
    # Replace OSPF template with custom one (no BFD and adjust interface names)
    os.system("rm -f operations-homer-public/templates/common/ospf.conf && cp templates/ospf.j2 operations-homer-public/templates/common/ospf.conf")
    # Replace routing-options with one that just covers aggregates, no RPKI etc.
    os.system("rm -f operations-homer-public/templates/cr/routing-options.conf && cp templates/routing-options.j2 operations-homer-public/templates/cr/routing-options.conf")

    # Load data from YAML files so it's available to us
    with open('operations-homer-public/config/devices.yaml', 'r') as yaml_file:
        yaml_data['devices'] = yaml.safe_load(yaml_file)
    with open('operations-homer-public/config/common.yaml', 'r') as yaml_file:
        yaml_data['common'] = yaml.safe_load(yaml_file)
    with open('operations-homer-public/config/sites.yaml', 'r') as yaml_file:
        yaml_data['sites'] = yaml.safe_load(yaml_file)
    with open('operations-homer-public/config/roles.yaml', 'r') as yaml_file:
        yaml_data['roles'] = yaml.safe_load(yaml_file)

    print()


def clone_homer_repo():
    if Path('operations-homer-public').is_dir():
        print("Deleting existing homer public repo directory...")
        os.system("rm -Rf operations-homer-public")
        
    if Path('operations-homer-mock-private').is_dir():
        print("Deleting existing homer mock private repo directory...\n")
        os.system("rm -Rf operations-homer-mock-private")

    os.system("git clone --depth 1 https://github.com/wikimedia/operations-homer-public")
    print()
    os.system("git clone --depth 1 https://github.com/wikimedia/operations-homer-mock-private")
    print()

def remove_capirca_key(filename):
    """ Loads data from YAML file, removes dict keys with value 'capirca' and re-writes """
    
    with open(filename, "r") as yaml_file:
        data = yaml.safe_load(yaml_file)
        for element_name, element_values in data.items():
            try:
                del data[element_name]['capirca']
            except KeyError:
                pass
            if "config" in element_values.keys():
                try:
                    del data[element_name]['config']['capirca']
                except KeyError:
                    pass

    with open(filename, "w") as new_file:
        print(f"Removing capirca defs from {filename}...")
        yaml.dump(data, new_file)

                
def remove_prefix_lists_j2file(filename, pfx_lists):
    """ Interates over Jinja2 template and removes prefix-list definitions with names
        matching those in array pfx_lists[]. """

    with open('/tmp/new_file', "w") as new_file:
        write_lines = True
        with open(filename, 'r') as old_file:
            for line in old_file.readlines():
                if line.startswith("prefix-list") and line.split()[1] in pfx_lists:
                    write_lines = False
                if write_lines:
                    new_file.write(line)
                elif line.startswith("}"):
                    write_lines = True

    os.system(f"rm -fv {filename} && mv -v /tmp/new_file {filename}")


def add_lvs_devices():
    """ Parse sites.yaml from Homer repo and create crpd device to represent each LVS """
    print("\nAdding LVS devices...")

    # If saved YAML file with LVS service IPs is present load the data
    try:
        with open('lvs_getvips/lvs_vips.yaml', 'r') as yaml_file:
            lvs_vips = yaml.safe_load(yaml_file)
    except FileNotFoundError:
        lvs_vips = None

    for site_name, site_vars in yaml_data['sites'].items():
        try:
            for lvs_name, lvs_ip in site_vars['lvs_neighbors'].items():
                # Get vlan associated with IP from netbox
                nb_ip = ipaddress.ip_interface(nb.ipam.ip_addresses.get(address=lvs_ip))
                nb_subnet = nb.ipam.prefixes.get(prefix=str(nb_ip.network))
                # Iterate over devices - find switch with this vlan
                lvs_dev = None
                for device_name, device_vars in devices.items():
                    if device_vars['sub_type'] == "bridge":
                        # Check if it's the right switch by looking for LVS vlan
                        for interface_name, int_data in device_vars['phys_ints'].items():
                            if str(nb_subnet.vlan.vid) in int_data['vlans']:
                                switch_name = device_name
                                lvs_dev = get_lvs_dev(lvs_name, str(nb_ip), lvs_vips)
               
                if lvs_dev:
                    devices[lvs_name] = lvs_dev
                    add_br_access_port(switch_name, nb_subnet.vlan.vid, lvs_name, "eth1")

        except KeyError:
            # No LVS at site
            pass


def get_lvs_dev(lvs_name, lvs_ip, lvs_vips):
    """ Creates device entry for lvs - only ever has 1 interface """
    lvs_dev = {
        'kind': 'crpd',
        'sub_type': 'lvs',
        'subints': {},
        'phys_ints': { 
            'eth1': {
                'addrs': [lvs_ip],
                'clab_dev': 'eth1', 
                'descr': '',
    } } }

    if lvs_name in lvs_vips.keys():
        lvs_dev['loop_addrs'] = lvs_vips[lvs_name]['vips']

    return lvs_dev


def add_br_access_port(bridge_name, vlan_id, far_side_device, far_side_int):
    """ Adds access port to a device acting as L2 switch, and link between it and attached device """
    bridge_dev = devices[bridge_name]
    int_name = get_next_eth_int(bridge_dev)
    
    bridge_dev['phys_ints'][int_name] = {
        'addrs': [],
        'clab_dev': int_name,
        'descr': f"link to {far_side_device} {far_side_int}",
        'access_vlan': vlan_id,
        'vlans': []
    }

    add_link(bridge_name, int_name, far_side_device, far_side_int)


def get_next_eth_int(device_data):
    """ Returns name for next eth interface on a device """
    eth_ints = [eth_int for eth_int in device_data['phys_ints'].keys() if eth_int.startswith('eth')]
    return f"eth{len(eth_ints) + 1}"


def write_isp_rtr_config():
    ''' Write JunOS config in JSON format to file which will be loaded to isp_router node '''

    print("Writing isp_router_conf.json...")
    rtr_conf = {
        'policy-options': {
            'policy-statement': [],
            'prefix-list': []
        },
        'routing-options': {
            'rib': [{
                'name': 'inet6.0',
                'static': {
                    'route': [{
                        'name': '2000::/3',
                        'next-hop' : ['2001:172:20:20::1']
            }]}}],
            'static': {
                'route': [{
                    'name': '0.0.0.0/1',
                    'next-hop': ['172.20.20.1']
                },
                {
                    'name': '128.0.0.0/1',
                    'next-hop': ['172.20.20.1']
        }]}},
        'protocols': {
            'bgp': {
                'group': []
    }}}

    # Add IPv4 static routes for ranges we want to announce
    for v4_routes in dummy_routes['4'].values():
        for v4_route in v4_routes:
            route_conf = {
                'name': v4_route,
                'next-hop': ['172.20.20.1']
            }
            rtr_conf['routing-options']['static']['route'].append(route_conf)

    # Add IPv6 static routes
    for v6_routes in dummy_routes['6'].values():
        for v6_route in v6_routes:
            route_conf = {
                'name': v6_route,
                'next-hop' : ['2001:172:20:20::1']
            }
            rtr_conf['routing-options']['rib'][0]['static']['route'].append(route_conf)

    # Add prefix-lists for routes we'll use same dummy as-path
    for ip_version, path_groups in dummy_routes.items():
        for as_path, networks in path_groups.items():
            pfx_list_conf = {
                'name': f'PFX_V{ip_version}_{as_path.replace(" ", "_")}',
                'prefix-list-item': []
            }
            for network in networks:
                pfx_list_conf['prefix-list-item'].append({
                    'name': network
                })
            rtr_conf['policy-options']['prefix-list'].append(pfx_list_conf)

    # Add policy-statements to add as-path prepends
    for local_as, group_vars in devices['isp_router']['bgp_groups'].items():
        policy = {}
        for ip_version in ['4', '6']:
            policy[ip_version] = {
                'name': f"{group_vars['provider'].upper()}-OUT{ip_version}",
                'term': []
            }

            # Allow 0.0.0.0/1 and 128.0.0.0/1 if it's a v4 policy
            if ip_version == '4':
                for index, network in enumerate(['0.0.0.0/1', '128.0.0.0/1']):
                    term = {
                        'name': f"HALF{index + 1}",
                        'from': {
                            'protocol': ["static"],
                            'route-filter': [{
                                'address': network,
                                'exact': [None]
                            }]
                        },
                        'then': {
                            'accept': [None]
                        }
                    }
                    # Alternate pre-pend on each of the routes
                    if (local_as + index) % 2 == 0:
                        term['then']['as-path-prepend'] = f"{local_as} {local_as}"
                    policy[ip_version]['term'].append(term)
            else:
                # V6 - add term to announce global unicast range
                policy[ip_version]['term'].append({
                    'name': "GLOBAL_UNICAST",
                    'from': {
                        'protocol': ["static"],
                        'route-filter': [{
                            'address': '2000::/3',
                            'exact': [None]
                        }]
                    },
                    'then': {
                        'accept': [None]
                    }
                })

            # Add term for every different AS-path we'll prepend
            for as_path, networks in dummy_routes[ip_version].items():
                valid_asns = []
                # Pre-pend once or twice randomly:
                prepends = hash(as_path + str(local_as)) % 3
                # But more often don't
                if prepends > 0:
                    preprends = prepends - (hash(as_path + str(local_as)) % 2)
                valid_asns = [str(local_as)] * prepends
                # Add remaining ASNs to path - do not add our own if present
                asns = as_path.split()
                for asn in asns:
                    if asn != str(local_as):
                        valid_asns.append(asn)
                policy_term = {
                    'name': f'PATH_{"_".join(valid_asns)}',
                    'from': {
                        "protocol": ["static"],
                        "prefix-list": [{
                            "name": f'PFX_V{ip_version}_{as_path.replace(" ", "_")}'
                        }]
                    },
                    'then': {
                        'as-path-expand': {
                            "aspath": f'{" ".join(valid_asns)}'
                        },
                        'accept': [None]
                    }
                }
                policy[ip_version]['term'].append(policy_term)
            rtr_conf['policy-options']['policy-statement'].append(policy[ip_version])
            
            # Create BGP group
            bgp_group = {
                "name": f"{group_vars['provider'].upper()}{ip_version}",
                "export": [f"{group_vars['provider'].upper()}-OUT{ip_version}"],
                "peer-as": "14907",
                "local-as": {
                    "as-number": str(local_as),
                    "private": [None],
                    "no-prepend-global-as": [None]
                },
                "neighbor": []
            }
            for wmf_peer in group_vars['wmf_peers']:
                if str(ipaddress.ip_address(wmf_peer).version) == ip_version:
                    bgp_group['neighbor'].append({'name': wmf_peer})
            rtr_conf['protocols']['bgp']['group'].append(bgp_group)


    # Write config to file
    with open('output/isp_router_conf.json', 'w') as out_file:
        out_file.write(json.dumps(rtr_conf))    


if __name__=="__main__":
    main()

