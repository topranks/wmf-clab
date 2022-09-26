1. Get VIPs using cumin:

sudo cumin -o json --force 'A:lvs' 'ip -json addr show lo' | tee lvs_vips.json

2. Transfer the JSON output to local machine, remove the first (non-json) lines, then generate output YAML with this script

