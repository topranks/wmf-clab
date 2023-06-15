#!/usr/bin/python3

import yaml
import os

def main():
    """ Adds FQDNs for clab devices to /etc/hosts"""

    fqdn_file = open('fqdn.yaml', 'r')
    fqdn_map = yaml.safe_load(fqdn_file)
    fqdn_file.close()

    new_file = open('/tmp/new_hosts', 'w')

    with open('/etc/hosts', 'r') as hostsfile:
        for line in hostsfile.readlines():
            line_strip = line.rstrip('\n')
            if "clab-wmf-clab-" in line:
                device = line.split()[-1].replace('clab-wmf-clab-', '')
                if device in fqdn_map:
                    new_file.write(f"{line_strip}\t{fqdn_map[device]}\t{device}\n")
                else:
                    new_file.write(f"{line_strip}\t{device}\n")
            else:
                new_file.write(line)

    new_file.close()

    os.system('rm -vf /etc/hosts && mv -v /tmp/new_hosts /etc/hosts')


if __name__=="__main__":
    main()
