#!/usr/bin/python3

import argparse
import pynetbox
import ipaddress
import yaml
import os
from pathlib import Path
import sys
import json
from pprintpp import pprint as pp

import pickle

import urllib3
urllib3.disable_warnings()

parser = argparse.ArgumentParser(description='WMF Container Lab Topology Generator')
parser.add_argument('--netbox', help='Netbox server IP / Hostname', type=str, default='netbox.wikimedia.org')
parser.add_argument('-k', '--key', help='Netbox API Token / Key', type=str)
parser.add_argument('--name', help='Name for clab project, file names based on this.', default='wmf-clab')
parser.add_argument('-l', '--license', help='License file name for crpd if available', type=str)
parser.add_argument('--hosts', help='Comma separated list of hosts to add to the topology', type=str, default="")
parser.add_argument('--load-pickle', help='Comma separated list of hosts to add to the topology', action='store_true')
parser.add_argument('--roles', help='Comma separate list of roles to pull (default: cr,clousw)', type=str, default="cr,cloudsw")
parser.add_argument('--statuses', help='Comma separate list of device status to pull (default: active)', type=str, default="active")
# TODO: add 'sites' option to select only get initial devices from given site
args = parser.parse_args()

import clab_repos
import clab_write

def main():
    global nb, devices, links, yaml_data, device_transits
    if args.load_pickle:
        # Load the data from dumped file - use when working on clab topo generation
        devices, links, yaml_data, device_transits = load_pickle()
    else:
        # Create data structures from netbox etc.
        nb = nb_connect()
        yaml_data = clab_repos.prep_homer_repo()
        device_transits = clab_repos.get_device_transits(yaml_data)
        devices, links = {}, {}
        add_isp_router()
        get_nb_info()
        add_hosts()
        save_pickle()

    pp(devices)
    print()
    pp(links)

    # Write ContainerLab format output topology 
    clab_write.write_files(args, devices, links, yaml_data)


def save_pickle():
    pickle_vars = {
        "devices": devices,
        "links": links,
        "yaml_data": yaml_data,
        "device_transits": device_transits
    }

    with open('pickle_vars.data', 'wb') as dump_file:
        pickle.dump(pickle_vars, dump_file)

def load_pickle():
    with open('pickle_vars.data', 'rb') as dump_file:
        pickle_vars = pickle.load(dump_file)

    return pickle_vars['devices'], pickle_vars['links'], pickle_vars['yaml_data'], pickle_vars['device_transits']
    

def add_hosts():
    # TODO: Make the input a series of comma-seperated globs so we can go lvs*
    if args.hosts:
        nb_hosts = nb.dcim.devices.filter(name=args.hosts.split(","))
        for nb_host in nb_hosts:
            add_host(nb_host)


def add_host(nb_host):
    nb_ints = nb.dcim.interfaces.filter(device_id=nb_host.id, enabled="true")
    for nb_int in nb_ints:
        far_side_int, far_side_dev = get_far_side_dev(nb_int, nb_host)
        if far_side_int is not None and far_side_int.enabled:
            sw_name = get_device_name(far_side_dev)
            if sw_name in devices:
                int_addrs = list(nb.ipam.ip_addresses.filter(interface_id=nb_int.id))
                add_device_interface(nb_host.name, nb_int.name, int_addrs, nb_int.description, nb_host)
                add_device_interface(sw_name, far_side_int.name, [], far_side_int.description, far_side_dev)
                add_ordered_link(nb_host.name, nb_int, sw_name, far_side_int)

        if nb_int.parent:
            int_addrs = list(nb.ipam.ip_addresses.filter(interface_id=nb_int.id))
            add_subint(nb_host, nb_int, int_addrs)    

        # Add bridges
        # if nb_int.bridge:


def get_nb_info():
    """ Main loop that iterates over NB devices and extracts required data to the 'devices' and 
        'links' variables as needed to generate the clab topology and startup script files. """
    print()
    roles = [role.strip() for role in args.roles.split(",")]
    statuses = [status.strip() for status in args.statuses.split(",")]
    l3_devices = nb.dcim.devices.filter(role=roles, status=statuses)
    for nb_device in l3_devices:
        print(f"Gathering Netbox data for {nb_device.name}...")
        add_device(nb_device)
        
        # Iterate over device nb_ints and process each
        for interface in devices[nb_device.name]['nb_ints'].values():
            if not interface.mgmt_only and not interface.lag:
                if interface.count_ipaddresses:
                    add_l3_int(nb_device, interface)
                else:
                    add_l2_int(nb_device, interface)
            

def nb_connect():
    nb_url = "https://{}".format(args.netbox)
    if args.key:
        nb_key = args.key
    else:
        from getpass import getpass
        nb_key = getpass(prompt="Netbox API Key: ")

    nb = pynetbox.api(nb_url, token=nb_key, threading=True)
    nb.http_session.verify = False
    return nb


