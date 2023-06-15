from pathlib import Path
import os
import yaml
import ipaddress

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

    yaml_data = {}
    # Load data from YAML files so it's available to us
    with open('operations-homer-public/config/devices.yaml', 'r') as yaml_file:
        yaml_data['devices'] = yaml.safe_load(yaml_file)
    with open('operations-homer-public/config/common.yaml', 'r') as yaml_file:
        yaml_data['common'] = yaml.safe_load(yaml_file)
    with open('operations-homer-public/config/sites.yaml', 'r') as yaml_file:
        yaml_data['sites'] = yaml.safe_load(yaml_file)
    with open('operations-homer-public/config/roles.yaml', 'r') as yaml_file:
        yaml_data['roles'] = yaml.safe_load(yaml_file)

    return yaml_data


def clone_homer_repo():
    if Path('operations-homer-public').is_dir():
        print("Deleting existing homer public repo directory...")
        os.system("rm -Rf operations-homer-public")

    if Path('operations-homer-mock-private').is_dir():
        print("Deleting existing homer mock private repo directory...\n")
        os.system("rm -Rf operations-homer-mock-private")

    # Not verifying TLS as running on a machine with incorrect time to fool crpd license
    os.system("git -c http.sslVerify=false clone --depth 1 https://github.com/wikimedia/operations-homer-public")
    print()
    os.system("git -c http.sslVerify=false clone --depth 1 https://github.com/wikimedia/operations-homer-mock-private")
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


def get_device_transits(yaml_data):
    """ Parses devices.yaml and extracts transit peer data for each device """
    device_transits = {}
    for device_name, device_vars in yaml_data['devices'].items():
        if "config" in device_vars.keys():
            if "transits" in device_vars['config'].keys():
                short_name = device_name.split(".")[0]
                device_transits[short_name] = {}
                for peer_ip_str, peer_vars in device_vars['config']['transits'].items():
                    peer_ip = ipaddress.ip_address(peer_ip_str)
                    device_transits[short_name][peer_ip] = {}
                    device_transits[short_name][peer_ip]['provider'] = peer_vars['provider']
                    device_transits[short_name][peer_ip]['AS'] = \
                        yaml_data['common']['transit_providers'][peer_vars['provider']]['AS']

    return device_transits
