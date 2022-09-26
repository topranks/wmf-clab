# wmf-lab

![wmf-lab topology](https://github.com/topranks/wmf-lab/blob/main/clab_wmf-lab.png)

Script to create a topology file for [containerlab](https://containerlab.srlinux.dev/) to simulate the WMF network (see this [presentation](https://www.youtube.com/watch?v=n81Tc1g4W5U) for an intro.)

The script uses WMF Netbox, and homer public repo YAML files, to collect information on devices running on the WMF network and create a topology to simulate them using docker/containerlab, with Juniper's [crpd](https://www.juniper.net/documentation/us/en/software/crpd/crpd-deployment/topics/concept/understanding-crpd.html) container image as router nodes.

As crpd is a lightweight container it requires significantly less resources than VM-based appliances such as vMX.  This means it is possible to simulate many virtual nodes on even modest hardware.

Two additional scripts are included, one which can run on a device with keys that can connect to produciton routers, and gathers config and operational state from the live network, dumping it to JSON files.  The other companion script can be used to push this config to the containerlab instances, filling in the gaps for elements that are confgiured manually in the current infra.  Some other basic tooling is included to gather LVS service IPs from production so they can be announced to the simulated network elements.

## Approach 

### Juniper cRPD - Containerised Routing Protocol Daemon

Juniper's crpd is basically just their routing-stack software (i.e. OSPF, BGP, IS-IS implementation) deployed in a container.  Unlike virtual-machine based platforms such as [vMX](https://www.juniper.net/us/en/products/routers/mx-series/vmx-virtual-router-software.html), it does not implement any dataplane funcationality.  Instead it runs the various protocols and builds the per-protocol and global RIB, and then uses the normal Linux [netlink](https://en.wikipedia.org/wiki/Netlink) interface to program routes into the Linux network namespace of the crpd container.  

This means that, while the OSPF, BGP and other protocol implemenations should operate exactly as on a real Juniper router, packet encapsulation and forwarding is being performed by Linux.  As such crpd is only 100% valid to test some things (such as changes to OSPF metrics) but not others (like how MPLS label stacks or Vlan tags are added to packets).

### Lab Overview

At a high level the approach to building the lab is as follows:

1. Run the ```gen_topo.py``` script, which will:
    1. Connect to WMF Netbox and discover all core routers, links and circuits between them.
    2. Generate a containerlab topology file in YAML to match the discovered topology.
    3. Write a startup bash script which will:
        1. Initialise the lab with the clab command, creating containers and links
        2. Add IP addresses to the newly created container interfaces
        3. Add virtual interfaces (bridges, 802.1q sub-interfaces) to containers as needed
        4. Set the correct allowed Vlans on interfaces terminating on bridge devices (simulating L2 switches)
        5. Add entries to /etc/hosts to point device FQDN hostnames at local clab management IPs
    4. Clone the [homer public repo](https://github.com/wikimedia/operations-homer-public) and apply the following modifications
        1. Remove Capirca keys from device and role YAML files (cRPD does not support JunOS firewall conf)
        2. Remove prefix lists which use 'apply-groups' for elements cRPD cannot model (system-ntp list etc)
        3. Replace certain top-level Jinja2 templates (such as 'cr.conf') with versions which only include config sections cRPD supports.
2. Gather additional data not available in Netbox/Homer repo
    1. Run the ```junos_get_live_conf.py``` script on a device which has access to production routers, and transfer the JSON files it saves to the 'wmf-lab' directory on the machine running the lab.
    2. Save LVS service IPs using the script/instructions in the ```lvs_getvips``` directory of this repo
3. Initialise the lab by running ```start_wmf-lab.sh``` from the 'output' directory
    * This initialises the lab and performs the actions described above in 1.3 
5. Run homer against the newly-created container devices to apply Juniper configuration
    * ```homer "cr*" commit "Apply config to clab nodes."```
6. Run the ```junos_push_saved_data.py``` script to disable BGP groups not needed, and add additional config from production devices saved in step 2.1.


## Integration with containerlab

### Interface Addressing

Containerlab supports crpd natively, however it provides no mechanism to configure IP addresses on the veth interfaces that exist within each containerized node.  For most of the containerized network nodes it supports this is not an issue - most allow configuration of interface addresses through their CLI, Netconf etc.  That is not true with crpd, however.  Instead crpd expects to run on a Linux host / container with all interface IPs already configured, and allows you to enable OSPF, BGP etc. which will run over those interfaces.

To overcome this the "start" shell script uses the Linux [ip](https://manpages.debian.org/bullseye/iproute2/ip-route.8.en.html) command to add interface IPs as required once the containers have been created by clab.

### Interface Naming

Real Juniper devices operated by WMF use standard JunOS interface naming such as 'ge-0/0/0', 'et-5/0/1' etc.  Linux does not, unfortunately, allow a forward slash in a network device name, so we cannot give the crpd interfaces exactly matching those on production routers.  So in the lab interfaces are named with underscores replacing forward slashes.

### Modelling switches

WMF routers commonly have connections to layer-2 switches, typically with multiple 802.1q sub-interfaces on each link connecting to a different Vlan on the switch.  Many of these are configured as OSPF 'passive' interfaces, or have BGP configured on them to servers (such as load-balancers).

To model L2 switches containerlab nodes are added of kind 'linux', set to run a standard Debian-based container image.  Each of these has a vlan-aware bridge added to them by the startup script, called 'br0'.  All link interfaces terminating on these nodes are bound to the br0 device, and set to either 'access' or 'trunk' mode with the correct Vlan's allowed on each.  This effectively connects nodes at layer-2 similar to our L2 switches, but using Linux bridge to do so rather than any Juniper-coded forwarding.

Sub-interfaces on ports connecting to these bridges, within the crpd containers, are also created by the start script.  Containerlab does not provide a mechanism to add these itself.  The addresses for these sub-ints are added by the start script during deploy.

## Running the script to generate topology / config files.

Most typically I run the lab in a Debian VM on my system, to keep it all isolated.  It should be possible to run on any Linux system with Python3 and docker, however.  It is advised to run on a system with minimum 8GB RAM, and preferably 12GB+, to allow each container to run comfortably.  4 vCPUs is reccomended but it should work with 2 or less.

The clab binary and start script need to be run as root to create containers and network devices.  When running in a VM I tend to execute all the below from a root shell to keep things simple.

### Install Dependencies

Python3, [Pynetbox](https://github.com/netbox-community/pynetbox), Juniper's [PyEz library](https://www.juniper.net/documentation/us/en/software/junos-pyez/junos-pyez-developer/topics/concept/junos-pyez-overview.html), WMF's [Homer](https://doc.wikimedia.org/homer/master/introduction.html#homer-configuration-manager-for-network-devices) and [Docker](https://www.docker.com/) are required to generate the topology and run the lab. 

First install pip:
```
sudo apt install python3-pip
```

Then the Python components:
```
pip3 install pynetbox junos-eznc homer
```

Next install docker following their [instructions](https://docs.docker.com/engine/install/debian/).

Once installed we should import the crpd container image.  Copy the tar.gz file over to the system with scp or similar, then add it to the docker system:

```
docker load -i junos-routing-crpd-docker-19.4R1.10.tgz
```

To verify it loaded run "docker images", and take note of the 'image id' that's been assigned to the new image
```
root@debiantest:/home/debian# docker images
REPOSITORY                     TAG         IMAGE ID       CREATED       SIZE
hub.juniper.net/routing/crpd   19.4R1.10   5b6acdd96efb   2 years ago   320MB
```

Then tag it as 'crpd:latest' (the name the containerlab topolofy file will look for):
```
docker tag 5b6acdd96efb crpd:latest
```

We also want to install a debain container image from docker hub which will be used to simulate L2 switches
```
root@debiantest:~# docker pull debian
Using default tag: latest
latest: Pulling from library/debian
23858da423a6: Pull complete 
Digest: sha256:3e82b1af33607aebaeb3641b75d6e80fd28d36e17993ef13708e9493e30e8ff9
Status: Downloaded newer image for debian:latest
docker.io/library/debian:latest
```

You can verify the images have been sucessfully imported with "docker images":
```
root@debiantest:/home/debian# docker images
REPOSITORY                     TAG         IMAGE ID       CREATED       SIZE
debian                         latest      43d28810c1b4   13 days ago   124MB
crpd                           latest      5b6acdd96efb   2 years ago   320MB
hub.juniper.net/routing/crpd   19.4R1.10   5b6acdd96efb   2 years ago   320MB
```

Finally we add the containerlab repo to our system and install it:
```
echo "deb [trusted=yes] https://apt.fury.io/netdevops/ /" | \
sudo tee -a /etc/apt/sources.list.d/netdevops.list

sudo apt update
sudo apt install containerlab
```

### Generate an SSH keypair to allow passwordless ssh to the containers

The script will link ```~/.ssh/id_ed25519.pub``` to /root/.ssh/authorized_keys within the container images to allow SSH without password (required for Homer and the other scripts using the JunOS Netconf connection).  If you do not have an ED25519 keypair already generate one as follows:
```
ssh-keygen -t ed25519
```

The JunOS PyEz library needs to be passed an SSH config file, which explicity specifies the SSH public key to use when connecting.  By default the scripts in this repo will attempt to use '~/.ssh/config' for this.  So create this file if not present, with contents as follows:
```
Host *
    IdentityFile /root/.ssh/id_ed25519
```

### Clone this repo and run the script to generate the lab topology:

Clone this repo as follows:
```
git clone --depth 1 https://github.com/topranks/wmf-lab.git
```
You can then change to the 'wmf-lab' directory and run the "gen_topo.py" script, it will ask for an API key to connect to the WMF Netbox server and begin building the topology.  If you have a license file to run crpd the path can be provided with the '-l' option, which will add the license parameter for crpd nodes in the containerlab topology.  The lab will run without a license file, but it is needed for BGP, so it's limited use without.
```
cmooney@wikilap:~/wmf-lab$ ./gen_topo.py -l ~/wmf-lab/crpd.lic
Netbox API Key: 
Addding cr1-codfw...
Addding cr1-drmrs...
Addding cr1-eqiad...
Addding cr1-eqsin...
Addding cr1-ulsfo...
Addding cr2-codfw...
Addding cr2-drmrs...
Addding cr2-eqdfw...
Addding cr2-eqiad...
Addding cr2-eqord...
Addding cr2-eqsin...
Addding cr2-esams...
Addding cr2-knams...
Addding cr2-ulsfo...
Addding cr3-eqsin...
Addding cr3-esams...
Addding cr3-knams...
Addding cr3-ulsfo...
Addding cr4-ulsfo...

Deleting existing homer public repo directory...
Cloning homer public repo to operations-homer-public...
Cloning into 'operations-homer-public'...
remote: Enumerating objects: 130, done.
remote: Counting objects: 100% (130/130), done.
remote: Compressing objects: 100% (106/106), done.
remote: Total 130 (delta 34), reused 96 (delta 15), pack-reused 0
Receiving objects: 100% (130/130), 64.33 KiB | 1.61 MiB/s, done.
Resolving deltas: 100% (34/34), done.
Removing capirca defs from operations-homer-public/config/devices.yaml...
Removing capirca defs from operations-homer-public/config/roles.yaml...
removed 'operations-homer-public/templates/includes/policies/common-prefix-lists.conf'
renamed '/tmp/new_file' -> 'operations-homer-public/templates/includes/policies/common-prefix-lists.conf'
removed 'operations-homer-public/templates/cr/policy-options.conf'
renamed '/tmp/new_file' -> 'operations-homer-public/templates/cr/policy-options.conf'

Adding LVS devices...
Building clab topology...
Writing clab topology file wmf-lab.yaml...
Writing start_wmf-lab.sh...
Writing stop_wmf-lab.sh...
Writing fqdn.yaml...
```

NOTE:  The script takes quite a while to run.  This is due to my poor coding and the very slow Netbox REST API.  I hope to get time to work on optimizing it in the near future, potentially using Netbox's GraphQL API, or at least focusing on removing the number of API calls (which wasn't high on the agenda during development).  Luckily the topology does not need to be re-generated very frequently, so the script only needs to run occasionally (like when new transport links are added).
    
When complete you should find a new sub-folder has been created, called "output", containing the start and stop scripts, as well as the containerlab topology file.
```
cmooney@wikilap:~/wmf-lab$ ls -lah output/
total 84K
drwxrwxr-x 3 cmooney cmooney 4.0K Aug 17 16:49 .
drwxrwxr-x 5 cmooney cmooney 4.0K Aug 17 16:49 ..
-rwxr-xr-x 1 cmooney cmooney  57K Aug 17 16:49 start_wmf-lab.sh
-rwxr-xr-x 1 cmooney cmooney  948 Aug 17 16:49 stop_wmf-lab.sh
-rw-rw-r-- 1 cmooney cmooney 6.2K Aug 17 16:49 wmf-lab.yaml
```

The script also clones the Homer public repo into the current directory, and modifies / replaces some template files within it to make them compatible with crpd.

## Running the lab

### Start script

The start script needs to be run with root priviledges as it adds Linux netdevs to the various container namespaces and configures IP addresses:
```
sudo ./start_wmf-lab.sh
```

<details>
  <summary>Example output - click to expand</summary>
  
```
root@debiantest:~/wmf-lab/output# ./start_wmf-lab.sh 
+ sudo clab deploy -t wmf-lab.yaml
INFO[0000] Containerlab v0.32.0 started                 
INFO[0000] Parsing & checking topology file: wmf-lab.yaml 
INFO[0000] Creating lab directory: /root/wmf-lab/output/clab-wmf-lab 
INFO[0000] Creating docker network: Name="wmf_lab", IPv4Subnet="172.20.20.0/24", IPv6Subnet="2001:172:20:20::/64", MTU="1500" 
INFO[0000] Creating container: "asw2-ulsfo"             
INFO[0000] Creating container: "asw-d-codfw"            
INFO[0000] Creating container: "asw-c-codfw"            
INFO[0000] Creating container: "asw2-d-eqiad"           
INFO[0000] Creating container: "asw2-b-eqiad"           
INFO[0000] Creating container: "asw-b-codfw"            
INFO[0000] Creating container: "cloudsw1-d5-eqiad"      
INFO[0000] Creating container: "asw-a-codfw"            
INFO[0000] Creating container: "asw2-a-eqiad"           
INFO[0000] Creating container: "asw1-eqsin"             
INFO[0000] Creating container: "asw2-c-eqiad"           
INFO[0000] Creating container: "cloudsw1-c8-eqiad"      
INFO[0000] Creating container: "asw2-esams"             
INFO[0000] Creating container: "cr1-eqiad"              
INFO[0000] Creating container: "cr1-drmrs"              
INFO[0000] Creating container: "lvs3005"                
INFO[0000] Creating container: "lvs2008"                
INFO[0000] Creating container: "cr2-codfw"              
INFO[0000] Creating container: "mr1-codfw"              
INFO[0000] Creating container: "cr3-knams"              
INFO[0000] Creating container: "lvs5002"                
INFO[0000] Creating container: "lvs4007"                
INFO[0000] Creating container: "cr2-eqdfw"              
INFO[0000] Creating container: "asw1-b13-drmrs"         
INFO[0000] Creating container: "lsw1-e1-eqiad"          
INFO[0000] Creating container: "mr1-eqsin"              
INFO[0000] Creating container: "cr2-eqord"              
INFO[0000] Creating container: "cr3-eqsin"              
INFO[0000] Creating container: "mr1-eqiad"              
INFO[0000] Creating container: "pfw3b-codfw"            
INFO[0000] Creating container: "lvs5001"                
INFO[0000] Creating container: "lvs3007"                
INFO[0000] Creating container: "pfw3a-eqiad"            
INFO[0000] Creating container: "lvs1020"                
INFO[0000] Creating container: "pfw3a-codfw"            
INFO[0000] Creating container: "cr4-ulsfo"              
INFO[0000] Creating container: "cr2-esams"              
INFO[0000] Creating container: "cr2-eqsin"              
INFO[0000] Creating container: "asw1-b12-drmrs"         
INFO[0000] Creating container: "cr2-drmrs"              
INFO[0000] Creating container: "cr2-eqiad"              
INFO[0000] Creating container: "cr3-esams"              
INFO[0000] Creating container: "cr3-ulsfo"              
INFO[0000] Creating container: "lvs4006"                
INFO[0000] Creating container: "lsw1-f1-eqiad"          
INFO[0000] Creating container: "lvs2010"                
INFO[0000] Creating container: "mr1-esams"              
INFO[0000] Creating container: "lvs1018"                
INFO[0000] Creating container: "cr1-codfw"              
INFO[0000] Creating container: "lvs1019"                
INFO[0000] Creating container: "mr1-ulsfo"              
INFO[0000] Creating container: "pfw3b-eqiad"            
INFO[0000] Creating container: "lvs4005"                
INFO[0000] Creating container: "lvs2009"                
INFO[0000] Creating container: "lvs2007"                
INFO[0000] Creating container: "lvs5003"                
INFO[0000] Creating container: "lvs1017"                
INFO[0000] Creating container: "lvs3006"                
INFO[0007] Creating virtual wire: asw2-d-eqiad:eth1 <--> lvs1020:eth1 
INFO[0007] Creating virtual wire: asw1-eqsin:ae1 <--> cr3-eqsin:ae1 
INFO[0007] Creating virtual wire: cr3-eqsin:ae1.401 <--> mr1-eqsin:ge-0_0_4.401 
INFO[0008] Creating virtual wire: asw-d-codfw:eth1 <--> lvs2010:eth1 
INFO[0008] Creating virtual wire: asw-a-codfw:eth1 <--> lvs2007:eth1 
INFO[0009] Creating virtual wire: cr3-ulsfo:et-0_0_1 <--> asw2-ulsfo:et-1_0_24 
INFO[0010] Creating virtual wire: asw2-ulsfo:eth1 <--> lvs4005:eth1 
INFO[0010] Creating virtual wire: cr2-eqsin:ae1.402 <--> mr1-eqsin:ge-0_0_4.402 
INFO[0010] Creating virtual wire: cr2-eqsin:ae0 <--> cr3-eqsin:ae0 
INFO[0010] Creating virtual wire: asw1-eqsin:ae2 <--> cr2-eqsin:ae1 
INFO[0010] Creating virtual wire: asw2-ulsfo:eth3 <--> lvs4007:eth1 
INFO[0010] Creating virtual wire: asw2-esams:ae2 <--> cr2-esams:ae1 
INFO[0011] Creating virtual wire: cr1-drmrs:et-0_0_2 <--> asw1-b13-drmrs:et-0_0_50 
INFO[0012] Creating virtual wire: cr1-codfw:xe-1_0_1_2 <--> cr3-eqsin:xe-0_1_0 
INFO[0012] Creating virtual wire: cr1-codfw:ae2 <--> asw-b-codfw:ae1 
INFO[0012] Creating virtual wire: cr1-codfw:ae4 <--> asw-d-codfw:ae1 
INFO[0012] Creating virtual wire: cr1-codfw:xe-1_0_1_3 <--> pfw3a-codfw:xe-0_0_16 
INFO[0012] Creating virtual wire: cr1-codfw:ae1 <--> asw-a-codfw:ae1 
INFO[0012] Creating virtual wire: cr1-codfw:ae3 <--> asw-c-codfw:ae1 
INFO[0013] Creating virtual wire: cr3-knams:ae1.403 <--> cr2-esams:ae1.403 
INFO[0013] Creating virtual wire: cr3-knams:ae1.401 <--> cr3-esams:ae1.401 
INFO[0013] Creating virtual wire: asw2-esams:ae3 <--> cr3-esams:ae1 
INFO[0013] Creating virtual wire: cr3-esams:ae0 <--> cr2-esams:ae0 
INFO[0013] Creating virtual wire: cr3-esams:xe-0_0_1 <--> cr2-drmrs:xe-0_1_3 
INFO[0013] Creating virtual wire: cr1-drmrs:et-0_0_0 <--> cr2-drmrs:et-0_0_0 
INFO[0013] Creating virtual wire: cr2-drmrs:et-0_0_1 <--> asw1-b13-drmrs:et-0_0_48 
INFO[0013] Creating virtual wire: asw2-ulsfo:eth2 <--> lvs4006:eth1 
INFO[0013] Creating virtual wire: asw-b-codfw:eth1 <--> lvs2008:eth1 
INFO[0014] Creating virtual wire: asw1-eqsin:eth3 <--> lvs5003:eth1 
INFO[0014] Creating virtual wire: asw2-a-eqiad:eth1 <--> lvs1017:eth1 
INFO[0014] Creating virtual wire: cr2-eqdfw:xe-0_1_0 <--> cr1-codfw:xe-1_1_1_2 
INFO[0014] Creating virtual wire: cr2-eqdfw:xe-0_1_3.26 <--> cr2-drmrs:xe-0_1_1.26 
INFO[0014] Creating virtual wire: cr2-eqdfw:xe-0_1_3.23 <--> cr3-knams:xe-0_1_5.23 
INFO[0014] Creating virtual wire: asw-c-codfw:eth1 <--> lvs2009:eth1 
INFO[0015] Creating virtual wire: asw2-b-eqiad:eth1 <--> lvs1018:eth1 
INFO[0015] Creating virtual wire: cr1-eqiad:xe-3_1_7 <--> pfw3a-eqiad:xe-0_0_16 
INFO[0015] Creating virtual wire: cr1-eqiad:ae3 <--> asw2-c-eqiad:ae1 
INFO[0015] Creating virtual wire: cr3-knams:xe-0_1_5.13 <--> cr1-eqiad:xe-4_2_2.13 
INFO[0015] Creating virtual wire: cr2-eqdfw:xe-0_1_3.12 <--> cr1-eqiad:xe-4_2_2.12 
INFO[0015] Creating virtual wire: cr1-eqiad:ae1 <--> asw2-a-eqiad:ae1 
INFO[0015] Creating virtual wire: cr1-codfw:xe-1_1_1_3 <--> cr1-eqiad:xe-4_2_0 
INFO[0015] Creating virtual wire: cr1-eqiad:ae2 <--> asw2-b-eqiad:ae1 
INFO[0015] Creating virtual wire: cr1-eqiad:xe-3_1_4 <--> cr1-drmrs:xe-0_1_2 
INFO[0015] Creating virtual wire: cr1-eqiad:gr-4_3_0.1 <--> cr2-eqsin:gr-0_1_0.1 
INFO[0015] Creating virtual wire: cr2-drmrs:xe-0_1_1.16 <--> cr1-eqiad:xe-4_2_2.16 
INFO[0015] Creating virtual wire: asw2-esams:eth2 <--> lvs3006:eth1 
INFO[0015] Creating virtual wire: cr1-eqiad:xe-3_0_4 <--> cloudsw1-c8-eqiad:xe-0_0_0 
INFO[0015] Creating virtual wire: cr1-eqiad:ae4 <--> asw2-d-eqiad:ae1 
INFO[0016] Creating virtual wire: mr1-ulsfo:ge-0_0_4.401 <--> cr3-ulsfo:et-0_0_1.401 
INFO[0017] Creating virtual wire: asw2-esams:eth1 <--> lvs3005:eth1 
INFO[0017] Creating virtual wire: cr3-ulsfo:xe-0_1_1 <--> cr2-eqord:xe-0_1_3 
INFO[0017] Creating virtual wire: cr4-ulsfo:gr-0_0_0.2 <--> cr2-eqdfw:gr-0_0_0.1 
INFO[0017] Creating virtual wire: cr4-ulsfo:xe-0_1_2 <--> cr2-eqsin:xe-0_1_4 
INFO[0017] Creating virtual wire: cr4-ulsfo:et-0_0_1 <--> asw2-ulsfo:et-2_0_24 
INFO[0017] Creating virtual wire: cr4-ulsfo:xe-0_1_1 <--> cr1-codfw:xe-1_1_1_0 
INFO[0017] Creating virtual wire: cr3-ulsfo:et-0_0_1.501 <--> cr4-ulsfo:et-0_0_1.501 
INFO[0017] Creating virtual wire: cr3-ulsfo:ae0.2 <--> cr4-ulsfo:ae0.2 
INFO[0017] Creating virtual wire: mr1-ulsfo:ge-0_0_4.402 <--> cr4-ulsfo:et-0_0_1.402 
INFO[0017] Creating virtual wire: cr1-codfw:ae1.401 <--> mr1-codfw:ge-0_0_1.401 
INFO[0017] Creating virtual wire: cr2-eqiad:ae4 <--> asw2-d-eqiad:ae2 
INFO[0017] Creating virtual wire: cr2-eqiad:xe-3_0_4 <--> cloudsw1-d5-eqiad:xe-0_0_0 
INFO[0017] Creating virtual wire: cr2-eqiad:xe-3_1_7 <--> pfw3b-eqiad:xe-7_0_16 
INFO[0017] Creating virtual wire: cr2-eqiad:ae2 <--> asw2-b-eqiad:ae2 
INFO[0017] Creating virtual wire: cr2-eqiad:ae1 <--> asw2-a-eqiad:ae2 
INFO[0017] Creating virtual wire: cr2-eqord:xe-0_1_5 <--> cr2-eqiad:xe-4_2_0 
INFO[0017] Creating virtual wire: cr2-eqiad:ae3 <--> asw2-c-eqiad:ae2 
INFO[0017] Creating virtual wire: cr1-eqiad:xe-3_0_6 <--> cr2-eqiad:xe-3_3_3 
INFO[0017] Creating virtual wire: cr2-eqiad:ae0 <--> cr1-eqiad:ae0 
INFO[0017] Creating virtual wire: cr2-esams:xe-0_1_3 <--> cr2-eqiad:xe-4_1_3 
INFO[0017] Creating virtual wire: lsw1-f1-eqiad:et-0_0_48.100 <--> cr2-eqiad:et-1_0_2.100 
INFO[0017] Creating virtual wire: cr3-esams:gr-0_0_0.1 <--> cr2-eqiad:gr-4_3_0.1 
INFO[0017] Creating virtual wire: mr1-eqiad:ge-0_0_1.402 <--> cr2-eqiad:ae1.402 
INFO[0017] Creating virtual wire: mr1-eqiad:ge-0_0_1.401 <--> cr1-eqiad:ae1.401 
INFO[0018] Creating virtual wire: cr2-drmrs:et-0_0_2 <--> asw1-b12-drmrs:et-0_0_50 
INFO[0018] Creating virtual wire: cr1-drmrs:et-0_0_1 <--> asw1-b12-drmrs:et-0_0_48 
INFO[0019] Creating virtual wire: asw1-eqsin:eth1 <--> lvs5001:eth1 
INFO[0019] Creating virtual wire: cr2-codfw:ae1 <--> asw-a-codfw:ae2 
INFO[0019] Creating virtual wire: cr2-codfw:xe-1_0_1_0 <--> pfw3b-codfw:xe-7_0_16 
INFO[0019] Creating virtual wire: cr2-codfw:ae3 <--> asw-c-codfw:ae2 
INFO[0019] Creating virtual wire: cr2-eqord:xe-0_1_0 <--> cr2-codfw:xe-1_0_1_1 
INFO[0019] Creating virtual wire: cr2-codfw:ae1.402 <--> mr1-codfw:ge-0_0_1.402 
INFO[0019] Creating virtual wire: cr2-codfw:ae4 <--> asw-d-codfw:ae2 
INFO[0019] Creating virtual wire: cr2-codfw:ae2 <--> asw-b-codfw:ae2 
INFO[0019] Creating virtual wire: cr2-codfw:xe-1_1_1_1 <--> cr2-eqiad:xe-3_2_2 
INFO[0019] Creating virtual wire: cr1-codfw:ae0 <--> cr2-codfw:ae0 
INFO[0019] Creating virtual wire: cr2-eqdfw:xe-0_1_4 <--> cr2-codfw:xe-1_1_1_2 
INFO[0019] Creating virtual wire: asw2-c-eqiad:eth1 <--> lvs1019:eth1 
INFO[0019] Creating virtual wire: asw1-eqsin:eth2 <--> lvs5002:eth1 
INFO[0020] Creating virtual wire: asw2-esams:eth3 <--> lvs3007:eth1 
INFO[0020] Creating virtual wire: cr1-eqiad:et-1_0_2.100 <--> lsw1-e1-eqiad:et-0_0_48.100 
INFO[0020] Creating virtual wire: cr3-esams:ae1.402 <--> mr1-esams:ge-0_0_1.402 
INFO[0020] Creating virtual wire: cr2-esams:ae1.404 <--> mr1-esams:ge-0_0_1.404 
INFO[0022] Adding containerlab host entries to /etc/hosts file 
+----+--------------------------------+--------------+---------------+-------+---------+-----------------+-----------------------+
| #  |              Name              | Container ID |     Image     | Kind  |  State  |  IPv4 Address   |     IPv6 Address      |
+----+--------------------------------+--------------+---------------+-------+---------+-----------------+-----------------------+
|  1 | clab-wmf-lab-asw-a-codfw       | e7f0a956561c | debian:latest | linux | running | 172.20.20.14/24 | 2001:172:20:20::e/64  |
|  2 | clab-wmf-lab-asw-b-codfw       | 5a9a8d239881 | debian:latest | linux | running | 172.20.20.10/24 | 2001:172:20:20::a/64  |
|  3 | clab-wmf-lab-asw-c-codfw       | 6735671fd9b4 | debian:latest | linux | running | 172.20.20.8/24  | 2001:172:20:20::8/64  |
|  4 | clab-wmf-lab-asw-d-codfw       | 5ccfda3bd0aa | debian:latest | linux | running | 172.20.20.13/24 | 2001:172:20:20::d/64  |
|  5 | clab-wmf-lab-asw1-b12-drmrs    | fd20c110872e | crpd          | crpd  | running | 172.20.20.47/24 | 2001:172:20:20::2f/64 |
|  6 | clab-wmf-lab-asw1-b13-drmrs    | 54166a7e0507 | crpd          | crpd  | running | 172.20.20.27/24 | 2001:172:20:20::1b/64 |
|  7 | clab-wmf-lab-asw1-eqsin        | 303f3dd38341 | debian:latest | linux | running | 172.20.20.5/24  | 2001:172:20:20::5/64  |
|  8 | clab-wmf-lab-asw2-a-eqiad      | 3c7a575263ed | debian:latest | linux | running | 172.20.20.4/24  | 2001:172:20:20::4/64  |
|  9 | clab-wmf-lab-asw2-b-eqiad      | ad7d8983da85 | debian:latest | linux | running | 172.20.20.9/24  | 2001:172:20:20::9/64  |
| 10 | clab-wmf-lab-asw2-c-eqiad      | a58edac188b2 | debian:latest | linux | running | 172.20.20.11/24 | 2001:172:20:20::b/64  |
| 11 | clab-wmf-lab-asw2-d-eqiad      | a2ff691f6a78 | debian:latest | linux | running | 172.20.20.12/24 | 2001:172:20:20::c/64  |
| 12 | clab-wmf-lab-asw2-esams        | 237c05a5dacc | debian:latest | linux | running | 172.20.20.6/24  | 2001:172:20:20::6/64  |
| 13 | clab-wmf-lab-asw2-ulsfo        | d3608834f0c8 | debian:latest | linux | running | 172.20.20.3/24  | 2001:172:20:20::3/64  |
| 14 | clab-wmf-lab-cloudsw1-c8-eqiad | 98a934b05b6f | debian:latest | linux | running | 172.20.20.7/24  | 2001:172:20:20::7/64  |
| 15 | clab-wmf-lab-cloudsw1-d5-eqiad | 250c03ec81a0 | debian:latest | linux | running | 172.20.20.2/24  | 2001:172:20:20::2/64  |
| 16 | clab-wmf-lab-cr1-codfw         | 1d005d041a77 | crpd          | crpd  | running | 172.20.20.31/24 | 2001:172:20:20::1f/64 |
| 17 | clab-wmf-lab-cr1-drmrs         | 36f18adebd43 | crpd          | crpd  | running | 172.20.20.20/24 | 2001:172:20:20::14/64 |
| 18 | clab-wmf-lab-cr1-eqiad         | 7d5f09287ea7 | crpd          | crpd  | running | 172.20.20.49/24 | 2001:172:20:20::31/64 |
| 19 | clab-wmf-lab-cr2-codfw         | 90b587d37b39 | crpd          | crpd  | running | 172.20.20.54/24 | 2001:172:20:20::36/64 |
| 20 | clab-wmf-lab-cr2-drmrs         | 4751ab8f389a | crpd          | crpd  | running | 172.20.20.29/24 | 2001:172:20:20::1d/64 |
| 21 | clab-wmf-lab-cr2-eqdfw         | 3ab9af4009dd | crpd          | crpd  | running | 172.20.20.41/24 | 2001:172:20:20::29/64 |
| 22 | clab-wmf-lab-cr2-eqiad         | 04fecaf6e3c4 | crpd          | crpd  | running | 172.20.20.55/24 | 2001:172:20:20::37/64 |
| 23 | clab-wmf-lab-cr2-eqord         | b944cd7acbb5 | crpd          | crpd  | running | 172.20.20.45/24 | 2001:172:20:20::2d/64 |
| 24 | clab-wmf-lab-cr2-eqsin         | 4a968656c51e | crpd          | crpd  | running | 172.20.20.26/24 | 2001:172:20:20::1a/64 |
| 25 | clab-wmf-lab-cr2-esams         | 4c1f69d59f58 | crpd          | crpd  | running | 172.20.20.28/24 | 2001:172:20:20::1c/64 |
| 26 | clab-wmf-lab-cr3-eqsin         | 8ef181208793 | crpd          | crpd  | running | 172.20.20.16/24 | 2001:172:20:20::10/64 |
| 27 | clab-wmf-lab-cr3-esams         | 816eec6f0616 | crpd          | crpd  | running | 172.20.20.36/24 | 2001:172:20:20::24/64 |
| 28 | clab-wmf-lab-cr3-knams         | 156563e8fe50 | crpd          | crpd  | running | 172.20.20.32/24 | 2001:172:20:20::20/64 |
| 29 | clab-wmf-lab-cr3-ulsfo         | a579d85acde4 | crpd          | crpd  | running | 172.20.20.17/24 | 2001:172:20:20::11/64 |
| 30 | clab-wmf-lab-cr4-ulsfo         | 772a99fd9538 | crpd          | crpd  | running | 172.20.20.52/24 | 2001:172:20:20::34/64 |
| 31 | clab-wmf-lab-lsw1-e1-eqiad     | d7ffe8901b8e | crpd          | crpd  | running | 172.20.20.50/24 | 2001:172:20:20::32/64 |
| 32 | clab-wmf-lab-lsw1-f1-eqiad     | e4f087443273 | crpd          | crpd  | running | 172.20.20.33/24 | 2001:172:20:20::21/64 |
| 33 | clab-wmf-lab-lvs1017           | d5fe3b0982c9 | crpd          | crpd  | running | 172.20.20.35/24 | 2001:172:20:20::23/64 |
| 34 | clab-wmf-lab-lvs1018           | 24314c6db697 | crpd          | crpd  | running | 172.20.20.44/24 | 2001:172:20:20::2c/64 |
| 35 | clab-wmf-lab-lvs1019           | c6f15fdfaec6 | crpd          | crpd  | running | 172.20.20.59/24 | 2001:172:20:20::3b/64 |
| 36 | clab-wmf-lab-lvs1020           | 9479bd455d42 | crpd          | crpd  | running | 172.20.20.18/24 | 2001:172:20:20::12/64 |
| 37 | clab-wmf-lab-lvs2007           | 9eedb3b77589 | crpd          | crpd  | running | 172.20.20.21/24 | 2001:172:20:20::15/64 |
| 38 | clab-wmf-lab-lvs2008           | 1fb011c73a85 | crpd          | crpd  | running | 172.20.20.38/24 | 2001:172:20:20::26/64 |
| 39 | clab-wmf-lab-lvs2009           | ff7fb7523228 | crpd          | crpd  | running | 172.20.20.37/24 | 2001:172:20:20::25/64 |
| 40 | clab-wmf-lab-lvs2010           | 53db6b3f7805 | crpd          | crpd  | running | 172.20.20.19/24 | 2001:172:20:20::13/64 |
| 41 | clab-wmf-lab-lvs3005           | 086dbd822759 | crpd          | crpd  | running | 172.20.20.46/24 | 2001:172:20:20::2e/64 |
| 42 | clab-wmf-lab-lvs3006           | 638d1d63b65a | crpd          | crpd  | running | 172.20.20.34/24 | 2001:172:20:20::22/64 |
| 43 | clab-wmf-lab-lvs3007           | 58f651924784 | crpd          | crpd  | running | 172.20.20.57/24 | 2001:172:20:20::39/64 |
| 44 | clab-wmf-lab-lvs4005           | 18c80977ee42 | crpd          | crpd  | running | 172.20.20.24/24 | 2001:172:20:20::18/64 |
| 45 | clab-wmf-lab-lvs4006           | 16e9e64028cd | crpd          | crpd  | running | 172.20.20.40/24 | 2001:172:20:20::28/64 |
| 46 | clab-wmf-lab-lvs4007           | d0c37f3116d3 | crpd          | crpd  | running | 172.20.20.23/24 | 2001:172:20:20::17/64 |
| 47 | clab-wmf-lab-lvs5001           | c78133c04782 | crpd          | crpd  | running | 172.20.20.51/24 | 2001:172:20:20::33/64 |
| 48 | clab-wmf-lab-lvs5002           | 652c699937aa | crpd          | crpd  | running | 172.20.20.58/24 | 2001:172:20:20::3a/64 |
| 49 | clab-wmf-lab-lvs5003           | b2f709a0fbb7 | crpd          | crpd  | running | 172.20.20.30/24 | 2001:172:20:20::1e/64 |
| 50 | clab-wmf-lab-mr1-codfw         | f2c1bc03be26 | crpd          | crpd  | running | 172.20.20.56/24 | 2001:172:20:20::38/64 |
| 51 | clab-wmf-lab-mr1-eqiad         | f26d0ec62df5 | crpd          | crpd  | running | 172.20.20.53/24 | 2001:172:20:20::35/64 |
| 52 | clab-wmf-lab-mr1-eqsin         | d80f67f4fbd2 | crpd          | crpd  | running | 172.20.20.15/24 | 2001:172:20:20::f/64  |
| 53 | clab-wmf-lab-mr1-esams         | 0afd3045ca05 | crpd          | crpd  | running | 172.20.20.48/24 | 2001:172:20:20::30/64 |
| 54 | clab-wmf-lab-mr1-ulsfo         | 3578fe3fda4c | crpd          | crpd  | running | 172.20.20.43/24 | 2001:172:20:20::2b/64 |
| 55 | clab-wmf-lab-pfw3a-codfw       | 6036afa171ce | crpd          | crpd  | running | 172.20.20.22/24 | 2001:172:20:20::16/64 |
| 56 | clab-wmf-lab-pfw3a-eqiad       | b103d9142c56 | crpd          | crpd  | running | 172.20.20.39/24 | 2001:172:20:20::27/64 |
| 57 | clab-wmf-lab-pfw3b-codfw       | b2306543dae6 | crpd          | crpd  | running | 172.20.20.42/24 | 2001:172:20:20::2a/64 |
| 58 | clab-wmf-lab-pfw3b-eqiad       | cf8493e12f68 | crpd          | crpd  | running | 172.20.20.25/24 | 2001:172:20:20::19/64 |
+----+--------------------------------+--------------+---------------+-------+---------+-----------------+-----------------------+
+ ../add_fqdn_hosts.py
removed '/etc/hosts'
renamed '/tmp/new_hosts' -> '/etc/hosts'
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.192/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-1/0/1:2 dev xe-1_0_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 103.102.166.139/31 dev xe-1_0_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2001:df2:e500:fe02::2/64 dev xe-1_0_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-1/0/1:3 dev xe-1_0_1_3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.200/31 dev xe-1_0_1_3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-1/1/1:0 dev xe-1_1_1_0
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 198.35.26.203/31 dev xe-1_1_1_0
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:863:fe07::2/64 dev xe-1_1_1_0
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-1/1/1:2 dev xe-1_1_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.210/31 dev xe-1_1_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe03::1/64 dev xe-1_1_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-1/1/1:3 dev xe-1_1_1_3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.221/31 dev xe-1_1_1_3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe01::2/64 dev xe-1_1_1_3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.218/31 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe00::1/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.401 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.206/31 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe05::1/64 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae3 dev ae3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev ae3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae4 dev ae4
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev ae4
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae1 name ae1.2001 type vlan id 2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.2/27 dev ae1.2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:1:fe00::1/64 dev ae1.2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae1.2001 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.2001 dev ae1.2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae1 name ae1.2017 type vlan id 2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.0.2/22 dev ae1.2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:101:fe00::1/64 dev ae1.2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae1.2017 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.2017 dev ae1.2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae1 name ae1.2201 type vlan id 2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.152.242/28 dev ae1.2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:201:fe00::1/64 dev ae1.2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae1.2201 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.2201 dev ae1.2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae2 name ae2.2002 type vlan id 2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.34/27 dev ae2.2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:2:fe00::1/64 dev ae2.2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae2.2002 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2002 dev ae2.2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae2 name ae2.2018 type vlan id 2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.16.2/22 dev ae2.2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:102:fe00::1/64 dev ae2.2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae2.2018 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2018 dev ae2.2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae2 name ae2.2118 type vlan id 2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.20.2/24 dev ae2.2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:118:fe00::1/64 dev ae2.2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae2.2118 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2118 dev ae2.2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae2 name ae2.2120 type vlan id 2120
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.186/29 dev ae2.2120
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae2.2120 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2120 dev ae2.2120
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae2 name ae2.2122 type vlan id 2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.21.2/24 dev ae2.2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:122:fe00::1/64 dev ae2.2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae2.2122 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2122 dev ae2.2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae3 name ae3.2003 type vlan id 2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.66/27 dev ae3.2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:3:fe00::1/64 dev ae3.2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae3.2003 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae3.2003 dev ae3.2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae3 name ae3.2019 type vlan id 2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.32.2/22 dev ae3.2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:103:fe00::1/64 dev ae3.2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae3.2019 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae3.2019 dev ae3.2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae4 name ae4.2004 type vlan id 2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.98/27 dev ae4.2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:4:fe00::1/64 dev ae4.2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae4.2004 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae4.2004 dev ae4.2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link ae4 name ae4.2020 type vlan id 2020
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.48.2/22 dev ae4.2020
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:104:fe00::1/64 dev ae4.2020
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev ae4.2020 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae4.2020 dev ae4.2020
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.131/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:ffff::4/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias xe-0/1/0 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.138/31 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:fe02::1/64 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.140/31 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:fe05::1/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.401 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.132/31 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:fe03::1/64 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link add link ae1 name ae1.510 type vlan id 510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.2/28 dev ae1.510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:1:fe00::1/64 dev ae1.510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set dev ae1.510 up
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.510 dev ae1.510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link add link ae1 name ae1.520 type vlan id 520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 10.132.0.2/24 dev ae1.520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:101:fe00::1/64 dev ae1.520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set dev ae1.520 up
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.520 dev ae1.520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link add link ae1 name ae1.530 type vlan id 530
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.18/28 dev ae1.530
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:201:fe00::1/64 dev ae1.530
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set dev ae1.530 up
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.530 dev ae1.530
+ sudo ip netns exec clab-wmf-lab-pfw3a-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3a-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3a-codfw ip link set alias xe-0/0/16 dev xe-0_0_16
+ sudo ip netns exec clab-wmf-lab-pfw3a-codfw ip addr add 208.80.153.201/31 dev xe-0_0_16
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.193/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias xe-0/1/1 dev xe-0_1_1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.202/31 dev xe-0_1_1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe07::1/64 dev xe-0_1_1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias gr-0/0/0.2 dev gr-0_0_0.2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.204/31 dev gr-0_0_0.2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe04::1/64 dev gr-0_0_0.2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias xe-0/1/2 dev xe-0_1_2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.206/31 dev xe-0_1_2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe01::1/64 dev xe-0_1_2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.501 dev et-0_0_1.501
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.226/29 dev et-0_0_1.501
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:62:c000::200:149:2/125 dev et-0_0_1.501
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias ae0.2 dev ae0.2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.197/31 dev ae0.2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe00::2/64 dev ae0.2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.402 dev et-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.200/31 dev et-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe06::1/64 dev et-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr flush dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link add link et-0_0_1 name et-0_0_1.1201 type vlan id 1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.3/28 dev et-0_0_1.1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:1:fe00::2/64 dev et-0_0_1.1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set dev et-0_0_1.1201 up
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.1201 dev et-0_0_1.1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link add link et-0_0_1 name et-0_0_1.1211 type vlan id 1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 10.128.0.3/24 dev et-0_0_1.1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:101:fe00::2/64 dev et-0_0_1.1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set dev et-0_0_1.1211 up
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.1211 dev et-0_0_1.1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link add link et-0_0_1 name et-0_0_1.1221 type vlan id 1221
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.243/28 dev et-0_0_1.1221
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:201:fe00::2/64 dev et-0_0_1.1221
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set dev et-0_0_1.1221 up
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.1221 dev et-0_0_1.1221
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.198/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:ffff::5/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/0 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.211/31 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe03::2/64 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/3.12 dev xe-0_1_3.12
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.215/31 dev xe-0_1_3.12
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe08::2/64 dev xe-0_1_3.12
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/4 dev xe-0_1_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.213/31 dev xe-0_1_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe04::2/64 dev xe-0_1_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/3.26 dev xe-0_1_3.26
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.204/31 dev xe-0_1_3.26
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe0a::1/64 dev xe-0_1_3.26
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias gr-0/0/0.1 dev gr-0_0_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 198.35.26.205/31 dev gr-0_0_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:863:fe04::2/64 dev gr-0_0_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/3.23 dev xe-0_1_3.23
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.217/31 dev xe-0_1_3.23
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe09::2/64 dev xe-0_1_3.23
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.196/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/0 dev xe-4_2_0
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.153.220/31 dev xe-4_2_0
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:860:fe01::1/64 dev xe-4_2_0
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/1/4 dev xe-3_1_4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 185.15.58.138/31 dev xe-3_1_4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2a02:ec80:600:fe01::1/64 dev xe-3_1_4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias et-1/0/2.100 dev et-1_0_2.100
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.66.0.8/31 dev et-1_0_2.100
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:fe07::1/64 dev et-1_0_2.100
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/4 dev xe-3_0_4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev xe-3_0_4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/6 dev xe-3_0_6
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 206.126.236.106/22 dev xe-3_0_6
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2001:504:0:2:0:1:4907:2/64 dev xe-3_0_6
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/1/7 dev xe-3_1_7
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.200/31 dev xe-3_1_7
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/2.12 dev xe-4_2_2.12
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.153.214/31 dev xe-4_2_2.12
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:860:fe08::1/64 dev xe-4_2_2.12
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/2.13 dev xe-4_2_2.13
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 91.198.174.250/31 dev xe-4_2_2.13
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:862:fe06::1/64 dev xe-4_2_2.13
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/2.16 dev xe-4_2_2.16
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 185.15.58.147/31 dev xe-4_2_2.16
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2a02:ec80:600:fe04::2/64 dev xe-4_2_2.16
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias gr-4/3/0.1 dev gr-4_3_0.1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 103.102.166.147/31 dev gr-4_3_0.1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2001:df2:e500:fe07::2/64 dev gr-4_3_0.1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.193/30 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:fe00::1/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.401 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.204/31 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:fe04::1/64 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3 dev ae3
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev ae3
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4 dev ae4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev ae4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link xe-3_0_4 name xe-3_0_4.1000 type vlan id 1000
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.147.16/31 dev xe-3_0_4.1000
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:fe09::1/64 dev xe-3_0_4.1000
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev xe-3_0_4.1000 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/4.1000 dev xe-3_0_4.1000
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link xe-3_0_4 name xe-3_0_4.1102 type vlan id 1102
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.210/31 dev xe-3_0_4.1102
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev xe-3_0_4.1102 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/4.1102 dev xe-3_0_4.1102
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae1 name ae1.1001 type vlan id 1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.2/26 dev ae1.1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:1:fe00::1/64 dev ae1.1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae1.1001 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1001 dev ae1.1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae1 name ae1.1017 type vlan id 1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.0.2/22 dev ae1.1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:101:fe00::1/64 dev ae1.1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae1.1017 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1017 dev ae1.1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae1 name ae1.1030 type vlan id 1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.5.2/24 dev ae1.1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:104:fe00::1/64 dev ae1.1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae1.1030 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1030 dev ae1.1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae1 name ae1.1117 type vlan id 1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.4.2/24 dev ae1.1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:117:fe00::1/64 dev ae1.1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae1.1117 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1117 dev ae1.1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae2 name ae2.1002 type vlan id 1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.130/26 dev ae2.1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:2:fe00::1/64 dev ae2.1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae2.1002 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1002 dev ae2.1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae2 name ae2.1018 type vlan id 1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.16.2/22 dev ae2.1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:102:fe00::1/64 dev ae2.1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae2.1018 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1018 dev ae2.1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae2 name ae2.1021 type vlan id 1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.21.2/24 dev ae2.1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:105:fe00::1/64 dev ae2.1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae2.1021 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1021 dev ae2.1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae2 name ae2.1202 type vlan id 1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.155.66/28 dev ae2.1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:202:fe00::1/64 dev ae2.1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae2.1202 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1202 dev ae2.1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae3 name ae3.1003 type vlan id 1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.66/26 dev ae3.1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:3:fe00::1/64 dev ae3.1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae3.1003 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1003 dev ae3.1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae3 name ae3.1019 type vlan id 1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.32.2/22 dev ae3.1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:103:fe00::1/64 dev ae3.1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae3.1019 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1019 dev ae3.1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae3 name ae3.1022 type vlan id 1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.36.2/24 dev ae3.1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:106:fe00::1/64 dev ae3.1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae3.1022 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1022 dev ae3.1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae3 name ae3.1119 type vlan id 1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.37.2/24 dev ae3.1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:119:fe00::1/64 dev ae3.1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae3.1119 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1119 dev ae3.1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae4 name ae4.1004 type vlan id 1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.155.98/27 dev ae4.1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:4:fe00::1/64 dev ae4.1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae4.1004 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4.1004 dev ae4.1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae4 name ae4.1020 type vlan id 1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.48.2/22 dev ae4.1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:107:fe00::1/64 dev ae4.1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae4.1020 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4.1020 dev ae4.1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link ae4 name ae4.1023 type vlan id 1023
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.53.2/24 dev ae4.1023
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:108:fe00::1/64 dev ae4.1023
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev ae4.1023 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4.1023 dev ae4.1023
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.193/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.219/31 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe00::2/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-1/0/1:0 dev xe-1_0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.202/31 dev xe-1_0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-1/0/1:1 dev xe-1_0_1_1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.223/31 dev xe-1_0_1_1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe02::2/64 dev xe-1_0_1_1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-1/1/1:1 dev xe-1_1_1_1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.154.215/31 dev xe-1_1_1_1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:861:fe06::2/64 dev xe-1_1_1_1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-1/1/1:2 dev xe-1_1_1_2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.212/31 dev xe-1_1_1_2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe04::1/64 dev xe-1_1_1_2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.402 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.208/31 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe06::1/64 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae3 dev ae3
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev ae3
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae4 dev ae4
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev ae4
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae1 name ae1.2001 type vlan id 2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.3/27 dev ae1.2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:1:fe00::2/64 dev ae1.2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae1.2001 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.2001 dev ae1.2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae1 name ae1.2017 type vlan id 2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.0.3/22 dev ae1.2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:101:fe00::2/64 dev ae1.2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae1.2017 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.2017 dev ae1.2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae1 name ae1.2201 type vlan id 2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.152.243/28 dev ae1.2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:201:fe00::2/64 dev ae1.2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae1.2201 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.2201 dev ae1.2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae2 name ae2.2002 type vlan id 2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.35/27 dev ae2.2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:2:fe00::2/64 dev ae2.2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae2.2002 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2002 dev ae2.2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae2 name ae2.2018 type vlan id 2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.16.3/22 dev ae2.2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:102:fe00::2/64 dev ae2.2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae2.2018 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2018 dev ae2.2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae2 name ae2.2118 type vlan id 2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.20.3/24 dev ae2.2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:118:fe00::2/64 dev ae2.2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae2.2118 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2118 dev ae2.2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae2 name ae2.2120 type vlan id 2120
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.187/29 dev ae2.2120
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae2.2120 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2120 dev ae2.2120
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae2 name ae2.2122 type vlan id 2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.21.3/24 dev ae2.2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:122:fe00::2/64 dev ae2.2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae2.2122 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2122 dev ae2.2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae3 name ae3.2003 type vlan id 2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.67/27 dev ae3.2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:3:fe00::2/64 dev ae3.2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae3.2003 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae3.2003 dev ae3.2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae3 name ae3.2019 type vlan id 2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.32.3/22 dev ae3.2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:103:fe00::2/64 dev ae3.2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae3.2019 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae3.2019 dev ae3.2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae4 name ae4.2004 type vlan id 2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.99/27 dev ae4.2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:4:fe00::2/64 dev ae4.2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae4.2004 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae4.2004 dev ae4.2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link ae4 name ae4.2020 type vlan id 2020
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.48.3/22 dev ae4.2020
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:104:fe00::2/64 dev ae4.2020
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev ae4.2020 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae4.2020 dev ae4.2020
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip link set alias ge-0/0/1.401 dev ge-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 208.80.153.207/31 dev ge-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 2620:0:860:fe05::2/64 dev ge-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip link set alias ge-0/0/1.402 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 208.80.153.209/31 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 2620:0:860:fe06::2/64 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev ae1 vid 2001
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev ae1 vid 2017
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev ae1 vid 2201
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev ae2 vid 2001
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev ae2 vid 2017
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev ae2 vid 2201
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw bridge vlan add dev eth1 vid 2017 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw-a-codfw ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae1 vid 2002
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae1 vid 2018
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae1 vid 2118
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae1 vid 2120
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae1 vid 2122
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae2 vid 2002
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae2 vid 2018
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae2 vid 2118
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae2 vid 2120
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev ae2 vid 2122
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw bridge vlan add dev eth1 vid 2018 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw-b-codfw ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan add dev ae1 vid 2003
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan add dev ae1 vid 2019
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan add dev ae2 vid 2003
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan add dev ae2 vid 2019
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw bridge vlan add dev eth1 vid 2019 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw-c-codfw ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan add dev ae1 vid 2004
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan add dev ae1 vid 2020
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan add dev ae2 vid 2004
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan add dev ae2 vid 2020
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw bridge vlan add dev eth1 vid 2020 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw-d-codfw ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 185.15.58.128/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 2a02:ec80:600:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip link set alias et-0/0/0 dev et-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 185.15.58.136/31 dev et-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 2a02:ec80:600:fe05::1/64 dev et-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip link set alias et-0/0/1 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 185.15.58.142/31 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 2a02:ec80:600:fe06::1/64 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip link set alias et-0/0/2 dev et-0_0_2
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 185.15.58.148/31 dev et-0_0_2
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 2a02:ec80:600:fe07::1/64 dev et-0_0_2
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip link set alias xe-0/1/2 dev xe-0_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 185.15.58.139/31 dev xe-0_1_2
+ sudo ip netns exec clab-wmf-lab-cr1-drmrs ip addr add 2a02:ec80:600:fe01::2/64 dev xe-0_1_2
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 185.15.58.129/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2a02:ec80:600:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip link set alias et-0/0/0 dev et-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 185.15.58.137/31 dev et-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2a02:ec80:600:fe05::2/64 dev et-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip link set alias xe-0/1/1.16 dev xe-0_1_1.16
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 185.15.58.146/31 dev xe-0_1_1.16
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2a02:ec80:600:fe04::1/64 dev xe-0_1_1.16
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip link set alias et-0/0/1 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 185.15.58.144/31 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2a02:ec80:600:fe09::1/64 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip link set alias et-0/0/2 dev et-0_0_2
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 185.15.58.140/31 dev et-0_0_2
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2a02:ec80:600:fe08::1/64 dev et-0_0_2
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip link set alias xe-0/1/1.26 dev xe-0_1_1.26
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 208.80.153.205/31 dev xe-0_1_1.26
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2620:0:860:fe0a::2/64 dev xe-0_1_1.26
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip link set alias xe-0/1/3 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 91.198.174.225/31 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-drmrs ip addr add 2620:0:862:fe08::2/64 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip link set alias et-0/0/48 dev et-0_0_48
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip addr add 185.15.58.143/31 dev et-0_0_48
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip addr add 2a02:ec80:600:fe06::2/64 dev et-0_0_48
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip link set alias et-0/0/50 dev et-0_0_50
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip addr add 185.15.58.141/31 dev et-0_0_50
+ sudo ip netns exec clab-wmf-lab-asw1-b12-drmrs ip addr add 2a02:ec80:600:fe08::2/64 dev et-0_0_50
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip link set alias et-0/0/50 dev et-0_0_50
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip addr add 185.15.58.149/31 dev et-0_0_50
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip addr add 2a02:ec80:600:fe07::2/64 dev et-0_0_50
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip link set alias et-0/0/48 dev et-0_0_48
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip addr add 185.15.58.145/31 dev et-0_0_48
+ sudo ip netns exec clab-wmf-lab-asw1-b13-drmrs ip addr add 2a02:ec80:600:fe09::2/64 dev et-0_0_48
+ sudo ip netns exec clab-wmf-lab-lsw1-e1-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lsw1-e1-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lsw1-e1-eqiad ip link set alias et-0/0/48.100 dev et-0_0_48.100
+ sudo ip netns exec clab-wmf-lab-lsw1-e1-eqiad ip addr add 10.66.0.9/31 dev et-0_0_48.100
+ sudo ip netns exec clab-wmf-lab-lsw1-e1-eqiad ip addr add 2620:0:861:fe07::2/64 dev et-0_0_48.100
+ sudo ip netns exec clab-wmf-lab-cloudsw1-c8-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cloudsw1-c8-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cloudsw1-c8-eqiad ip link set alias xe-0/0/0 dev xe-0_0_0
+ sudo ip netns exec clab-wmf-lab-cloudsw1-c8-eqiad ip addr flush dev xe-0_0_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.197/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/3/3 dev xe-3_3_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 206.126.236.221/22 dev xe-3_3_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2001:504:0:2:0:1:4907:1/64 dev xe-3_3_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.194/30 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe00::2/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/2/2 dev xe-3_2_2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.214/31 dev xe-3_2_2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe06::1/64 dev xe-3_2_2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias et-1/0/2.100 dev et-1_0_2.100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.66.0.10/31 dev et-1_0_2.100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe08::1/64 dev et-1_0_2.100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/0/4 dev xe-3_0_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev xe-3_0_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/1/7 dev xe-3_1_7
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.202/31 dev xe-3_1_7
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-4/1/3 dev xe-4_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 91.198.174.248/31 dev xe-4_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:862:fe07::1/64 dev xe-4_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-4/2/0 dev xe-4_2_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.208/31 dev xe-4_2_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe02::1/64 dev xe-4_2_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias gr-4/3/0.1 dev gr-4_3_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.220/31 dev gr-4_3_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe03::1/64 dev gr-4_3_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.402 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.206/31 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe05::1/64 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3 dev ae3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev ae3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4 dev ae4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev ae4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link xe-3_0_4 name xe-3_0_4.1100 type vlan id 1100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.147.14/31 dev xe-3_0_4.1100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe0a::1/64 dev xe-3_0_4.1100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev xe-3_0_4.1100 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/0/4.1100 dev xe-3_0_4.1100
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link xe-3_0_4 name xe-3_0_4.1103 type vlan id 1103
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.212/31 dev xe-3_0_4.1103
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev xe-3_0_4.1103 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/0/4.1103 dev xe-3_0_4.1103
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae1 name ae1.1001 type vlan id 1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.3/26 dev ae1.1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:1:fe00::2/64 dev ae1.1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae1.1001 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1001 dev ae1.1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae1 name ae1.1017 type vlan id 1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.0.3/22 dev ae1.1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:101:fe00::2/64 dev ae1.1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae1.1017 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1017 dev ae1.1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae1 name ae1.1030 type vlan id 1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.5.3/24 dev ae1.1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:104:fe00::2/64 dev ae1.1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae1.1030 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1030 dev ae1.1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae1 name ae1.1117 type vlan id 1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.4.3/24 dev ae1.1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:117:fe00::2/64 dev ae1.1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae1.1117 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1117 dev ae1.1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae2 name ae2.1002 type vlan id 1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.131/26 dev ae2.1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:2:fe00::2/64 dev ae2.1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae2.1002 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1002 dev ae2.1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae2 name ae2.1018 type vlan id 1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.16.3/22 dev ae2.1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:102:fe00::2/64 dev ae2.1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae2.1018 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1018 dev ae2.1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae2 name ae2.1021 type vlan id 1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.21.3/24 dev ae2.1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:105:fe00::2/64 dev ae2.1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae2.1021 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1021 dev ae2.1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae2 name ae2.1202 type vlan id 1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.155.67/28 dev ae2.1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:202:fe00::2/64 dev ae2.1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae2.1202 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1202 dev ae2.1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae3 name ae3.1003 type vlan id 1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.67/26 dev ae3.1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:3:fe00::2/64 dev ae3.1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae3.1003 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1003 dev ae3.1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae3 name ae3.1019 type vlan id 1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.32.3/22 dev ae3.1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:103:fe00::2/64 dev ae3.1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae3.1019 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1019 dev ae3.1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae3 name ae3.1022 type vlan id 1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.36.3/24 dev ae3.1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:106:fe00::2/64 dev ae3.1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae3.1022 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1022 dev ae3.1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae3 name ae3.1119 type vlan id 1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.37.3/24 dev ae3.1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:119:fe00::2/64 dev ae3.1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae3.1119 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1119 dev ae3.1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae4 name ae4.1004 type vlan id 1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.155.99/27 dev ae4.1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:4:fe00::2/64 dev ae4.1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae4.1004 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4.1004 dev ae4.1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae4 name ae4.1020 type vlan id 1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.48.3/22 dev ae4.1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:107:fe00::3/64 dev ae4.1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae4.1020 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4.1020 dev ae4.1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link ae4 name ae4.1023 type vlan id 1023
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.53.3/24 dev ae4.1023
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:108:fe00::2/64 dev ae4.1023
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev ae4.1023 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4.1023 dev ae4.1023
+ sudo ip netns exec clab-wmf-lab-pfw3a-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3a-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3a-eqiad ip link set alias xe-0/0/16 dev xe-0_0_16
+ sudo ip netns exec clab-wmf-lab-pfw3a-eqiad ip addr add 208.80.154.201/31 dev xe-0_0_16
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.246/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:ffff::4/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias xe-0/1/5.13 dev xe-0_1_5.13
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.251/31 dev xe-0_1_5.13
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:fe06::2/64 dev xe-0_1_5.13
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias xe-0/1/5.23 dev xe-0_1_5.23
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 208.80.153.216/31 dev xe-0_1_5.23
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:860:fe09::1/64 dev xe-0_1_5.23
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias ae1.403 dev ae1.403
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.255/31 dev ae1.403
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:fe03::2/64 dev ae1.403
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias ae1.401 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.229/31 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:fe01::2/64 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.130/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:ffff::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias gr-0/1/0.1 dev gr-0_1_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.146/31 dev gr-0_1_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:fe07::1/64 dev gr-0_1_0.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias xe-0/1/4 dev xe-0_1_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 198.35.26.207/31 dev xe-0_1_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2620:0:863:fe01::2/64 dev xe-0_1_4
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.141/31 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:fe05::2/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.402 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.142/31 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:fe04::1/64 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link add link ae1 name ae1.510 type vlan id 510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.3/28 dev ae1.510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:1:fe00::2/64 dev ae1.510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set dev ae1.510 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.510 dev ae1.510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link add link ae1 name ae1.520 type vlan id 520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 10.132.0.3/24 dev ae1.520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:101:fe00::2/64 dev ae1.520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set dev ae1.520 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.520 dev ae1.520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link add link ae1 name ae1.530 type vlan id 530
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.19/28 dev ae1.530
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:201:fe00::2/64 dev ae1.530
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set dev ae1.530 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.530 dev ae1.530
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip link set alias ge-0/0/1.401 dev ge-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 208.80.154.205/31 dev ge-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 2620:0:861:fe04::2/64 dev ge-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip link set alias ge-0/0/1.402 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 208.80.154.207/31 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 2620:0:861:fe05::2/64 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae1 vid 1001
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae1 vid 1017
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae1 vid 1030
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae1 vid 1117
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae2 vid 1001
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae2 vid 1017
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae2 vid 1030
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev ae2 vid 1117
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad bridge vlan add dev eth1 vid 1017 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-a-eqiad ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae1 vid 1002
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae1 vid 1018
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae1 vid 1021
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae1 vid 1202
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae2 vid 1002
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae2 vid 1018
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae2 vid 1021
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev ae2 vid 1202
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad bridge vlan add dev eth1 vid 1018 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-b-eqiad ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae1 vid 1003
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae1 vid 1019
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae1 vid 1022
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae1 vid 1119
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae2 vid 1003
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae2 vid 1019
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae2 vid 1022
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev ae2 vid 1119
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad bridge vlan add dev eth1 vid 1019 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-c-eqiad ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev ae1 vid 1004
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev ae1 vid 1020
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev ae1 vid 1023
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev ae2 vid 1004
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev ae2 vid 1020
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev ae2 vid 1023
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad bridge vlan add dev eth1 vid 1020 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-d-eqiad ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-pfw3b-codfw ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3b-codfw ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3b-codfw ip link set alias xe-7/0/16 dev xe-7_0_16
+ sudo ip netns exec clab-wmf-lab-pfw3b-codfw ip addr add 208.80.153.203/31 dev xe-7_0_16
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 208.80.154.198/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:861:ffff::5/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip link set alias xe-0/1/0 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 208.80.153.222/31 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:860:fe02::1/64 dev xe-0_1_0
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip link set alias xe-0/1/5 dev xe-0_1_5
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 208.80.154.209/31 dev xe-0_1_5
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:861:fe02::2/64 dev xe-0_1_5
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip link set alias xe-0/1/3 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 198.35.26.209/31 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:863:fe02::2/64 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.245/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:ffff::5/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias xe-0/0/1 dev xe-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.224/31 dev xe-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe08::1/64 dev xe-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias gr-0/0/0.1 dev gr-0_0_0.1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 208.80.154.221/31 dev gr-0_0_0.1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:861:fe03::2/64 dev gr-0_0_0.1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.253/31 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe02::2/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.401 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.228/31 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe01::1/64 dev ae1.401
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.402 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.240/31 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe04::1/64 dev ae1.402
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link add link ae1 name ae1.100 type vlan id 100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.2/25 dev ae1.100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:1:fe00::1/64 dev ae1.100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set dev ae1.100 up
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.100 dev ae1.100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link add link ae1 name ae1.102 type vlan id 102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.130/28 dev ae1.102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:201:fe00::1/64 dev ae1.102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set dev ae1.102 up
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.102 dev ae1.102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link add link ae1 name ae1.103 type vlan id 103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 10.20.0.2/24 dev ae1.103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:102:fe00::1/64 dev ae1.103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set dev ae1.103 up
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.103 dev ae1.103
+ sudo ip netns exec clab-wmf-lab-lsw1-f1-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lsw1-f1-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lsw1-f1-eqiad ip link set alias et-0/0/48.100 dev et-0_0_48.100
+ sudo ip netns exec clab-wmf-lab-lsw1-f1-eqiad ip addr add 10.66.0.11/31 dev et-0_0_48.100
+ sudo ip netns exec clab-wmf-lab-lsw1-f1-eqiad ip addr add 2620:0:861:fe08::2/64 dev et-0_0_48.100
+ sudo ip netns exec clab-wmf-lab-cloudsw1-d5-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cloudsw1-d5-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cloudsw1-d5-eqiad ip link set alias xe-0/0/0 dev xe-0_0_0
+ sudo ip netns exec clab-wmf-lab-cloudsw1-d5-eqiad ip addr flush dev xe-0_0_0
+ sudo ip netns exec clab-wmf-lab-pfw3b-eqiad ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3b-eqiad ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-pfw3b-eqiad ip link set alias xe-7/0/16 dev xe-7_0_16
+ sudo ip netns exec clab-wmf-lab-pfw3b-eqiad ip addr add 208.80.154.203/31 dev xe-7_0_16
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.244/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:ffff::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias xe-0/1/3 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.249/31 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe07::2/64 dev xe-0_1_3
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae0 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.252/31 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe02::1/64 dev ae0
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.403 dev ae1.403
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.254/31 dev ae1.403
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe03::1/64 dev ae1.403
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.404 dev ae1.404
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.242/31 dev ae1.404
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe05::1/64 dev ae1.404
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link add link ae1 name ae1.100 type vlan id 100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.3/25 dev ae1.100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:1:fe00::2/64 dev ae1.100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set dev ae1.100 up
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.100 dev ae1.100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link add link ae1 name ae1.102 type vlan id 102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.131/28 dev ae1.102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:201:fe00::2/64 dev ae1.102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set dev ae1.102 up
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.102 dev ae1.102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link add link ae1 name ae1.103 type vlan id 103
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 10.20.0.3/24 dev ae1.103
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:102:fe00::2/64 dev ae1.103
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set dev ae1.103 up
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.103 dev ae1.103
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.192/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias xe-0/1/1 dev xe-0_1_1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.208/31 dev xe-0_1_1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:fe02::1/64 dev xe-0_1_1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.401 dev et-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.198/31 dev et-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:fe05::1/64 dev et-0_0_1.401
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.501 dev et-0_0_1.501
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.225/29 dev et-0_0_1.501
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:62:c000::200:149:1/125 dev et-0_0_1.501
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1 dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr flush dev et-0_0_1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias ae0.2 dev ae0.2
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.196/31 dev ae0.2
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:fe00::1/64 dev ae0.2
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link add link et-0_0_1 name et-0_0_1.1201 type vlan id 1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.2/28 dev et-0_0_1.1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:1:fe00::1/64 dev et-0_0_1.1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set dev et-0_0_1.1201 up
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.1201 dev et-0_0_1.1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link add link et-0_0_1 name et-0_0_1.1211 type vlan id 1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 10.128.0.2/24 dev et-0_0_1.1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:101:fe00::1/64 dev et-0_0_1.1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set dev et-0_0_1.1211 up
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.1211 dev et-0_0_1.1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link add link et-0_0_1 name et-0_0_1.1221 type vlan id 1221
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.242/28 dev et-0_0_1.1221
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:201:fe00::1/64 dev et-0_0_1.1221
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set dev et-0_0_1.1221 up
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.1221 dev et-0_0_1.1221
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip link set alias ge-0/0/4.402 dev ge-0_0_4.402
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 103.102.166.143/31 dev ge-0_0_4.402
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 2001:df2:e500:fe04::2/64 dev ge-0_0_4.402
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip link set alias ge-0/0/4.401 dev ge-0_0_4.401
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 103.102.166.133/31 dev ge-0_0_4.401
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 2001:df2:e500:fe03::2/64 dev ge-0_0_4.401
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev ae2 vid 510
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev ae2 vid 520
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev ae2 vid 530
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set alias ae1 dev ae1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev ae1 master br0
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan del dev ae1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev ae1 vid 510
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev ae1 vid 520
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev ae1 vid 530
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip addr flush dev ae1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev eth1 vid 520 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set alias eth2 dev eth2
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev eth2 master br0
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan del dev eth2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev eth2 vid 520 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip addr flush dev eth2
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set alias eth3 dev eth3
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip link set dev eth3 master br0
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan del dev eth3 vid 1
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin bridge vlan add dev eth3 vid 520 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw1-eqsin ip addr flush dev eth3
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set alias ae2 dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev ae2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan del dev ae2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev ae2 vid 100
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev ae2 vid 102
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev ae2 vid 103
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip addr flush dev ae2
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set alias ae3 dev ae3
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev ae3 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan del dev ae3 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev ae3 vid 100
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev ae3 vid 102
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev ae3 vid 103
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip addr flush dev ae3
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev eth1 vid 103 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set alias eth2 dev eth2
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev eth2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan del dev eth2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev eth2 vid 103 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip addr flush dev eth2
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set alias eth3 dev eth3
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip link set dev eth3 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan del dev eth3 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-esams bridge vlan add dev eth3 vid 103 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-esams ip addr flush dev eth3
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip link set alias ge-0/0/1.404 dev ge-0_0_1.404
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 91.198.174.243/31 dev ge-0_0_1.404
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 2620:0:862:fe05::2/64 dev ge-0_0_1.404
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip link set alias ge-0/0/1.402 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 91.198.174.241/31 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 2620:0:862:fe04::2/64 dev ge-0_0_1.402
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip link set alias ge-0/0/4.401 dev ge-0_0_4.401
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 198.35.26.199/31 dev ge-0_0_4.401
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 2620:0:863:fe05::2/64 dev ge-0_0_4.401
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip link set alias ge-0/0/4.402 dev ge-0_0_4.402
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 198.35.26.201/31 dev ge-0_0_4.402
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 2620:0:863:fe06::2/64 dev ge-0_0_4.402
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link add br0 type bridge vlan_filtering 1 vlan_protocol 802.1Q vlan_stats_enabled 1 vlan_stats_per_port 1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev br0 mtu 9212
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev br0 up
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip addr flush dev br0
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set alias et-1/0/24 dev et-1_0_24
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev et-1_0_24 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan del dev et-1_0_24 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev et-1_0_24 vid 1201
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev et-1_0_24 vid 1211
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev et-1_0_24 vid 1221
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip addr flush dev et-1_0_24
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set alias et-2/0/24 dev et-2_0_24
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev et-2_0_24 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan del dev et-2_0_24 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev et-2_0_24 vid 1201
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev et-2_0_24 vid 1211
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev et-2_0_24 vid 1221
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip addr flush dev et-2_0_24
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev eth1 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan del dev eth1 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev eth1 vid 1211 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip addr flush dev eth1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set alias eth2 dev eth2
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev eth2 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan del dev eth2 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev eth2 vid 1211 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip addr flush dev eth2
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set alias eth3 dev eth3
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip link set dev eth3 master br0
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan del dev eth3 vid 1
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo bridge vlan add dev eth3 vid 1211 pvid untagged
+ sudo ip netns exec clab-wmf-lab-asw2-ulsfo ip addr flush dev eth3
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 208.80.154.224/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 208.80.154.225/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 208.80.154.232/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 2620:0:861:ed1a::9/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 2620:0:861:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 2620:0:861:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip addr add 10.64.0.80/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1017 ip route add default via 10.64.0.2
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 208.80.154.240/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 208.80.154.241/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 208.80.154.242/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 208.80.154.243/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 208.80.154.250/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 208.80.154.252/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 2620:0:861:ed1a::3:241/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 2620:0:861:ed1a::3:16/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 2620:0:861:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip addr add 10.64.16.60/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1018 ip route add default via 10.64.16.2
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.1/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.10/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.11/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.12/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.13/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.14/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.16/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.17/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.18/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.19/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.20/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.21/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.22/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.23/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.24/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.25/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.26/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.27/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.28/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.29/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.30/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.31/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.32/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.34/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.35/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.37/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.38/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.39/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.40/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.41/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.42/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.43/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.44/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.45/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.46/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.47/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.48/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.49/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.5/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.50/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.51/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.52/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.53/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.54/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.55/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.56/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.57/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.59/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.60/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.61/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.62/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.63/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.64/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.65/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.66/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.67/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.68/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.69/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.70/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.71/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.73/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.2.2.8/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip addr add 10.64.32.17/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1019 ip route add default via 10.64.32.2
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.1/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.10/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.11/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.12/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.13/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.14/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.16/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.17/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.18/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.19/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.20/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.21/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.22/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.23/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.24/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.25/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.26/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.27/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.28/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.29/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.30/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.31/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.32/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.34/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.35/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.37/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.38/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.39/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.40/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.41/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.42/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.43/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.44/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.45/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.46/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.47/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.48/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.49/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.5/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.50/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.51/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.52/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.53/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.54/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.55/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.56/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.57/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.59/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.60/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.61/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.62/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.63/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.64/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.65/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.66/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.67/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.68/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.69/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.70/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.71/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.73/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.2.2.8/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.224/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.225/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.232/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.240/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.241/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.242/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.243/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.250/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 208.80.154.252/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 2620:0:861:ed1a::9/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 2620:0:861:ed1a::3:241/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 2620:0:861:ed1a::3:16/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 2620:0:861:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 2620:0:861:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 2620:0:861:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip addr add 10.64.48.72/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs1020 ip route add default via 10.64.48.2
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 208.80.153.224/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 208.80.153.225/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 208.80.153.232/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 2620:0:860:ed1a::9/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 2620:0:860:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 2620:0:860:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip addr add 10.192.1.7/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2007 ip route add default via 10.192.0.2
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip addr add 208.80.153.240/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip addr add 208.80.153.250/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip addr add 208.80.153.252/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip addr add 2620:0:860:ed1a::3:fa/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip addr add 2620:0:860:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip addr add 10.192.17.7/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2008 ip route add default via 10.192.16.2
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.1/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.10/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.11/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.13/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.14/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.16/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.17/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.18/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.19/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.20/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.21/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.22/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.23/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.24/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.25/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.26/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.27/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.28/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.29/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.30/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.31/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.32/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.34/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.35/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.37/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.39/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.41/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.42/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.43/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.44/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.45/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.46/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.47/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.48/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.49/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.5/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.50/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.51/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.52/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.53/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.54/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.55/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.56/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.57/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.58/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.59/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.60/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.61/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.62/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.63/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.64/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.65/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.66/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.67/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.68/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.69/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.70/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.72/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.2.1.8/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip addr add 10.192.33.7/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2009 ip route add default via 10.192.32.2
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.1/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.10/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.11/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.13/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.14/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.16/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.17/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.18/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.19/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.20/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.21/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.22/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.23/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.24/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.25/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.26/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.27/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.28/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.29/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.30/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.31/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.32/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.34/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.35/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.37/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.39/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.41/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.42/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.43/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.44/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.45/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.46/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.47/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.48/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.49/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.5/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.50/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.51/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.52/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.53/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.54/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.55/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.56/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.57/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.58/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.59/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.60/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.61/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.62/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.63/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.64/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.65/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.66/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.67/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.68/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.69/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.70/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.72/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.2.1.8/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 208.80.153.224/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 208.80.153.225/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 208.80.153.232/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 208.80.153.240/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 208.80.153.250/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 208.80.153.252/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 2620:0:860:ed1a::9/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 2620:0:860:ed1a::3:fa/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 2620:0:860:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 2620:0:860:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 2620:0:860:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip addr add 10.192.49.7/22 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs2010 ip route add default via 10.192.48.2
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 198.35.26.96/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 198.35.26.97/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 198.35.26.98/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 2620:0:863:ed1a::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 2620:0:863:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 2620:0:863:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip addr add 10.128.0.15/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs4005 ip route add default via 10.128.0.2
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip addr add 198.35.26.112/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip addr add 2620:0:863:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip addr add 10.128.0.16/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs4006 ip route add default via 10.128.0.2
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 198.35.26.112/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 198.35.26.96/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 198.35.26.97/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 198.35.26.98/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 2620:0:863:ed1a::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 2620:0:863:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 2620:0:863:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 2620:0:863:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip addr add 10.128.0.17/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs4007 ip route add default via 10.128.0.2
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 103.102.166.224/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 103.102.166.225/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 103.102.166.226/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 2001:df2:e500:ed1a::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 2001:df2:e500:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 2001:df2:e500:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip addr add 10.132.0.11/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs5001 ip route add default via 10.132.0.2
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip addr add 103.102.166.240/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip addr add 2001:df2:e500:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip addr add 10.132.0.12/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs5002 ip route add default via 10.132.0.2
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 103.102.166.224/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 103.102.166.225/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 103.102.166.226/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 103.102.166.240/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 2001:df2:e500:ed1a::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 2001:df2:e500:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 2001:df2:e500:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 2001:df2:e500:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip addr add 10.132.0.13/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs5003 ip route add default via 10.132.0.2
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 91.198.174.192/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 91.198.174.193/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 91.198.174.194/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 2620:0:862:ed1a::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 2620:0:862:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 2620:0:862:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip addr add 10.20.0.15/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs3005 ip route add default via 10.20.0.2
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip addr add 91.198.174.208/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip addr add 2620:0:862:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip addr add 10.20.0.16/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs3006 ip route add default via 10.20.0.2
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 91.198.174.192/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 91.198.174.193/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 91.198.174.194/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 91.198.174.208/32 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 2620:0:862:ed1a::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 2620:0:862:ed1a::2:b/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 2620:0:862:ed1a::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 2620:0:862:ed1a::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip route del default via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip route add 192.168.122.1 via 172.20.20.1
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip link set alias eth1 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip addr add 10.20.0.17/24 dev eth1
+ sudo ip netns exec clab-wmf-lab-lvs3007 ip route add default via 10.20.0.2
+ ../junos_push_lvs_conf.py -c ../lvs_config.json
Pushed LVS config for lvs1017.
Pushed LVS config for lvs1018.
Pushed LVS config for lvs1019.
Pushed LVS config for lvs1020.
Pushed LVS config for lvs2007.
Pushed LVS config for lvs2008.
Pushed LVS config for lvs2009.
Pushed LVS config for lvs2010.
Pushed LVS config for lvs3005.
Pushed LVS config for lvs3006.
Pushed LVS config for lvs3007.
Pushed LVS config for lvs4005.
Pushed LVS config for lvs4006.
Pushed LVS config for lvs4007.
Pushed LVS config for lvs5001.
Pushed LVS config for lvs5002.
Pushed LVS config for lvs5003.

root@debiantest:~/wmf-lab/output# 
```
</details>

##### Connecting to crpd instances
  
Once started you can see the status of the containers as follows:
```
root@debiantest:~# sudo clab inspect -n wmf-lab
+----+--------------------------------+--------------+---------------+-------+---------+-----------------+-----------------------+
| #  |              Name              | Container ID |     Image     | Kind  |  State  |  IPv4 Address   |     IPv6 Address      |
+----+--------------------------------+--------------+---------------+-------+---------+-----------------+-----------------------+
|  1 | clab-wmf-lab-asw-a-codfw       | e7f0a956561c | debian:latest | linux | running | 172.20.20.14/24 | 2001:172:20:20::e/64  |
|  2 | clab-wmf-lab-asw-b-codfw       | 5a9a8d239881 | debian:latest | linux | running | 172.20.20.10/24 | 2001:172:20:20::a/64  |
|  3 | clab-wmf-lab-asw-c-codfw       | 6735671fd9b4 | debian:latest | linux | running | 172.20.20.8/24  | 2001:172:20:20::8/64  |
|  4 | clab-wmf-lab-asw-d-codfw       | 5ccfda3bd0aa | debian:latest | linux | running | 172.20.20.13/24 | 2001:172:20:20::d/64  |
|  5 | clab-wmf-lab-asw1-b12-drmrs    | fd20c110872e | crpd          | crpd  | running | 172.20.20.47/24 | 2001:172:20:20::2f/64 |
|  6 | clab-wmf-lab-asw1-b13-drmrs    | 54166a7e0507 | crpd          | crpd  | running | 172.20.20.27/24 | 2001:172:20:20::1b/64 |
|  7 | clab-wmf-lab-asw1-eqsin        | 303f3dd38341 | debian:latest | linux | running | 172.20.20.5/24  | 2001:172:20:20::5/64  |
|  8 | clab-wmf-lab-asw2-a-eqiad      | 3c7a575263ed | debian:latest | linux | running | 172.20.20.4/24  | 2001:172:20:20::4/64  |
|  9 | clab-wmf-lab-asw2-b-eqiad      | ad7d8983da85 | debian:latest | linux | running | 172.20.20.9/24  | 2001:172:20:20::9/64  |
| 10 | clab-wmf-lab-asw2-c-eqiad      | a58edac188b2 | debian:latest | linux | running | 172.20.20.11/24 | 2001:172:20:20::b/64  |
| 11 | clab-wmf-lab-asw2-d-eqiad      | a2ff691f6a78 | debian:latest | linux | running | 172.20.20.12/24 | 2001:172:20:20::c/64  |
| 12 | clab-wmf-lab-asw2-esams        | 237c05a5dacc | debian:latest | linux | running | 172.20.20.6/24  | 2001:172:20:20::6/64  |
| 13 | clab-wmf-lab-asw2-ulsfo        | d3608834f0c8 | debian:latest | linux | running | 172.20.20.3/24  | 2001:172:20:20::3/64  |
| 14 | clab-wmf-lab-cloudsw1-c8-eqiad | 98a934b05b6f | debian:latest | linux | running | 172.20.20.7/24  | 2001:172:20:20::7/64  |
| 15 | clab-wmf-lab-cloudsw1-d5-eqiad | 250c03ec81a0 | debian:latest | linux | running | 172.20.20.2/24  | 2001:172:20:20::2/64  |
| 16 | clab-wmf-lab-cr1-codfw         | 1d005d041a77 | crpd          | crpd  | running | 172.20.20.31/24 | 2001:172:20:20::1f/64 |
| 17 | clab-wmf-lab-cr1-drmrs         | 36f18adebd43 | crpd          | crpd  | running | 172.20.20.20/24 | 2001:172:20:20::14/64 |
| 18 | clab-wmf-lab-cr1-eqiad         | 7d5f09287ea7 | crpd          | crpd  | running | 172.20.20.49/24 | 2001:172:20:20::31/64 |
| 19 | clab-wmf-lab-cr2-codfw         | 90b587d37b39 | crpd          | crpd  | running | 172.20.20.54/24 | 2001:172:20:20::36/64 |
| 20 | clab-wmf-lab-cr2-drmrs         | 4751ab8f389a | crpd          | crpd  | running | 172.20.20.29/24 | 2001:172:20:20::1d/64 |
| 21 | clab-wmf-lab-cr2-eqdfw         | 3ab9af4009dd | crpd          | crpd  | running | 172.20.20.41/24 | 2001:172:20:20::29/64 |
| 22 | clab-wmf-lab-cr2-eqiad         | 04fecaf6e3c4 | crpd          | crpd  | running | 172.20.20.55/24 | 2001:172:20:20::37/64 |
| 23 | clab-wmf-lab-cr2-eqord         | b944cd7acbb5 | crpd          | crpd  | running | 172.20.20.45/24 | 2001:172:20:20::2d/64 |
| 24 | clab-wmf-lab-cr2-eqsin         | 4a968656c51e | crpd          | crpd  | running | 172.20.20.26/24 | 2001:172:20:20::1a/64 |
| 25 | clab-wmf-lab-cr2-esams         | 4c1f69d59f58 | crpd          | crpd  | running | 172.20.20.28/24 | 2001:172:20:20::1c/64 |
| 26 | clab-wmf-lab-cr3-eqsin         | 8ef181208793 | crpd          | crpd  | running | 172.20.20.16/24 | 2001:172:20:20::10/64 |
| 27 | clab-wmf-lab-cr3-esams         | 816eec6f0616 | crpd          | crpd  | running | 172.20.20.36/24 | 2001:172:20:20::24/64 |
| 28 | clab-wmf-lab-cr3-knams         | 156563e8fe50 | crpd          | crpd  | running | 172.20.20.32/24 | 2001:172:20:20::20/64 |
| 29 | clab-wmf-lab-cr3-ulsfo         | a579d85acde4 | crpd          | crpd  | running | 172.20.20.17/24 | 2001:172:20:20::11/64 |
| 30 | clab-wmf-lab-cr4-ulsfo         | 772a99fd9538 | crpd          | crpd  | running | 172.20.20.52/24 | 2001:172:20:20::34/64 |
| 31 | clab-wmf-lab-lsw1-e1-eqiad     | d7ffe8901b8e | crpd          | crpd  | running | 172.20.20.50/24 | 2001:172:20:20::32/64 |
| 32 | clab-wmf-lab-lsw1-f1-eqiad     | e4f087443273 | crpd          | crpd  | running | 172.20.20.33/24 | 2001:172:20:20::21/64 |
| 33 | clab-wmf-lab-lvs1017           | d5fe3b0982c9 | crpd          | crpd  | running | 172.20.20.35/24 | 2001:172:20:20::23/64 |
| 34 | clab-wmf-lab-lvs1018           | 24314c6db697 | crpd          | crpd  | running | 172.20.20.44/24 | 2001:172:20:20::2c/64 |
| 35 | clab-wmf-lab-lvs1019           | c6f15fdfaec6 | crpd          | crpd  | running | 172.20.20.59/24 | 2001:172:20:20::3b/64 |
| 36 | clab-wmf-lab-lvs1020           | 9479bd455d42 | crpd          | crpd  | running | 172.20.20.18/24 | 2001:172:20:20::12/64 |
| 37 | clab-wmf-lab-lvs2007           | 9eedb3b77589 | crpd          | crpd  | running | 172.20.20.21/24 | 2001:172:20:20::15/64 |
| 38 | clab-wmf-lab-lvs2008           | 1fb011c73a85 | crpd          | crpd  | running | 172.20.20.38/24 | 2001:172:20:20::26/64 |
| 39 | clab-wmf-lab-lvs2009           | ff7fb7523228 | crpd          | crpd  | running | 172.20.20.37/24 | 2001:172:20:20::25/64 |
| 40 | clab-wmf-lab-lvs2010           | 53db6b3f7805 | crpd          | crpd  | running | 172.20.20.19/24 | 2001:172:20:20::13/64 |
| 41 | clab-wmf-lab-lvs3005           | 086dbd822759 | crpd          | crpd  | running | 172.20.20.46/24 | 2001:172:20:20::2e/64 |
| 42 | clab-wmf-lab-lvs3006           | 638d1d63b65a | crpd          | crpd  | running | 172.20.20.34/24 | 2001:172:20:20::22/64 |
| 43 | clab-wmf-lab-lvs3007           | 58f651924784 | crpd          | crpd  | running | 172.20.20.57/24 | 2001:172:20:20::39/64 |
| 44 | clab-wmf-lab-lvs4005           | 18c80977ee42 | crpd          | crpd  | running | 172.20.20.24/24 | 2001:172:20:20::18/64 |
| 45 | clab-wmf-lab-lvs4006           | 16e9e64028cd | crpd          | crpd  | running | 172.20.20.40/24 | 2001:172:20:20::28/64 |
| 46 | clab-wmf-lab-lvs4007           | d0c37f3116d3 | crpd          | crpd  | running | 172.20.20.23/24 | 2001:172:20:20::17/64 |
| 47 | clab-wmf-lab-lvs5001           | c78133c04782 | crpd          | crpd  | running | 172.20.20.51/24 | 2001:172:20:20::33/64 |
| 48 | clab-wmf-lab-lvs5002           | 652c699937aa | crpd          | crpd  | running | 172.20.20.58/24 | 2001:172:20:20::3a/64 |
| 49 | clab-wmf-lab-lvs5003           | b2f709a0fbb7 | crpd          | crpd  | running | 172.20.20.30/24 | 2001:172:20:20::1e/64 |
| 50 | clab-wmf-lab-mr1-codfw         | f2c1bc03be26 | crpd          | crpd  | running | 172.20.20.56/24 | 2001:172:20:20::38/64 |
| 51 | clab-wmf-lab-mr1-eqiad         | f26d0ec62df5 | crpd          | crpd  | running | 172.20.20.53/24 | 2001:172:20:20::35/64 |
| 52 | clab-wmf-lab-mr1-eqsin         | d80f67f4fbd2 | crpd          | crpd  | running | 172.20.20.15/24 | 2001:172:20:20::f/64  |
| 53 | clab-wmf-lab-mr1-esams         | 0afd3045ca05 | crpd          | crpd  | running | 172.20.20.48/24 | 2001:172:20:20::30/64 |
| 54 | clab-wmf-lab-mr1-ulsfo         | 3578fe3fda4c | crpd          | crpd  | running | 172.20.20.43/24 | 2001:172:20:20::2b/64 |
| 55 | clab-wmf-lab-pfw3a-codfw       | 6036afa171ce | crpd          | crpd  | running | 172.20.20.22/24 | 2001:172:20:20::16/64 |
| 56 | clab-wmf-lab-pfw3a-eqiad       | b103d9142c56 | crpd          | crpd  | running | 172.20.20.39/24 | 2001:172:20:20::27/64 |
| 57 | clab-wmf-lab-pfw3b-codfw       | b2306543dae6 | crpd          | crpd  | running | 172.20.20.42/24 | 2001:172:20:20::2a/64 |
| 58 | clab-wmf-lab-pfw3b-eqiad       | cf8493e12f68 | crpd          | crpd  | running | 172.20.20.25/24 | 2001:172:20:20::19/64 |
+----+--------------------------------+--------------+---------------+-------+---------+-----------------+-----------------------+
```

Entries in /etc/hosts should also have been written to direct WMF production hostnames to the container management IPs, for example:
```
root@debiantest:~# grep cr1-eqiad /etc/hosts
172.20.20.49	clab-wmf-lab-cr1-eqiad	cr1-eqiad.wikimedia.org
2001:172:20:20::31	clab-wmf-lab-cr1-eqiad	cr1-eqiad.wikimedia.org
```
    
You can connect to any via SSH using these hostnames:
```
root@debiantest:~# ssh cr1-eqiad.wikimedia.org
Welcome to Ubuntu 18.04.1 LTS (GNU/Linux 5.10.0-18-amd64 x86_64)

 * Documentation:  https://help.ubuntu.com
 * Management:     https://landscape.canonical.com
 * Support:        https://ubuntu.com/advantage

This system has been minimized by removing packages and content that are
not required on a system that users do not log into.

To restore this content, you can run the 'unminimize' command.

===>
           Containerized Routing Protocols Daemon (CRPD)
 Copyright (C) 2018-19, Juniper Networks, Inc. All rights reserved.
                                                                    <===

root@cr1-eqiad:~# 
```
                                                                                       
Run 'cli' once connected to access the JunOS command line.

                                                                                       
<details>
  <summary>Example output - click to expand</summary>
  
```
root@cr1-eqiad:~# cli
root@cr1-eqiad> 

root@cr1-eqiad> show configuration 
## Last commit: 2022-09-26 17:00:12 UTC by root
version 20191212.201431_builder.r1074901;
system {
    root-authentication {
        encrypted-password "$6$lB5c6$Zeud8c6IhCTE6hnZxXBl3ZMZTC2hOx9pxxYUWTHKW1oC32SATWLMH2EXarxWS5k685qMggUfFur1lq.o4p4cg1"; ## SECRET-DATA
    }
}

root@cr1-eqiad> show interfaces routing 
Interface        State Addresses
xe-3_0_6         Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fe6a:dfc4
                       INET  206.126.236.106
                       INET6 2001:504:0:2:0:1:4907:2
ae0              Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fe5d:1e21
                       INET  208.80.154.193
                       INET6 2620:0:861:fe00::1
et-1_0_2.100     Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fe49:f587
                       INET  10.66.0.8
                       INET6 2620:0:861:fe07::1
ae1.401          Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fedd:4676
                       INET  208.80.154.204
                       INET6 2620:0:861:fe04::1
lsi              Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::fcc5:13ff:fee2:3a64
xe-4_2_2.16      Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fe33:aba
                       INET  185.15.58.147
                       INET6 2a02:ec80:600:fe04::2
xe-4_2_2.13      Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fe8a:d856
                       INET  91.198.174.250
                       INET6 2620:0:862:fe06::1
xe-4_2_2.12      Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:feec:255f
                       INET  208.80.153.214
                       INET6 2620:0:860:fe08::1
xe-4_2_0         Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:feb2:3a4a
                       INET  208.80.153.220
                       INET6 2620:0:860:fe01::1
xe-3_1_7         Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:feb4:d47e
                       INET  208.80.154.200
xe-3_1_4         Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:fefe:dec8
                       INET  185.15.58.138
                       INET6 2a02:ec80:600:fe01::1
xe-3_0_4.1102    Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.154.210
                       INET6 fe80::a8c1:abff:fef6:7abc
xe-3_0_4.1000    Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.147.16
                       INET6 2620:0:861:fe09::1
                       INET6 fe80::a8c1:abff:fef6:7abc
xe-3_0_4         Up    MPLS  enabled
                       ISO   enabled
lo.0             Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.154.196
                       INET6 2620:0:861:ffff::1
gr-4_3_0.1       Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::a8c1:abff:feab:d21b
                       INET  103.102.166.147
                       INET6 2001:df2:e500:fe07::2
eth0             Up    MPLS  enabled
                       ISO   enabled
                       INET  172.20.20.49
                       INET6 2001:172:20:20::31
                       INET6 fe80::42:acff:fe14:1431
ae4.1023         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.53.2
                       INET6 2620:0:861:108:fe00::1
                       INET6 fe80::a8c1:abff:fe49:f02f
ae4.1020         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.48.2
                       INET6 2620:0:861:107:fe00::1
                       INET6 fe80::a8c1:abff:fe49:f02f
ae4.1004         Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.155.98
                       INET6 2620:0:861:4:fe00::1
                       INET6 fe80::a8c1:abff:fe49:f02f
ae4              Up    MPLS  enabled
                       ISO   enabled
ae3.1119         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.37.2
                       INET6 2620:0:861:119:fe00::1
                       INET6 fe80::a8c1:abff:febf:dad7
ae3.1022         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.36.2
                       INET6 2620:0:861:106:fe00::1
                       INET6 fe80::a8c1:abff:febf:dad7
ae3.1019         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.32.2
                       INET6 2620:0:861:103:fe00::1
                       INET6 fe80::a8c1:abff:febf:dad7
ae3.1003         Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.154.66
                       INET6 2620:0:861:3:fe00::1
                       INET6 fe80::a8c1:abff:febf:dad7
ae3              Up    MPLS  enabled
                       ISO   enabled
ae2.1202         Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.155.66
                       INET6 2620:0:861:202:fe00::1
                       INET6 fe80::a8c1:abff:fe9a:12a8
ae2.1021         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.21.2
                       INET6 2620:0:861:105:fe00::1
                       INET6 fe80::a8c1:abff:fe9a:12a8
ae2.1018         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.16.2
                       INET6 2620:0:861:102:fe00::1
                       INET6 fe80::a8c1:abff:fe9a:12a8
ae2.1002         Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.154.130
                       INET6 2620:0:861:2:fe00::1
                       INET6 fe80::a8c1:abff:fe9a:12a8
ae2              Up    MPLS  enabled
                       ISO   enabled    
ae1.1117         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.4.2
                       INET6 2620:0:861:117:fe00::1
                       INET6 fe80::a8c1:abff:fe4b:3b27
ae1.1030         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.5.2
                       INET6 2620:0:861:104:fe00::1
                       INET6 fe80::a8c1:abff:fe4b:3b27
ae1.1017         Up    MPLS  enabled
                       ISO   enabled
                       INET  10.64.0.2
                       INET6 2620:0:861:101:fe00::1
                       INET6 fe80::a8c1:abff:fe4b:3b27
ae1.1001         Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.154.2
                       INET6 2620:0:861:1:fe00::1
                       INET6 fe80::a8c1:abff:fe4b:3b27
ae1              Up    MPLS  enabled
                       ISO   enabled

```
</details>                                                                                       

### Configure devices with Homer

As devices are reachable on thier normal hostnames, and we have a local copy of the public and mock private Homer repos (with some modifcations to allow them work with crpd), we can run Homer to configure the containerized devices so they will match production.  

#### Homer Configuration    
    
Homer, and the netbox plugin, should be installed and configured as normal.  It is strongly advised to this the correct way, and not repeat the authors [idiotic steps](https://phabricator.wikimedia.org/P34916).

The file ```/etc/homer/config.yaml``` should be created as usual.  Important elements that are required here are:
    
- Path to the correct mock private and public repos
- Correct plugin reference for the Netbox plugin
- 'transports' configured with username 'root' and referencing correct ssh config file
    
You may find [this example](https://phabricator.wikimedia.org/P34917) useful.
    
#### Run Homer
    
Homer can be run for the simulated core routers as follows:
```
homer "cr*" commit "configure clab devices"
```
    
As ususal you should be prompted to confirm the changes on each device.  When complete you can connect to any of the reconfigured crpd nodes and see the changes.  For instance OSPF interfaces should be up and match the live network:
```
root@cr1-eqiad> show ospf neighbor 
Address          Interface              State           ID               Pri  Dead
208.80.154.194   ae0                    Full            208.80.154.197   128    38
185.15.58.139    xe-3_1_4               Full            185.15.58.128    128    39
208.80.153.221   xe-4_2_0               Full            208.80.153.192   128    31
208.80.153.215   xe-4_2_2.12            Full            208.80.153.198   128    36
91.198.174.251   xe-4_2_2.13            Full            91.198.174.246   128    37
185.15.58.146    xe-4_2_2.16            Full            185.15.58.129    128    31
```
    
#### Add additional config to containerlab nodes saved from production
    
Assuming you have run the ```junos_get_live_conf.py``` script from a machine with production access, transfer the "junos_data" directory to the wmf-lab folder on the machine running the lab.  You can then run ```junos_push_saved_data.py``` to add this additional config to the lab devices.
    
NOTE: There is a [bug](https://github.com/Juniper/py-junos-eznc/issues/1208) in how cRPD reports the JunOS version in use, which prevents retrieving cRPD configs in JSON format using PyEz, which tries to verify the version is recent enough to support this.  If you hit this you may see this error message:
```
root@debiantest:~/wmf-lab# ./junos_push_saved_data.py 
/usr/local/lib/python3.9/dist-packages/jnpr/junos/device.py:886: RuntimeWarning: Native JSON support is only from 14.2 onwards
```
    
The simple solution until this is fixed is to modify the device.py file just before the line it lists, and change ```ver_info.major[0] >= 15``` to ```ver_info.major[0] >= 0```.  This will cause it to proceed regardless of JunOS version, and the script should run:
```
root@debiantest:~/wmf-lab# ./junos_push_saved_data.py 
Pushed revised config for cr1-codfw.
Pushed revised config for cr1-drmrs.
Pushed revised config for cr1-eqiad.
Pushed revised config for cr2-codfw.
Pushed revised config for cr2-drmrs.
Pushed revised config for cr2-eqdfw.
Pushed revised config for cr2-eqiad.
Pushed revised config for cr2-eqord.
Pushed revised config for cr2-eqsin.
Pushed revised config for cr2-esams.
Pushed revised config for cr3-eqsin.
Pushed revised config for cr3-esams.
Pushed revised config for cr3-knams.
Pushed revised config for cr3-ulsfo.
Pushed revised config for cr4-ulsfo.
```
    
With this configuration added we should now also see Confed BGP peerings up and running:
```
root@cr1-eqiad> show bgp summary | match Estab 
10.64.0.80            64600        130        127       0       0       18:36 Establ
10.64.16.60           64600        130        127       0       0       18:32 Establ
10.64.32.17           64600        132        130       0       0       18:52 Establ
10.64.48.72           64600        131        128       0       0       18:48 Establ
91.198.174.251        65003         46         43       0       0        1:22 Establ
185.15.58.139         65006         70         25       0       0        1:40 Establ
185.15.58.146         65006         77         25       0       0        1:34 Establ
198.35.26.192         65004         35         29       0       0        1:18 Establ
198.35.26.193         65004         19         30       0       0        1:16 Establ
208.80.153.192        65002         36         50       0       0        1:33 Establ
208.80.153.193        65002         45         67       0       0        1:28 Establ
208.80.154.197        65001         25         23       0       0        1:27 Establ
208.80.154.198        65020         53         67       0       0        1:30 Establ
2620:0:861:ffff::2       65001         29         43       0       0        1:30 Establ
2a02:ec80:600:fe01::2       65006         32         40       0       0        1:36 Establ
2a02:ec80:600:fe04::1       65006         42         42       0       0        1:23 Establ
```

    

### Linux shell inside container

It is possible to connect to the bash shell of any of the crpd containers using SSH as described previously.  You can also use "docker exec" to spawn a new bash shell inside the container.  In both cases the resulting shell runs inside the container with the limited userspace available.
  
As the primary reason for using the containers is network isolation, it can be useful to execute a new shell within the network namespace, rather than fully inside the container.  For example:
  
```
cathal@officepc:~$ sudo ip netns exec clab-wmf-lab-cr1-codfw bash
root@officepc:/home/cathal# 
```
  
Netns names created by clab match the names shown under "clab inspect" above.  Or you can use "sudo ip netns list" to see them.
  
Once you have a shell inside the container you can use all userspace tools that are available in the OS:
  
```
root@debiantest:~# sudo ip netns exec clab-wmf-lab-cr2-codfw bash
root@debiantest:~# mtr -b -w -c 5 91.198.174.192
Start: 2022-09-26T19:49:22+0100
HOST: debiantest                                        Loss%   Snt   Last   Avg  Best  Wrst StDev
  1.|-- xe-0-1-0.cr2-eqord.wikimedia.org (208.80.153.222)  0.0%     5    0.0   0.1   0.0   0.1   0.0
  2.|-- xe-4-2-0.cr2-eqiad.wikimedia.org (208.80.154.208)  0.0%     5    0.1   0.1   0.1   0.1   0.0
  3.|-- xe-0-1-3.cr2-esams.wikimedia.org (91.198.174.249)  0.0%     5    0.1   0.1   0.1   0.1   0.0
  4.|-- text-lb.esams.wikimedia.org (91.198.174.192)       0.0%     5    0.1   0.1   0.1   0.1   0.0

root@debiantest:~# 
root@debiantest:~# ip -br addr show | sort -V
ae0@if1525       UP             208.80.153.219/31 2620:0:860:fe00::2/64 fe80::a8c1:abff:fe52:6507/64 
ae1.402@if1516   UP             208.80.153.208/31 2620:0:860:fe06::1/64 fe80::a8c1:abff:fe8c:7d32/64 
ae1.2001@ae1     UP             208.80.153.3/27 2620:0:860:1:fe00::2/64 fe80::a8c1:abff:fe08:914a/64 
ae1.2017@ae1     UP             10.192.0.3/22 2620:0:860:101:fe00::2/64 fe80::a8c1:abff:fe08:914a/64 
ae1.2201@ae1     UP             208.80.152.243/28 2620:0:860:201:fe00::2/64 fe80::a8c1:abff:fe08:914a/64 
ae1@if1508       UP             
ae2.2002@ae2     UP             208.80.153.35/27 2620:0:860:2:fe00::2/64 fe80::a8c1:abff:fe75:b7e0/64 
ae2.2018@ae2     UP             10.192.16.3/22 2620:0:860:102:fe00::2/64 fe80::a8c1:abff:fe75:b7e0/64 
ae2.2118@ae2     UP             10.192.20.3/24 2620:0:860:118:fe00::2/64 fe80::a8c1:abff:fe75:b7e0/64 
ae2.2120@ae2     UP             208.80.153.187/29 fe80::a8c1:abff:fe75:b7e0/64 
ae2.2122@ae2     UP             10.192.21.3/24 2620:0:860:122:fe00::2/64 fe80::a8c1:abff:fe75:b7e0/64 
ae2@if1520       UP             
ae3.2003@ae3     UP             208.80.153.67/27 2620:0:860:3:fe00::2/64 fe80::a8c1:abff:fea1:6bda/64 
ae3.2019@ae3     UP             10.192.32.3/22 2620:0:860:103:fe00::2/64 fe80::a8c1:abff:fea1:6bda/64 
ae3@if1512       UP             
ae4.2004@ae4     UP             208.80.153.99/27 2620:0:860:4:fe00::2/64 fe80::a8c1:abff:fef2:3c5e/64 
ae4.2020@ae4     UP             10.192.48.3/22 2620:0:860:104:fe00::2/64 fe80::a8c1:abff:fef2:3c5e/64 
ae4@if1518       UP             
eth0@if1353      UP             172.20.20.54/24 2001:172:20:20::36/64 fe80::42:acff:fe14:1436/64 
lo               UNKNOWN        127.0.0.1/8 208.80.153.193/32 2620:0:860:ffff::2/128 ::1/128 
lsi              UNKNOWN        fe80::3ccf:95ff:feef:64f/64 
xe-1_0_1_0@if1510 UP             208.80.153.202/31 fe80::a8c1:abff:fe9c:b3be/64 
xe-1_0_1_1@if1515 UP             208.80.153.223/31 2620:0:860:fe02::2/64 fe80::a8c1:abff:fefb:bbb4/64 
xe-1_1_1_1@if1522 UP             208.80.154.215/31 2620:0:861:fe06::2/64 fe80::a8c1:abff:feab:32a9/64 
xe-1_1_1_2@if1527 UP             208.80.153.212/31 2620:0:860:fe04::1/64 fe80::a8c1:abff:fe60:e262/64 

root@debiantest:~# 
root@debiantest:~# tcpdump -l -nn -i xe-1_0_1_1 
tcpdump: verbose output suppressed, use -v[v]... for full protocol decode
listening on xe-1_0_1_1, link-type EN10MB (Ethernet), snapshot length 262144 bytes
19:55:14.222109 IP6 fe80::a8c1:abff:fefb:bbb4 > ff02::5: OSPFv3, Hello, length 40
19:55:14.788824 IP 208.80.153.223 > 224.0.0.5: OSPFv2, Hello, length 60
19:55:14.976436 IP 208.80.153.222 > 224.0.0.5: OSPFv2, LS-Update, length 64
19:55:17.844495 IP 208.80.153.193.51511 > 208.80.154.198.179: Flags [P.], seq 210047072:210047091, ack 91513286, win 15008, options [nop,nop,TS val 753967328 ecr 552261362], length 19: BGP
19:55:17.844512 IP 208.80.154.198.179 > 208.80.153.193.51511: Flags [.], ack 19, win 15466, options [nop,nop,TS val 552280075 ecr 753967328], length 0
19:55:18.887949 IP 208.80.153.222 > 224.0.0.5: OSPFv2, Hello, length 60
19:55:21.501512 IP6 fe80::a8c1:abff:feab:fe45 > ff02::5: OSPFv3, Hello, length 40    
```

### Stopping the lab
  
Run the stop script top stop the lab and clean up the bridge interfaces
```
sudo ./stop_wmf-lab.sh
```

<details>
  <summary>Example output - click to expand</summary>
  
```  
root@debiantest:~/wmf-lab/output# ./stop_wmf-lab.sh 
+ sudo clab destroy -t wmf-lab.yaml
INFO[0000] Parsing & checking topology file: wmf-lab.yaml 
INFO[0000] Destroying lab: wmf-lab                      
INFO[0002] Removed container: clab-wmf-lab-asw2-c-eqiad 
INFO[0003] Removed container: clab-wmf-lab-mr1-ulsfo    
INFO[0003] Removed container: clab-wmf-lab-lvs2009      
INFO[0003] Removed container: clab-wmf-lab-lvs3005      
INFO[0003] Removed container: clab-wmf-lab-mr1-esams    
INFO[0003] Removed container: clab-wmf-lab-cr2-eqdfw    
INFO[0004] Removed container: clab-wmf-lab-asw2-d-eqiad 
INFO[0004] Removed container: clab-wmf-lab-cr2-eqsin    
INFO[0004] Removed container: clab-wmf-lab-mr1-eqiad    
INFO[0004] Removed container: clab-wmf-lab-asw2-a-eqiad 
INFO[0004] Removed container: clab-wmf-lab-pfw3a-codfw  
INFO[0004] Removed container: clab-wmf-lab-asw1-b12-drmrs 
INFO[0004] Removed container: clab-wmf-lab-cloudsw1-c8-eqiad 
INFO[0004] Removed container: clab-wmf-lab-cr3-knams    
INFO[0004] Removed container: clab-wmf-lab-cr4-ulsfo    
INFO[0004] Removed container: clab-wmf-lab-lvs5003      
INFO[0004] Removed container: clab-wmf-lab-lvs3006      
INFO[0004] Removed container: clab-wmf-lab-asw-d-codfw  
INFO[0004] Removed container: clab-wmf-lab-pfw3b-eqiad  
INFO[0004] Removed container: clab-wmf-lab-lvs2010      
INFO[0005] Removed container: clab-wmf-lab-asw-c-codfw  
INFO[0005] Removed container: clab-wmf-lab-asw-a-codfw  
INFO[0005] Removed container: clab-wmf-lab-cloudsw1-d5-eqiad 
INFO[0005] Removed container: clab-wmf-lab-asw-b-codfw  
INFO[0005] Removed container: clab-wmf-lab-lvs1017      
INFO[0005] Removed container: clab-wmf-lab-lvs4006      
INFO[0005] Removed container: clab-wmf-lab-mr1-codfw    
INFO[0005] Removed container: clab-wmf-lab-cr1-drmrs    
INFO[0005] Removed container: clab-wmf-lab-lvs3007      
INFO[0005] Removed container: clab-wmf-lab-asw2-ulsfo   
INFO[0005] Removed container: clab-wmf-lab-cr3-esams    
INFO[0006] Removed container: clab-wmf-lab-lsw1-e1-eqiad 
INFO[0006] Removed container: clab-wmf-lab-lvs1019      
INFO[0006] Removed container: clab-wmf-lab-cr2-eqiad    
INFO[0006] Removed container: clab-wmf-lab-pfw3a-eqiad  
INFO[0006] Removed container: clab-wmf-lab-lsw1-f1-eqiad 
INFO[0006] Removed container: clab-wmf-lab-cr2-codfw    
INFO[0006] Removed container: clab-wmf-lab-lvs1020      
INFO[0006] Removed container: clab-wmf-lab-asw1-eqsin   
INFO[0006] Removed container: clab-wmf-lab-lvs1018      
INFO[0006] Removed container: clab-wmf-lab-lvs4007      
INFO[0006] Removed container: clab-wmf-lab-lvs2008      
INFO[0006] Removed container: clab-wmf-lab-mr1-eqsin    
INFO[0006] Removed container: clab-wmf-lab-asw1-b13-drmrs 
INFO[0006] Removed container: clab-wmf-lab-asw2-b-eqiad 
INFO[0006] Removed container: clab-wmf-lab-cr2-esams    
INFO[0006] Removed container: clab-wmf-lab-lvs5001      
INFO[0006] Removed container: clab-wmf-lab-cr2-eqord    
INFO[0007] Removed container: clab-wmf-lab-cr2-drmrs    
INFO[0007] Removed container: clab-wmf-lab-cr3-ulsfo    
INFO[0007] Removed container: clab-wmf-lab-lvs5002      
INFO[0007] Removed container: clab-wmf-lab-lvs4005      
INFO[0007] Removed container: clab-wmf-lab-cr1-eqiad    
INFO[0007] Removed container: clab-wmf-lab-cr1-codfw    
INFO[0007] Removed container: clab-wmf-lab-pfw3b-codfw  
INFO[0007] Removed container: clab-wmf-lab-cr3-eqsin    
INFO[0007] Removed container: clab-wmf-lab-asw2-esams   
INFO[0007] Removed container: clab-wmf-lab-lvs2007      
INFO[0007] Removing containerlab host entries from /etc/hosts file 
```
</details>   
