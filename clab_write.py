from pathlib import Path
import yaml
import json
import os
import ipaddress

def write_files(parser_args, device_info, link_info, parsed_yaml_data):
    global args, devices, links, yaml_data, dummy_routes

    # Load list of random routes we announce from fake isp router node
    with open('dummy_routes.yaml', 'r') as yaml_file:
        dummy_routes = yaml.safe_load(yaml_file)

    args = parser_args
    devices = device_info
    links = link_info
    yaml_data = parsed_yaml_data

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
            "network": "wmf_clab",
            "bridge": "wmf_clab",
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
                # Below needed to load license for cRPD v22 - but we need to fake date if expired
                #out_data['topology']['nodes'][device_name]['binds'].append(
                #    f"{args.license}:/tmp/crpd.lic")
                #out_data['topology']['nodes'][device_name]['exec'] = [
                #    "cli -c \"request system license add /tmp/crpd.lic\""
                #]
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
    # Added below as Netlink reports not being able to set IPv6 addr for some ints without
    # Expect it's just happening too quick after container/netns/netdev init as running 
    # command manually just after works fine.
    out_file.write("sleep 5\n\n")
    dns_resolvers = get_dns_resolvers()

    for device_name, device_vars in devices.items():
        # Disable proxy arp cos it's evil
        out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                        f"sysctl -w net.ipv4.conf.all.arp_ignore=2\n")

        if "loop_addrs" in device_vars.keys():
            for address in device_vars['loop_addrs']:
                out_file.write("sudo ip netns exec clab-{}-{} ip addr add {} dev lo\n".format(
                    args.name, device_name, address))

        out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip route del default via 172.20.20.1\n")
        out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip -6 route del default via 2001:172:20:20::1\n")

        for resolver in dns_resolvers:
            # Should be changed to detect v4/v6 IP and use appropriate next-hop, also discover GW IP and not assume default
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip route add {resolver} via 172.20.20.1\n")

        if device_vars['sub_type'] == "l2switch" or device_vars['sub_type'] == "l3switch":
            # This container should have a vlan-aware bridge created, which we'll attach all physicals to
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                            "ip link add irb type bridge vlan_filtering 1 vlan_protocol 802.1Q " \
                            "vlan_stats_enabled 1 vlan_stats_per_port 1\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip link set dev irb mtu 9212\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip link set dev irb up\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                                f"bridge vlan del dev irb vid 1 self\n")
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} ip addr flush dev irb\n\n")

        for int_name, int_vars in device_vars['phys_ints'].items():
            out_file.write("sudo ip netns exec clab-{}-{} ip link set alias \"{}\" dev {}\n".format(
                args.name, device_name, int_name, int_vars['clab_dev']))

            if int_vars['vlans']:
                # L2 trunk, so set port master to the 'irb' bridge and set vlans
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                               f"ip link set dev {int_vars['clab_dev']} master irb\n")
                # Vlan 1 defaults to native VLAN.  Delete to block untagged frames.
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                               f"bridge vlan del dev {int_vars['clab_dev']} vid 1\n")
                for vlan in int_vars['vlans']:
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                                   f"bridge vlan add dev {int_vars['clab_dev']} vid {vlan}\n")

            # If access vlan is set and not default value 0 (indicating none)
            if "access_vlan" in int_vars and int_vars['access_vlan']:
                if not int_vars['vlans']:
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                                   f"ip link set dev {int_vars['clab_dev']} master irb\n")
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                                   f"bridge vlan del dev {int_vars['clab_dev']} vid 1\n")
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                               f"bridge vlan add dev {int_vars['clab_dev']} vid {int_vars['access_vlan']} " \
                               f"pvid untagged\n")

            if int_vars['addrs']:
                for address in int_vars['addrs']:
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " 
                                   f"ip addr add {address} dev {int_vars['clab_dev']}\n")

                    if device_vars['sub_type'] == "host":
                        # Add default route towards the first IP in the subnet
                        ip_int = ipaddress.ip_interface(address)
                        out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} "
                                       f"ip route add default via {ip_int.network[1]}\n")

            else:
                # No unicast address - best to delete v6 link local too.
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} "
                               f"ip addr flush dev {int_vars['clab_dev']}\n")

        for subint_name, subint_vars in device_vars['subints'].items():
            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} "
                           f"ip link add link {subint_vars['clab_dev']} name {subint_vars['subint_dev']} "
                           f"type vlan id {subint_vars['vlan_id']}\n")

            for address in subint_vars['addrs']:
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} "
                               f"ip addr add {address} dev {subint_vars['subint_dev']}\n")

            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} "            
                           f"ip link set dev {subint_vars['subint_dev']} up\n")

            out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} "
                           f"ip link set alias {subint_vars['clab_dev']}.{subint_vars['vlan_id']} "
                           f"dev {subint_vars['subint_dev']}\n")

        if "irb_ints" in device_vars:
            # IRB interfaces are modelled as vlan sub-interfaces of the 'irb' master bridge.
            # We add them with the correct 802.1q tag, then allow that tag on the master dev itself
            for irb_name, irb_addrs in device_vars['irb_ints'].items():
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                    f"ip link add link irb name {irb_name} type vlan id {irb_name.split('.')[1]}\n")
                for address in irb_addrs:
                    out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                        f"ip addr add {address} dev {irb_name}\n")
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                    f"ip link set dev {irb_name} up\n")
                out_file.write(f"sudo ip netns exec clab-{args.name}-{device_name} " \
                    f"bridge vlan add dev irb vid {irb_name.split('.')[1]} self\n")


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