def get_device_name(nb_device):
    """ Returns device name for regular device, or gets it from VC """
    if nb_device.virtual_chassis:
       return nb_device.virtual_chassis.name.split(".")[0]
    else:
        return nb_device.name


def add_isp_router():
    """ Generic crpd device we always add.  Used to simulate upstream transit providers """
    devices['isp_router'] = {}
    devices['isp_router']['kind'] = "crpd"
    devices['isp_router']['phys_ints'] = {}
    devices['isp_router']['subints'] = {}
    devices['isp_router']['sub_type'] = "isp_router"
    devices['isp_router']['bgp_groups'] = {}


def add_l3_int(nb_device, interface):
    """ Routed interface (i.e. has IPs on it) """
    int_addrs = []
    for int_addr in nb.ipam.ip_addresses.filter(interface_id=interface.id):
        int_addrs.append(ipaddress.ip_interface(int_addr.address))

    if interface.count_fhrp_groups > 0:
        int_addrs = get_vrrp_ips(nb_device, interface, int_addrs) + int_addrs

    if interface.type.value == "virtual" and interface.name.startswith("lo"):
        devices[get_device_name(nb_device)]['loop_addrs'] = int_addrs
        return
    
    if interface.name.startswith("irb."):
        devices[get_device_name(nb_device)]['irb_ints'][interface.name] = int_addrs
        return

    if interface.name.startswith("gr-"):
        add_generic_transport(nb_device, interface, int_addrs)
        return

    if interface.parent:
        add_subint(nb_device, interface, int_addrs)
        return

    circuit = get_circuit(interface)
    if circuit:
        add_circuit_interface(nb_device, interface, int_addrs, circuit)
    else:
        add_generic_transport(nb_device, interface, int_addrs)


def get_vrrp_ips(nb_device, interface, int_ips):
    """ Returns list with any VRRP IPs that should be added to the address list for this int.
        VRRP is supported in cRPD 23 on, but for now we just assign VIP to one device """
    vrrp_ips = []
    for fhrp_assignment in nb.ipam.fhrp_group_assignments.filter(interface_id=interface.id):
        assignments = nb.ipam.fhrp_group_assignments.filter(group_id=fhrp_assignment.group.id)
        group_members = sorted([assignment.interface.device.name for assignment in assignments])
        # Only add VIPs on first member device
        if nb_device.name == group_members[0]:
            for nb_vip in fhrp_assignment.group.ip_addresses:
                vip_addr = ipaddress.ip_interface(nb_vip.address)
                # VIPs are /32s in Netbox for some weird reason, we need to change mask
                for int_ip in int_ips:
                    if vip_addr.ip in int_ip.network:
                        vrrp_ips.append(ipaddress.ip_interface(f"{vip_addr.ip}/{int_ip.network.prefixlen}"))

    return vrrp_ips


def add_subint(nb_device, interface, int_addrs):
    parent_int = interface.parent
    far_side_int, far_side_dev = get_far_side_dev(parent_int, nb_device)
    if far_side_dev:
        if interface.untagged_vlan:
            vlan_id = interface.untagged_vlan.vid
        else:
            vlan_id = interface.name.split(".")[-1]
        devices[get_device_name(nb_device)]['subints'][interface.name] = {
            "clab_dev": parent_int.name.replace('/', '_').replace(':', '_'),
            "subint_dev": interface.name.replace('/', '_').replace(':', '_'),
            "vlan_id": vlan_id,
            "addrs": int_addrs,
        }

    else:
        # No far side device - mostly VPLS WAN, add as generic link
        add_generic_transport(nb_device, interface, int_addrs)


def add_l2_int(nb_device, interface):
    """ Interface on L3 device with no IPs on it.  Either a L2 trunk on a 
        switch, or a parent interface for 802.1q subints """

    far_side_int, far_side_dev = get_far_side_dev(interface, nb_device)
    if far_side_dev:
        if far_side_dev.device_role.slug == "server":
            return
        else:
            add_device_interface(get_device_name(nb_device), interface.name, [], interface.description, nb_device)
            add_device_interface(get_device_name(far_side_dev), far_side_int.name, [],
                far_side_int.description, far_side_dev)
            add_ordered_link(get_device_name(nb_device), interface, get_device_name(far_side_dev), far_side_int)


def add_circuit_interface(nb_device, interface, int_addrs, circuit):
    if circuit.type.slug == "transit":
        add_transit_circuit(nb_device, interface, int_addrs, circuit)
    elif circuit.type.slug == "transport":
        add_generic_transport(nb_device, interface, int_addrs)
    # else:  TODO: ADD PEERING


