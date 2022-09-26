#!/usr/bin/python3

import json
import yaml

def main():
    with open('lvs_vips.json', 'r') as json_file:
        data = json.loads(json_file.read())


    out_data = {}
    for lvs_fqdn, lvs_json_str in data.items():
        lvs_name = lvs_fqdn.split('.')[0]
        out_data[lvs_name] = {
            'fqdn': lvs_fqdn,
            'site': lvs_fqdn.split('.')[1],
            'vips': []
        }

        vips = json.loads(lvs_json_str)
        for vip in vips:
            if len(vip) > 0:
                for addr in vip['addr_info']:
                    if addr['scope'] == 'global':
                        out_data[lvs_name]['vips'].append(f"{addr['local']}/{addr['prefixlen']}")

    with open('lvs_vips.yaml', 'w') as out_file:
        yaml.dump(out_data, out_file)


if __name__ == '__main__':
    main()