def get_circuit(interface):
    """ Returns circuit from nb_interface if it connects one. """
   
    # If the interface is a LAG check member port instead 
    if interface.type.value == "lag":
        interface = get_lag_member(interface)

    if interface.link_peer_type == "circuits.circuittermination":
        return interface.link_peer.circuit
    if interface.link_peer_type == "dcim.frontport":
        if interface.link_peer.rear_port.link_peer_type == "circuits.circuittermination":
            return interface.link_peer.rear_port.link_peer.circuit

    return None


def get_lag_member(interface):
    """ Returns a member physical interface belonging to a LAG so we can find other side """
    for nb_int in devices[get_device_name(interface.device)]['nb_ints'].values():
        if nb_int.lag is not None and nb_int.lag.name == interface.name:
            return nb_int
    return None


def add_transit_circuit(nb_device, interface, int_addrs, circuit):
    """ Adds device interface to WMF device terminating transit circuit, plus a
        link from it to the 'isp_router' node and an interface there to terminate
        it and simulate the ISP side """

    # Add WMF node interface
    descr = f"{circuit.provider} Transit CCT {circuit.cid}"
    add_device_interface(get_device_name(nb_device), interface.name, int_addrs, descr, nb_device)

    # Add 'isp_router' interface and record WMF peer IP + required ASN
    isp_rtr_int = get_next_eth_int(devices['isp_router'])
    descr = f"Peering to {nb_device.name} {interface.name}"
    isp_rtr_addrs = []
    for nb_ip in int_addrs:
        wmf_ip = ipaddress.ip_interface(str(nb_ip))
        for peer_ip in device_transits[get_device_name(nb_device)].keys():
            if peer_ip in wmf_ip.network:
                isp_rtr_addrs.append(f"{peer_ip}/{wmf_ip.network.prefixlen}")
                local_as = device_transits[get_device_name(nb_device)][peer_ip]['AS']
                if local_as not in devices['isp_router']['bgp_groups']:
                    devices['isp_router']['bgp_groups'][local_as] = {
                        'provider': device_transits[get_device_name(nb_device)][peer_ip]['provider'],
                        'wmf_peers': []
                }
                devices['isp_router']['bgp_groups'][local_as]['wmf_peers'].append(str(wmf_ip.ip))
                break
    add_device_interface('isp_router', isp_rtr_int, isp_rtr_addrs, descr)

    # Add link
    add_link(get_device_name(nb_device), interface.name, 'isp_router', isp_rtr_int)


def add_generic_transport(nb_device, interface, int_addrs):
    """ Adds device interfaces and entry in links{} for a generic L3 p2p link
        Gets far-side details using link IPs """
    far_side_int = get_far_side_from_addr(interface, int_addrs)

    if far_side_int:
        far_side_addrs = list(nb.ipam.ip_addresses.filter(interface_id=far_side_int.id))

        add_device_interface(get_device_name(nb_device), interface.name, int_addrs, interface.description, nb_device)
        add_device_interface(get_device_name(far_side_int.device), far_side_int.name, far_side_addrs,
            far_side_int.description, far_side_int.device)
        add_ordered_link(get_device_name(nb_device), interface, get_device_name(far_side_int.device), far_side_int)
#    else:
#       PNIs, GREs to Cloudflare, L3 link to a third party that's not transit


def get_far_side_from_addr(interface, int_addrs):
    """ Uses IP addrs as the most generic way to get far side, works for directly connected
        ints as well as those via L2VPN, intermediate switch or GRE / tunnel ints. """
    for address in int_addrs:
        subnet_ips = nb.ipam.ip_addresses.filter(parent=str(address.network))
        for subnet_ip in subnet_ips:
            if str(subnet_ip.address) != str(address):
                if subnet_ip.assigned_object:
                    return nb.dcim.interfaces.get(subnet_ip.assigned_object.id)


def get_next_eth_int(device_data):
    """ Returns name for next eth interface on a device """
    eth_ints = [eth_int for eth_int in device_data['phys_ints'].keys() if eth_int.startswith('eth')]
    return f"eth{len(eth_ints) + 1}"


def add_device_interface(device_name, int_name, int_addrs, descr, nb_device=None):
    """ Adds required details for a container interface to internal devices dict.
        Will also add the device itself if it is not already there. """
    # Add device if this is first we've seen it
    if device_name not in devices and nb_device:
        add_device(nb_device)

    if int_name not in devices[device_name]['phys_ints']:
        vlans = []
        access_vlan = 0
        if nb_device:
            # If it's a switch check Vlans needed on the interface
            interface = devices[get_device_name(nb_device)]['nb_ints'][int_name]
            if devices[get_device_name(nb_device)]['sub_type'] == "l2switch" and interface.mode is not None:
                if interface.mode.value == "tagged":
                    vlans = [vlan.vid for vlan in interface.tagged_vlans]
                if interface.untagged_vlan:
                    access_vlan = interface.untagged_vlan.vid

            elif devices[get_device_name(nb_device)]['sub_type'] == "l3switch" and not int_addrs:
                # It's a trunk or access port (i.e. we set allowed vlans) if it has no sub-interfaces
                subints = [sub for sub in devices[get_device_name(nb_device)]['nb_ints'].keys() if sub.startswith(f"{int_name}.")]
                if not subints and interface.mode is not None:
                    if interface.mode.value == "tagged":
                        vlans = [vlan.vid for vlan in interface.tagged_vlans]
                        if interface.untagged_vlan:
                            access_vlan = interface.untagged_vlan.vid
                    elif interface.mode.value == "access":
                        access_vlan = interface.untagged_vlan.vid

        devices[device_name]['phys_ints'][int_name] = {
            "addrs": int_addrs,
            "clab_dev": int_name.replace('/', '_').replace(':', '_'),
            "descr": descr,
            "vlans": vlans,
            "access_vlan": access_vlan
        }


def add_device(nb_device):
    device_name = get_device_name(nb_device)
    
    if device_name not in devices.keys():
        # Defaults
        kind = "crpd"
        sub_type = "cr"

        fqdn = get_dev_fqdn(nb_device)
        # Change for the switch types
        if nb_device.device_role.slug == "cloudsw":
            sub_type = "l3switch"
        elif nb_device.device_role.slug == "asw":
            try:
                if yaml_data['devices'][fqdn]['config']['l3_switch']:
                    sub_type = "l3switch"
            except KeyError as e:
                kind = "linux"
                sub_type = "l2switch"
        elif nb_device.device_role.slug == "server":
            kind = "linux"
            sub_type = "host"

        devices[device_name] = {}
        devices[device_name]['kind'] = kind
        devices[device_name]['sub_type'] = sub_type
        devices[device_name]['fqdn'] = fqdn
        devices[device_name]['phys_ints'] = {}
        devices[device_name]['subints'] = {}
        devices[device_name]['irb_ints'] = {}

        # Get device interfaces, add to device object keyed by int name
        devices[device_name]['nb_ints'] = {}
        if nb_device.virtual_chassis:
            # If it's VC we pull list of ints from the master device always
            nb_ints = nb.dcim.interfaces.filter(device_id=nb_device.virtual_chassis.master.id, enabled="true")
        else:
            nb_ints = nb.dcim.interfaces.filter(device_id=nb_device.id, enabled="true")
        for interface in nb_ints:
            devices[device_name]['nb_ints'][interface.name] = interface


def get_dev_fqdn(nb_device):
    if nb_device.virtual_chassis:
        return nb_device.virtual_chassis.name
    if nb_device.primary_ip4 is not None and nb_device.primary_ip4.dns_name:
        return nb_device.primary_ip4.dns_name
    elif nb_device.primary_ip6 is not None and nb_device.primary_ip6.dns_name:
        return nb_device.primary_ip6.dns_name
    else:
        return None


def add_ordered_link(router1, int1, router2, int2, descr=""):
    """ Pass router 'A' and 'B' based on lowest Netbox interface ID.  This ensures
        if we try to add a link a second time (parsing far-side router) the details
        are the same and we avoid duplication. """

    try:
        if int1.id < int2.id:
            add_link(router1, int1.name, router2, int2.name, descr)
        else:
            add_link(router2, int2.name, router1, int1.name, descr)
    except:
        print(f"    {router1} {int1} {type(int1)}")
        print(f"    {router2} {int2} {type(int2)}")


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


def get_far_side_dev(phys_int, device):
    """ Return device object connected to phys_int """
    far_side_int = get_link_far_side(phys_int)
    if far_side_int:
        return far_side_int, far_side_int.device
    else:
        return None, None


def get_link_far_side(interface):
    """ Gets far side interface when passed interface object. """
    if interface.type.value == "lag":
        lag_member = get_lag_member(interface)
        if lag_member.connected_endpoint_type == "dcim.interface":
            phys_int_b = nb.dcim.interfaces.get(lag_member.connected_endpoint.id)
            return nb.dcim.interfaces.get(phys_int_b.lag.id)
        else:
            # Usually parent int of peering cct like AMS-IX
            return
    else:
        # No LAG, nice and simple
        try:
            return nb.dcim.interfaces.get(interface.connected_endpoint.id)
        except AttributeError as e:
            pass
            #print(e)
            #print(f"ATTR ERROR 413: {interface.device.name} - {interface.name}")


if __name__=="__main__":
    main()

