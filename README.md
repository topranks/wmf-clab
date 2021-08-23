# wmf-lab

![wmf-lab topology](https://github.com/topranks/wmf-lab/blob/main/clab_wmf-lab.png)

Script to create a topology file for [containerlab](https://containerlab.srlinux.dev/) to simulate the WMF network.

The script use WMF Netbox, and homer public repo YAML files, to collect information on devices running on the WMF network and create a topology to simulate them using docker/containerlab, with Juniper's [crpd](https://www.juniper.net/documentation/us/en/software/crpd/crpd-deployment/topics/concept/understanding-crpd.html) container image as router nodes.

As crpd is a lightweight container it is possible to run multiple nodes on even the most modest hardware.

### Approach 

Juniper's crpd is basically just their routing-stack software (i.e. OSPF, BGP, IS-IS implementation) deployed in a container.  Unlike virtual-machine based platforms such as [vMX](https://www.juniper.net/us/en/products/routers/mx-series/vmx-virtual-router-software.html), it does not implement any dataplane funcationality.  Instead it runs the various protocols and builds the per-protocol and global RIB, and then uses the normal Linux [netlink](https://en.wikipedia.org/wiki/Netlink) interface to program routes into the Linux network namespace of the crpd container.  This means that, while the OSPF, BGP and other protocol implemenations should operate exactly as on a real Juniper router, packet encapsulation and forwarding is being performed by Linux.  As such crpd is only suitable for testing some things (such as changes to OSPF metrics) but not others (like how MPLS label stacks or Vlan tags are added to packets).

#### Integration with containerlab

##### Interface Addressing

Containerlab supports crpd natively, however it provides no mechanism to configure IP addresses on the veth interfaces that exist within each containerized node.  For most of the containerized network nodes it supports this is not an issue - most allow configuration of interface addresses through their CLI, Netconf etc.  That is not true with crpd, however.  Instead crpd expects to run on a Linux host / container with all interface IPs already configured, and allows you to configure OSPF, BGP etc. which will operate over those interfaces.

To overcome this the "start" shell script uses the Linux [ip](https://manpages.debian.org/unstable/iproute2/ip.8.en.html) command to add interface IPs as required once the containers have been created by clab.

##### Interface Naming

Real Juniper devices operated by WMF use standard JunOS interface naming such as 'ge-0/0/0', 'et-5/0/1' etc.  Containerlab requires interface names to be similar to "eth0", "eth1" etc.  As such it is not possible to create the simulated router nodes with the same interface naming as the actual network.  Instead a translation is done and "eth" interfaces are added to the containers as needed, each representing a real-world device interface.  The real-world interface name is added as an "alias" to the interface by the start script when initiating the lab.


##### Modelling switches

WMF routers commonly have connections to layer-2 switches, typically with multiple 802.1q sub-interfaces on each link connecting to a different Vlan on the switch.  Many of these are configured as OSPF 'passive' interfaces, or have BGP configured on them to servers (such as load-balancers).

Currently the lab deploys a containerlab node of the [bridge](https://containerlab.srlinux.dev/manual/kinds/bridge/) kind to represent required L2 devices.  A standard (rather than Vlan-aware) bridge is created, but this still allows Vlan tags to be used, which get filtered by each container as frames are received and delivered to the correct sub-interfaces (this works fine, minus the full isolation of frames through the bridge).  Clab devices of kind bridge need to have an actual bridge device created in the default Linux network namespace of the device running the lab in advance of deployment to work.  The start script creates these in advance to ensure things work, the stop script removes them.

Sub-interfaces on ports connecting to these simulated switches, within the crpd containers, are also created by the start script.  Containerlab does not provide a mechanism to add these itself.  Again the addresses required for each are added by the start script during deploy.

##### Currently support containerlab version

Containerlab versions 15+ introduce changes that cause a race condition for the Vlan sub-interfaces the start script generates (starting crpd before they exist).  For now it is advised to run with a modified version 14, which can be installed as follows:
```
sudo bash -c "$(curl -sL https://get-clab.srlinux.dev)" -- -v 0.0.0-crpd-fix
```

### Running the script to generate topology / config files.

##### Dependencies

Python 3 is requried to run the script itself.  [Pynetbox](https://github.com/netbox-community/pynetbox) is also required and can be installed as follows:
```
sudo pip3 install pynetbox
```

##### Clone this repo and run the script

Clone this repo as follows:
```
git clone --depth 1 https://github.com/topranks/wmf-lab.git
```
You can then change to the 'wmf-lab' directory and run the "gen_topo.py" script, it will ask for an API key to connect to the WMF Netbox server and begin building the topology:
```
cmooney@wikilap:~/wmf-lab$ ./gen_topo.py 
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

Building clab topology and creating base config templates...
Writing clab topology file wmf-lab.yaml...
Writing start_wmf-lab.sh...
Writing stop_wmf-lab.sh...
```

NOTE:  The lab takes a few minutes to generate, due to slow Netbox API and my shitty code ;)

When complete you should find a new sub-folder has been created, called "output", containing the start and stop scripts, the containerlab topology file, and the base JunOS configuration files for each crpd container:
```
cmooney@wikilap:~/wmf-lab$ ls -lah output/
total 84K
drwxrwxr-x 3 cmooney cmooney 4.0K Aug 17 16:49 .
drwxrwxr-x 5 cmooney cmooney 4.0K Aug 17 16:49 ..
drwxrwxr-x 3 cmooney cmooney 4.0K Aug 17 16:49 configs
-rwxr-xr-x 1 cmooney cmooney  57K Aug 17 16:49 start_wmf-lab.sh
-rwxr-xr-x 1 cmooney cmooney  948 Aug 17 16:49 stop_wmf-lab.sh
-rw-rw-r-- 1 cmooney cmooney 6.2K Aug 17 16:49 wmf-lab.yaml
```

### Running the lab

##### Dependencies

In order to run the lab you will need to install docker and containerlab.  On Debian-based systems it should be a matter of running:
```
sudo apt install docker-ce
sudo bash -c "$(curl -sL https://get-clab.srlinux.dev)" -- -v 0.0.0-crpd-fix
```

A valid crpd container image from Juniper also needs to be present on the local system for docker to run (i.e. it should show with "docker images").  This is available from Juniper, or contact the author if a WMF staff member.  The docker image should be named crpd:latest, you can use [docker tag](https://docs.docker.com/engine/reference/commandline/tag/) to alias the Juniper provided image to that name.

```
cathal@officepc:~$ sudo docker images | grep crpd 
crpd                           latest        5b6acdd96efb   20 months ago   320MB
hub.juniper.net/routing/crpd   19.4R1.10     5b6acdd96efb   20 months ago   320MB
```

#### Start script

The start script needs to be run with root priviledges as it adds Linux netdevs to the various container namespaces and configures IP addresses:
```
sudo ./start_wmf-lab.sh
```

<details>
  <summary>Example output - click to expand</summary>
  
```
root@officepc:/home/cathal/containerlab/wmf-lab# ./start_wmf-lab.sh 
+ sudo brctl addbr asw-a-codfw
+ sudo ip link set dev asw-a-codfw mtu 9212
+ sudo ip link set dev asw-a-codfw up
+ sudo brctl addbr asw-b-codfw
+ sudo ip link set dev asw-b-codfw mtu 9212
+ sudo ip link set dev asw-b-codfw up
+ sudo brctl addbr asw-c-codfw
+ sudo ip link set dev asw-c-codfw mtu 9212
+ sudo ip link set dev asw-c-codfw up
+ sudo brctl addbr asw-d-codfw
+ sudo ip link set dev asw-d-codfw mtu 9212
+ sudo ip link set dev asw-d-codfw up
+ sudo brctl addbr csw1-c8-eqiad
+ sudo ip link set dev csw1-c8-eqiad mtu 9212
+ sudo ip link set dev csw1-c8-eqiad up
+ sudo brctl addbr asw2-a-eqiad
+ sudo ip link set dev asw2-a-eqiad mtu 9212
+ sudo ip link set dev asw2-a-eqiad up
+ sudo brctl addbr asw2-b-eqiad
+ sudo ip link set dev asw2-b-eqiad mtu 9212
+ sudo ip link set dev asw2-b-eqiad up
+ sudo brctl addbr asw2-c-eqiad
+ sudo ip link set dev asw2-c-eqiad mtu 9212
+ sudo ip link set dev asw2-c-eqiad up
+ sudo brctl addbr asw2-d-eqiad
+ sudo ip link set dev asw2-d-eqiad mtu 9212
+ sudo ip link set dev asw2-d-eqiad up
+ sudo brctl addbr csw1-d5-eqiad
+ sudo ip link set dev csw1-d5-eqiad mtu 9212
+ sudo ip link set dev csw1-d5-eqiad up
+ sudo brctl addbr asw1-eqsin
+ sudo ip link set dev asw1-eqsin mtu 9212
+ sudo ip link set dev asw1-eqsin up
+ sudo brctl addbr asw2-esams
+ sudo ip link set dev asw2-esams mtu 9212
+ sudo ip link set dev asw2-esams up
+ sudo brctl addbr asw2-ulsfo
+ sudo ip link set dev asw2-ulsfo mtu 9212
+ sudo ip link set dev asw2-ulsfo up
+ sudo clab deploy -t wmf-lab.yaml
INFO[0000] Parsing & checking topology file: wmf-lab.yaml 
INFO[0000] Creating lab directory: /home/cathal/containerlab/wmf-lab/clab-wmf-lab 
INFO[0000] Creating docker network: Name='clab', IPv4Subnet='172.20.20.0/24', IPv6Subnet='2001:172:20:20::/64', MTU='1500' 
INFO[0000] Creating container: pfw3b-eqiad              
INFO[0000] Creating container: mr1-eqsin                
INFO[0000] Creating container: pfw3b-codfw              
INFO[0000] Creating container: cr2-esams                
INFO[0000] Creating container: cr1-codfw                
INFO[0000] Creating container: cr2-eqsin                
INFO[0000] Creating container: mr1-codfw                
INFO[0000] Creating container: cr2-eqdfw                
INFO[0000] Creating container: mr1-eqiad                
INFO[0000] Creating container: cr3-knams                
INFO[0000] Creating container: cr3-ulsfo                
INFO[0000] Creating container: mr1-esams                
INFO[0000] Creating container: mr1-ulsfo                
INFO[0000] Creating container: cr2-eqord                
INFO[0000] Creating container: pfw3a-eqiad              
INFO[0000] Creating container: cr1-eqiad                
INFO[0000] Creating container: cr2-eqiad                
INFO[0000] Creating container: cr2-codfw                
INFO[0000] Creating container: pfw3a-codfw              
INFO[0000] Creating container: cr3-esams                
INFO[0000] Creating container: cr4-ulsfo                
INFO[0000] Creating container: cr3-eqsin                
INFO[0003] Creating virtual wire: cr1-codfw:eth9 <--> asw-b-codfw:eth276027411 
INFO[0003] Creating virtual wire: cr1-codfw:eth10 <--> asw-c-codfw:eth242519861 
INFO[0003] Creating virtual wire: cr3-knams:eth1 <--> cr1-eqiad:eth5 
INFO[0003] Creating virtual wire: cr3-eqsin:eth3 <--> mr1-eqsin:eth2 
INFO[0003] Creating virtual wire: asw1-eqsin:eth220930212 <--> cr3-eqsin:eth4 
INFO[0003] Creating virtual wire: cr4-ulsfo:eth7 <--> asw2-ulsfo:eth746641012 
INFO[0003] Creating virtual wire: cr2-eqsin:eth3 <--> mr1-eqsin:eth1 
INFO[0003] Creating virtual wire: cr4-ulsfo:eth1 <--> cr1-codfw:eth2 
INFO[0003] Creating virtual wire: cr1-eqiad:eth3 <--> pfw3a-eqiad:eth1 
INFO[0003] Creating virtual wire: cr2-codfw:eth7 <--> asw-a-codfw:eth536575652 
INFO[0003] Creating virtual wire: cr1-codfw:eth7 <--> mr1-codfw:eth1 
INFO[0003] Creating virtual wire: cr2-codfw:eth10 <--> asw-d-codfw:eth33937352 
INFO[0003] Creating virtual wire: cr2-eqiad:eth1 <--> cr1-eqiad:eth6 
INFO[0003] Creating virtual wire: cr2-eqiad:eth12 <--> asw2-d-eqiad:eth909385222 
INFO[0003] Creating virtual wire: cr1-codfw:eth8 <--> asw-a-codfw:eth536575651 
INFO[0003] Creating virtual wire: mr1-ulsfo:eth2 <--> cr4-ulsfo:eth6 
INFO[0003] Creating virtual wire: cr2-eqdfw:eth5 <--> cr3-knams:eth2 
INFO[0003] Creating virtual wire: cr2-eqdfw:eth1 <--> cr1-codfw:eth1 
INFO[0003] Creating virtual wire: cr2-eqiad:eth3 <--> csw1-d5-eqiad:eth470247211 
INFO[0003] Creating virtual wire: cr1-eqiad:eth11 <--> asw2-d-eqiad:eth909385221 
INFO[0003] Creating virtual wire: cr2-eqsin:eth2 <--> cr3-eqsin:eth2 
INFO[0003] Creating virtual wire: cr2-eqiad:eth9 <--> asw2-a-eqiad:eth2094122 
INFO[0003] Creating virtual wire: cr3-knams:eth3 <--> cr2-esams:eth4 
INFO[0003] Creating virtual wire: cr3-ulsfo:eth1 <--> cr2-eqord:eth3 
INFO[0003] Creating virtual wire: cr2-eqiad:eth4 <--> pfw3b-eqiad:eth1 
INFO[0003] Creating virtual wire: cr1-codfw:eth5 <--> cr1-eqiad:eth1 
INFO[0003] Creating virtual wire: cr3-ulsfo:eth5 <--> cr4-ulsfo:eth5 
INFO[0003] Creating virtual wire: cr2-eqdfw:eth2 <--> cr1-eqiad:eth4 
INFO[0003] Creating virtual wire: cr1-eqiad:eth8 <--> asw2-a-eqiad:eth2094121 
INFO[0003] Creating virtual wire: mr1-eqiad:eth1 <--> cr1-eqiad:eth7 
INFO[0003] Creating virtual wire: mr1-eqiad:eth2 <--> cr2-eqiad:eth8 
INFO[0003] Creating virtual wire: cr2-codfw:eth8 <--> asw-b-codfw:eth276027412 
INFO[0003] Creating virtual wire: cr1-codfw:eth3 <--> pfw3a-codfw:eth1 
INFO[0003] Creating virtual wire: cr1-eqiad:eth2 <--> csw1-c8-eqiad:eth332421621 
INFO[0003] Creating virtual wire: cr2-codfw:eth3 <--> cr2-eqiad:eth2 
INFO[0003] Creating virtual wire: cr2-eqord:eth2 <--> cr2-eqiad:eth6 
INFO[0003] Creating virtual wire: cr3-esams:eth1 <--> cr2-eqiad:eth7 
INFO[0003] Creating virtual wire: cr3-knams:eth4 <--> cr3-esams:eth4 
INFO[0003] Creating virtual wire: cr2-codfw:eth6 <--> mr1-codfw:eth2 
INFO[0003] Creating virtual wire: cr2-eqiad:eth11 <--> asw2-c-eqiad:eth156814412 
INFO[0003] Creating virtual wire: asw2-esams:eth449402052 <--> cr3-esams:eth3 
INFO[0003] Creating virtual wire: cr2-codfw:eth4 <--> pfw3b-codfw:eth1 
INFO[0003] Creating virtual wire: cr1-codfw:eth6 <--> cr2-codfw:eth1 
INFO[0003] Creating virtual wire: cr1-eqiad:eth10 <--> asw2-c-eqiad:eth156814411 
INFO[0003] Creating virtual wire: cr2-eqiad:eth10 <--> asw2-b-eqiad:eth401133582 
INFO[0003] Creating virtual wire: asw1-eqsin:eth220930211 <--> cr2-eqsin:eth4 
INFO[0003] Creating virtual wire: cr3-ulsfo:eth3 <--> cr4-ulsfo:eth4 
INFO[0003] Creating virtual wire: cr3-ulsfo:eth4 <--> asw2-ulsfo:eth746641011 
INFO[0003] Creating virtual wire: cr1-codfw:eth4 <--> cr3-eqsin:eth1 
INFO[0003] Creating virtual wire: cr2-esams:eth1 <--> cr2-eqiad:eth5 
INFO[0003] Creating virtual wire: cr2-eqdfw:eth3 <--> cr2-codfw:eth2 
INFO[0003] Creating virtual wire: cr4-ulsfo:eth3 <--> cr2-eqsin:eth1 
INFO[0003] Creating virtual wire: cr3-esams:eth2 <--> cr2-esams:eth2 
INFO[0003] Creating virtual wire: cr1-codfw:eth11 <--> asw-d-codfw:eth33937351 
INFO[0003] Creating virtual wire: cr1-eqiad:eth9 <--> asw2-b-eqiad:eth401133581 
INFO[0003] Creating virtual wire: cr3-esams:eth5 <--> mr1-esams:eth2 
INFO[0003] Creating virtual wire: asw2-esams:eth449402051 <--> cr2-esams:eth3 
INFO[0003] Creating virtual wire: mr1-ulsfo:eth1 <--> cr3-ulsfo:eth2 
INFO[0003] Creating virtual wire: cr2-eqord:eth1 <--> cr2-codfw:eth5 
INFO[0003] Creating virtual wire: cr2-esams:eth5 <--> mr1-esams:eth1 
INFO[0003] Creating virtual wire: cr4-ulsfo:eth2 <--> cr2-eqdfw:eth4 
INFO[0003] Creating virtual wire: cr2-codfw:eth9 <--> asw-c-codfw:eth242519862 
INFO[0010] Writing /etc/hosts file                      
INFO[0010] 🎉 New containerlab version 0.16.2 is available! Release notes: https://containerlab.srlinux.dev/rn/0.16.2
Run 'containerlab version upgrade' to upgrade or go check other installation options at https://containerlab.srlinux.dev/install/ 
+----+--------------------------+--------------+-------+------+-------+---------+-----------------+-----------------------+
| #  |           Name           | Container ID | Image | Kind | Group |  State  |  IPv4 Address   |     IPv6 Address      |
+----+--------------------------+--------------+-------+------+-------+---------+-----------------+-----------------------+
|  1 | clab-wmf-lab-cr1-codfw   | e0f6e17e94b1 | crpd  | crpd |       | running | 172.20.20.23/24 | 2001:172:20:20::17/64 |
|  2 | clab-wmf-lab-cr1-eqiad   | 6ccc3035ec33 | crpd  | crpd |       | running | 172.20.20.17/24 | 2001:172:20:20::11/64 |
|  3 | clab-wmf-lab-cr2-codfw   | 672752fd39c7 | crpd  | crpd |       | running | 172.20.20.19/24 | 2001:172:20:20::13/64 |
|  4 | clab-wmf-lab-cr2-eqdfw   | 14ecf8ee88fb | crpd  | crpd |       | running | 172.20.20.9/24  | 2001:172:20:20::9/64  |
|  5 | clab-wmf-lab-cr2-eqiad   | 375a31889191 | crpd  | crpd |       | running | 172.20.20.16/24 | 2001:172:20:20::10/64 |
|  6 | clab-wmf-lab-cr2-eqord   | 2012cf1cb3ef | crpd  | crpd |       | running | 172.20.20.6/24  | 2001:172:20:20::6/64  |
|  7 | clab-wmf-lab-cr2-eqsin   | 485b7c312651 | crpd  | crpd |       | running | 172.20.20.13/24 | 2001:172:20:20::d/64  |
|  8 | clab-wmf-lab-cr2-esams   | 6403b602e21d | crpd  | crpd |       | running | 172.20.20.20/24 | 2001:172:20:20::14/64 |
|  9 | clab-wmf-lab-cr3-eqsin   | a7873effae9f | crpd  | crpd |       | running | 172.20.20.10/24 | 2001:172:20:20::a/64  |
| 10 | clab-wmf-lab-cr3-esams   | e5be79173dc8 | crpd  | crpd |       | running | 172.20.20.12/24 | 2001:172:20:20::c/64  |
| 11 | clab-wmf-lab-cr3-knams   | 49dd8732dc13 | crpd  | crpd |       | running | 172.20.20.8/24  | 2001:172:20:20::8/64  |
| 12 | clab-wmf-lab-cr3-ulsfo   | f6c24e23fefd | crpd  | crpd |       | running | 172.20.20.22/24 | 2001:172:20:20::16/64 |
| 13 | clab-wmf-lab-cr4-ulsfo   | e70800e8553d | crpd  | crpd |       | running | 172.20.20.7/24  | 2001:172:20:20::7/64  |
| 14 | clab-wmf-lab-mr1-codfw   | c397137e6c44 | crpd  | crpd |       | running | 172.20.20.4/24  | 2001:172:20:20::4/64  |
| 15 | clab-wmf-lab-mr1-eqiad   | e5efbf59c922 | crpd  | crpd |       | running | 172.20.20.21/24 | 2001:172:20:20::15/64 |
| 16 | clab-wmf-lab-mr1-eqsin   | 1b5c2dc1bee9 | crpd  | crpd |       | running | 172.20.20.5/24  | 2001:172:20:20::5/64  |
| 17 | clab-wmf-lab-mr1-esams   | 28298c7fe98e | crpd  | crpd |       | running | 172.20.20.2/24  | 2001:172:20:20::2/64  |
| 18 | clab-wmf-lab-mr1-ulsfo   | 62e46e1ee957 | crpd  | crpd |       | running | 172.20.20.14/24 | 2001:172:20:20::e/64  |
| 19 | clab-wmf-lab-pfw3a-codfw | baec9dfb9755 | crpd  | crpd |       | running | 172.20.20.3/24  | 2001:172:20:20::3/64  |
| 20 | clab-wmf-lab-pfw3a-eqiad | d0308e403250 | crpd  | crpd |       | running | 172.20.20.18/24 | 2001:172:20:20::12/64 |
| 21 | clab-wmf-lab-pfw3b-codfw | 213915c020bc | crpd  | crpd |       | running | 172.20.20.15/24 | 2001:172:20:20::f/64  |
| 22 | clab-wmf-lab-pfw3b-eqiad | 38391147f7ee | crpd  | crpd |       | running | 172.20.20.11/24 | 2001:172:20:20::b/64  |
+----+--------------------------+--------------+-------+------+-------+---------+-----------------+-----------------------+
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.192/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-5/0/0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.210/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe03::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-5/0/1 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 198.35.26.203/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:863:fe07::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-5/1/1 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.200/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-5/1/2 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 103.102.166.139/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2001:df2:e500:fe02::2/64 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias xe-5/2/1 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.221/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe01::2/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae0 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.218/31 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe00::1/64 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.401 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.206/31 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:fe05::1/64 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1 dev eth8
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev eth8
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2 dev eth9
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev eth9
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae3 dev eth10
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev eth10
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae4 dev eth11
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr flush dev eth11
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth8 name eth8.2001 type vlan id 2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.2/27 dev eth8.2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:1:fe00::1/64 dev eth8.2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth8.2001 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.2001 dev eth8.2001
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth8 name eth8.2017 type vlan id 2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.0.2/22 dev eth8.2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:101:fe00::1/64 dev eth8.2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth8.2017 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.2017 dev eth8.2017
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth8 name eth8.2201 type vlan id 2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.152.242/28 dev eth8.2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:201:fe00::1/64 dev eth8.2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth8.2201 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae1.2201 dev eth8.2201
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth9 name eth9.2002 type vlan id 2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.34/27 dev eth9.2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:2:fe00::1/64 dev eth9.2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth9.2002 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2002 dev eth9.2002
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth9 name eth9.2018 type vlan id 2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.16.2/22 dev eth9.2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:102:fe00::1/64 dev eth9.2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth9.2018 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2018 dev eth9.2018
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth9 name eth9.2118 type vlan id 2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.20.2/24 dev eth9.2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:118:fe00::1/64 dev eth9.2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth9.2118 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2118 dev eth9.2118
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth9 name eth9.2120 type vlan id 2120
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.186/29 dev eth9.2120
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth9.2120 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2120 dev eth9.2120
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth9 name eth9.2122 type vlan id 2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.21.2/24 dev eth9.2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:122:fe00::1/64 dev eth9.2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth9.2122 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae2.2122 dev eth9.2122
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth10 name eth10.2003 type vlan id 2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.66/27 dev eth10.2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:3:fe00::1/64 dev eth10.2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth10.2003 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae3.2003 dev eth10.2003
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth10 name eth10.2019 type vlan id 2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.32.2/22 dev eth10.2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:103:fe00::1/64 dev eth10.2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth10.2019 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae3.2019 dev eth10.2019
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth11 name eth11.2004 type vlan id 2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 208.80.153.98/27 dev eth11.2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:4:fe00::1/64 dev eth11.2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth11.2004 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae4.2004 dev eth11.2004
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link add link eth11 name eth11.2020 type vlan id 2020
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 10.192.48.2/22 dev eth11.2020
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip addr add 2620:0:860:104:fe00::1/64 dev eth11.2020
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set dev eth11.2020 up
+ sudo ip netns exec clab-wmf-lab-cr1-codfw ip link set alias ae4.2020 dev eth11.2020
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.198/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:ffff::5/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.211/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe03::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/3.12 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.215/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe08::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/4 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.213/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe04::2/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias gr-0/0/0.1 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 198.35.26.205/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:863:fe04::2/64 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip link set alias xe-0/1/3.23 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 208.80.153.217/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-eqdfw ip addr add 2620:0:860:fe09::2/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.193/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias xe-0/1/1 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.202/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe07::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias gr-0/0/0.2 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.204/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe04::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias gr-0/0/0.1 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 103.102.166.137/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2001:df2:e500:fe01::2/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.501 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.226/29 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:62:c000::200:149:2/125 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias ae0.2 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.197/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe00::2/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.402 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.200/31 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:fe06::1/64 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr flush dev eth7
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link add link eth7 name eth7.1201 type vlan id 1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.3/28 dev eth7.1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:1:fe00::2/64 dev eth7.1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set dev eth7.1201 up
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.1201 dev eth7.1201
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link add link eth7 name eth7.1211 type vlan id 1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 10.128.0.3/24 dev eth7.1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:101:fe00::2/64 dev eth7.1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set dev eth7.1211 up
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.1211 dev eth7.1211
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link add link eth7 name eth7.1221 type vlan id 1221
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 198.35.26.243/28 dev eth7.1221
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip addr add 2620:0:863:201:fe00::2/64 dev eth7.1221
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set dev eth7.1221 up
+ sudo ip netns exec clab-wmf-lab-cr4-ulsfo ip link set alias et-0/0/1.1221 dev eth7.1221
+ sudo ip netns exec clab-wmf-lab-pfw3a-codfw ip link set alias xe-0/0/16 dev eth1
+ sudo ip netns exec clab-wmf-lab-pfw3a-codfw ip addr add 208.80.153.201/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.131/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:ffff::4/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias xe-0/1/0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.138/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:fe02::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae0 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.140/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:fe05::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.401 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.132/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:fe03::1/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr flush dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link add link eth4 name eth4.510 type vlan id 510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.2/28 dev eth4.510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:1:fe00::1/64 dev eth4.510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set dev eth4.510 up
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.510 dev eth4.510
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link add link eth4 name eth4.520 type vlan id 520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 10.132.0.2/24 dev eth4.520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:101:fe00::1/64 dev eth4.520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set dev eth4.520 up
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.520 dev eth4.520
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link add link eth4 name eth4.530 type vlan id 530
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 103.102.166.18/28 dev eth4.530
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip addr add 2001:df2:e500:201:fe00::1/64 dev eth4.530
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set dev eth4.530 up
+ sudo ip netns exec clab-wmf-lab-cr3-eqsin ip link set alias ae1.530 dev eth4.530
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 185.212.145.2/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.196/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.153.220/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:860:fe01::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/4 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev eth2
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/1/7 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.200/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/2.12 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.153.214/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:860:fe08::1/64 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-4/2/2.13 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 91.198.174.250/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:862:fe06::1/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae0 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.193/30 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:fe00::1/64 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.401 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.204/31 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:fe04::1/64 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1 dev eth8
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev eth8
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2 dev eth9
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev eth9
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3 dev eth10
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev eth10
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4 dev eth11
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr flush dev eth11
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth2 name eth2.1102 type vlan id 1102
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.210/31 dev eth2.1102
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth2.1102 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/4.1102 dev eth2.1102
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth2 name eth2.1118 type vlan id 1118
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.20.2/24 dev eth2.1118
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:118:fe00::1/64 dev eth2.1118
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth2.1118 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias xe-3/0/4.1118 dev eth2.1118
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth8 name eth8.1001 type vlan id 1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.2/26 dev eth8.1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:1:fe00::1/64 dev eth8.1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth8.1001 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1001 dev eth8.1001
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth8 name eth8.1017 type vlan id 1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.0.2/22 dev eth8.1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:101:fe00::1/64 dev eth8.1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth8.1017 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1017 dev eth8.1017
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth8 name eth8.1030 type vlan id 1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.5.2/24 dev eth8.1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:104:fe00::1/64 dev eth8.1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth8.1030 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1030 dev eth8.1030
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth8 name eth8.1117 type vlan id 1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.4.2/24 dev eth8.1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:117:fe00::1/64 dev eth8.1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth8.1117 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae1.1117 dev eth8.1117
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth9 name eth9.1002 type vlan id 1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.130/26 dev eth9.1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:2:fe00::1/64 dev eth9.1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth9.1002 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1002 dev eth9.1002
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth9 name eth9.1018 type vlan id 1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.16.2/22 dev eth9.1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:102:fe00::1/64 dev eth9.1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth9.1018 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1018 dev eth9.1018
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth9 name eth9.1021 type vlan id 1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.21.2/24 dev eth9.1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:105:fe00::1/64 dev eth9.1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth9.1021 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1021 dev eth9.1021
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth9 name eth9.1202 type vlan id 1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.155.66/28 dev eth9.1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:202:fe00::1/64 dev eth9.1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth9.1202 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae2.1202 dev eth9.1202
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth10 name eth10.1003 type vlan id 1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.154.66/26 dev eth10.1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:3:fe00::1/64 dev eth10.1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth10.1003 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1003 dev eth10.1003
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth10 name eth10.1019 type vlan id 1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.32.2/22 dev eth10.1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:103:fe00::1/64 dev eth10.1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth10.1019 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1019 dev eth10.1019
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth10 name eth10.1022 type vlan id 1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.36.2/24 dev eth10.1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:106:fe00::1/64 dev eth10.1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth10.1022 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1022 dev eth10.1022
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth10 name eth10.1119 type vlan id 1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.37.2/24 dev eth10.1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:119:fe00::1/64 dev eth10.1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth10.1119 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae3.1119 dev eth10.1119
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth11 name eth11.1004 type vlan id 1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 208.80.155.98/27 dev eth11.1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:4:fe00::1/64 dev eth11.1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth11.1004 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4.1004 dev eth11.1004
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth11 name eth11.1020 type vlan id 1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.48.2/22 dev eth11.1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:107:fe00::1/64 dev eth11.1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth11.1020 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4.1020 dev eth11.1020
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link add link eth11 name eth11.1023 type vlan id 1023
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 10.64.53.2/24 dev eth11.1023
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip addr add 2620:0:861:108:fe00::1/64 dev eth11.1023
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set dev eth11.1023 up
+ sudo ip netns exec clab-wmf-lab-cr1-eqiad ip link set alias ae4.1023 dev eth11.1023
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.193/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.219/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe00::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-5/0/0 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.212/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe04::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-5/0/2 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.154.215/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:861:fe06::2/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-5/1/1 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.202/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias xe-5/2/1 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.223/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe02::2/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.402 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.208/31 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:fe06::1/64 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev eth7
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2 dev eth8
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev eth8
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae3 dev eth9
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev eth9
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae4 dev eth10
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr flush dev eth10
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth7 name eth7.2001 type vlan id 2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.3/27 dev eth7.2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:1:fe00::2/64 dev eth7.2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth7.2001 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.2001 dev eth7.2001
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth7 name eth7.2017 type vlan id 2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.0.3/22 dev eth7.2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:101:fe00::2/64 dev eth7.2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth7.2017 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.2017 dev eth7.2017
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth7 name eth7.2201 type vlan id 2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.152.243/28 dev eth7.2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:201:fe00::2/64 dev eth7.2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth7.2201 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae1.2201 dev eth7.2201
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth8 name eth8.2002 type vlan id 2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.35/27 dev eth8.2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:2:fe00::2/64 dev eth8.2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth8.2002 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2002 dev eth8.2002
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth8 name eth8.2018 type vlan id 2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.16.3/22 dev eth8.2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:102:fe00::2/64 dev eth8.2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth8.2018 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2018 dev eth8.2018
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth8 name eth8.2118 type vlan id 2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.20.3/24 dev eth8.2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:118:fe00::2/64 dev eth8.2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth8.2118 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2118 dev eth8.2118
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth8 name eth8.2120 type vlan id 2120
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.187/29 dev eth8.2120
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth8.2120 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2120 dev eth8.2120
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth8 name eth8.2122 type vlan id 2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.21.3/24 dev eth8.2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:122:fe00::2/64 dev eth8.2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth8.2122 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae2.2122 dev eth8.2122
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth9 name eth9.2003 type vlan id 2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.67/27 dev eth9.2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:3:fe00::2/64 dev eth9.2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth9.2003 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae3.2003 dev eth9.2003
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth9 name eth9.2019 type vlan id 2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.32.3/22 dev eth9.2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:103:fe00::2/64 dev eth9.2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth9.2019 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae3.2019 dev eth9.2019
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth10 name eth10.2004 type vlan id 2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 208.80.153.99/27 dev eth10.2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:4:fe00::2/64 dev eth10.2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth10.2004 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae4.2004 dev eth10.2004
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link add link eth10 name eth10.2020 type vlan id 2020
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 10.192.48.3/22 dev eth10.2020
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip addr add 2620:0:860:104:fe00::2/64 dev eth10.2020
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set dev eth10.2020 up
+ sudo ip netns exec clab-wmf-lab-cr2-codfw ip link set alias ae4.2020 dev eth10.2020
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip link set alias ge-0/0/1.401 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 208.80.153.207/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 2620:0:860:fe05::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip link set alias ge-0/0/1.402 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 208.80.153.209/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-codfw ip addr add 2620:0:860:fe06::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-pfw3a-eqiad ip link set alias xe-0/0/16 dev eth1
+ sudo ip netns exec clab-wmf-lab-pfw3a-eqiad ip addr add 208.80.154.201/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.246/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:ffff::4/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias xe-0/1/5.13 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.251/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:fe06::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias xe-0/1/5.23 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 208.80.153.216/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:860:fe09::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias ae1.403 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.255/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:fe03::2/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip link set alias ae1.401 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 91.198.174.229/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-knams ip addr add 2620:0:862:fe01::2/64 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.197/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:ffff::2/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.194/30 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe00::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/2/2 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.214/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe06::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/0/4 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/1/7 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.202/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-4/1/3 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 91.198.174.248/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:862:fe07::1/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-4/2/0 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.208/31 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe02::1/64 dev eth6
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias gr-4/3/0.1 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.220/31 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe03::1/64 dev eth7
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.402 dev eth8
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.206/31 dev eth8
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:fe05::1/64 dev eth8
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1 dev eth9
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev eth9
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2 dev eth10
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev eth10
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3 dev eth11
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev eth11
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4 dev eth12
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr flush dev eth12
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth3 name eth3.1103 type vlan id 1103
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.212/31 dev eth3.1103
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth3.1103 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/0/4.1103 dev eth3.1103
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth3 name eth3.1118 type vlan id 1118
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.20.3/24 dev eth3.1118
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:118:fe00::2/64 dev eth3.1118
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth3.1118 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias xe-3/0/4.1118 dev eth3.1118
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth9 name eth9.1001 type vlan id 1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.3/26 dev eth9.1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:1:fe00::2/64 dev eth9.1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth9.1001 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1001 dev eth9.1001
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth9 name eth9.1017 type vlan id 1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.0.3/22 dev eth9.1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:101:fe00::2/64 dev eth9.1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth9.1017 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1017 dev eth9.1017
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth9 name eth9.1030 type vlan id 1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.5.3/24 dev eth9.1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:104:fe00::2/64 dev eth9.1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth9.1030 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1030 dev eth9.1030
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth9 name eth9.1117 type vlan id 1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.4.3/24 dev eth9.1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:117:fe00::2/64 dev eth9.1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth9.1117 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae1.1117 dev eth9.1117
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth10 name eth10.1002 type vlan id 1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.131/26 dev eth10.1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:2:fe00::2/64 dev eth10.1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth10.1002 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1002 dev eth10.1002
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth10 name eth10.1018 type vlan id 1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.16.3/22 dev eth10.1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:102:fe00::2/64 dev eth10.1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth10.1018 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1018 dev eth10.1018
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth10 name eth10.1021 type vlan id 1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.21.3/24 dev eth10.1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:105:fe00::2/64 dev eth10.1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth10.1021 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1021 dev eth10.1021
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth10 name eth10.1202 type vlan id 1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.155.67/28 dev eth10.1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:202:fe00::2/64 dev eth10.1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth10.1202 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae2.1202 dev eth10.1202
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth11 name eth11.1003 type vlan id 1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.154.67/26 dev eth11.1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:3:fe00::2/64 dev eth11.1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth11.1003 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1003 dev eth11.1003
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth11 name eth11.1019 type vlan id 1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.32.3/22 dev eth11.1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:103:fe00::2/64 dev eth11.1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth11.1019 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1019 dev eth11.1019
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth11 name eth11.1022 type vlan id 1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.36.3/24 dev eth11.1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:106:fe00::2/64 dev eth11.1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth11.1022 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1022 dev eth11.1022
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth11 name eth11.1119 type vlan id 1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.37.3/24 dev eth11.1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:119:fe00::2/64 dev eth11.1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth11.1119 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae3.1119 dev eth11.1119
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth12 name eth12.1004 type vlan id 1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 208.80.155.99/27 dev eth12.1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:4:fe00::2/64 dev eth12.1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth12.1004 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4.1004 dev eth12.1004
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth12 name eth12.1020 type vlan id 1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.48.3/22 dev eth12.1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:107:fe00::3/64 dev eth12.1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth12.1020 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4.1020 dev eth12.1020
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link add link eth12 name eth12.1023 type vlan id 1023
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 10.64.53.3/24 dev eth12.1023
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip addr add 2620:0:861:108:fe00::2/64 dev eth12.1023
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set dev eth12.1023 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqiad ip link set alias ae4.1023 dev eth12.1023
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip link set alias ge-0/0/1.401 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 208.80.154.205/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 2620:0:861:fe04::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip link set alias ge-0/0/1.402 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 208.80.154.207/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-eqiad ip addr add 2620:0:861:fe05::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-pfw3b-codfw ip link set alias xe-7/0/16 dev eth1
+ sudo ip netns exec clab-wmf-lab-pfw3b-codfw ip addr add 208.80.153.203/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 208.80.154.198/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:861:ffff::5/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip link set alias xe-0/1/0 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 208.80.153.222/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:860:fe02::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip link set alias xe-0/1/5 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 208.80.154.209/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:861:fe02::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip link set alias xe-0/1/3 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 198.35.26.209/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqord ip addr add 2620:0:863:fe02::2/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-pfw3b-eqiad ip link set alias xe-7/0/16 dev eth1
+ sudo ip netns exec clab-wmf-lab-pfw3b-eqiad ip addr add 208.80.154.203/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.244/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:ffff::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias xe-0/1/3 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.249/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe07::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae0 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.252/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe02::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr flush dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.403 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.254/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe03::1/64 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.404 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.242/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:fe05::1/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link add link eth3 name eth3.100 type vlan id 100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.3/25 dev eth3.100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:1:fe00::2/64 dev eth3.100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set dev eth3.100 up
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.100 dev eth3.100
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link add link eth3 name eth3.102 type vlan id 102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 91.198.174.131/28 dev eth3.102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:201:fe00::2/64 dev eth3.102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set dev eth3.102 up
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.102 dev eth3.102
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link add link eth3 name eth3.103 type vlan id 103
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 10.20.0.3/24 dev eth3.103
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip addr add 2620:0:862:102:fe00::2/64 dev eth3.103
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set dev eth3.103 up
+ sudo ip netns exec clab-wmf-lab-cr2-esams ip link set alias ae1.103 dev eth3.103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.245/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:ffff::5/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias gr-0/0/0.1 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 208.80.154.221/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:861:fe03::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae0 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.253/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe02::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr flush dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.401 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.228/31 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe01::1/64 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.402 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.240/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:fe04::1/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link add link eth3 name eth3.100 type vlan id 100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.2/25 dev eth3.100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:1:fe00::1/64 dev eth3.100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set dev eth3.100 up
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.100 dev eth3.100
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link add link eth3 name eth3.102 type vlan id 102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 91.198.174.130/28 dev eth3.102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:201:fe00::1/64 dev eth3.102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set dev eth3.102 up
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.102 dev eth3.102
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link add link eth3 name eth3.103 type vlan id 103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 10.20.0.2/24 dev eth3.103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip addr add 2620:0:862:102:fe00::1/64 dev eth3.103
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set dev eth3.103 up
+ sudo ip netns exec clab-wmf-lab-cr3-esams ip link set alias ae1.103 dev eth3.103
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.192/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:ffff::1/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias xe-0/1/1 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.208/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:fe02::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.401 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.198/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:fe05::1/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.501 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.225/29 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:62:c000::200:149:1/125 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr flush dev eth4
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias ae0.2 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.196/31 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:fe00::1/64 dev eth5
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link add link eth4 name eth4.1201 type vlan id 1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.2/28 dev eth4.1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:1:fe00::1/64 dev eth4.1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set dev eth4.1201 up
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.1201 dev eth4.1201
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link add link eth4 name eth4.1211 type vlan id 1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 10.128.0.2/24 dev eth4.1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:101:fe00::1/64 dev eth4.1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set dev eth4.1211 up
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.1211 dev eth4.1211
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link add link eth4 name eth4.1221 type vlan id 1221
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 198.35.26.242/28 dev eth4.1221
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip addr add 2620:0:863:201:fe00::1/64 dev eth4.1221
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set dev eth4.1221 up
+ sudo ip netns exec clab-wmf-lab-cr3-ulsfo ip link set alias et-0/0/1.1221 dev eth4.1221
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.130/32 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:ffff::3/128 dev lo
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias gr-0/0/0.1 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.136/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:fe01::1/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae0 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.141/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:fe05::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.402 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.142/31 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:fe04::1/64 dev eth3
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1 dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr flush dev eth4
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link add link eth4 name eth4.510 type vlan id 510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.3/28 dev eth4.510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:1:fe00::2/64 dev eth4.510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set dev eth4.510 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.510 dev eth4.510
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link add link eth4 name eth4.520 type vlan id 520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 10.132.0.3/24 dev eth4.520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:101:fe00::2/64 dev eth4.520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set dev eth4.520 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.520 dev eth4.520
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link add link eth4 name eth4.530 type vlan id 530
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 103.102.166.19/28 dev eth4.530
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip addr add 2001:df2:e500:201:fe00::2/64 dev eth4.530
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set dev eth4.530 up
+ sudo ip netns exec clab-wmf-lab-cr2-eqsin ip link set alias ae1.530 dev eth4.530
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip link set alias ge-0/0/4.402 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 103.102.166.143/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 2001:df2:e500:fe04::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip link set alias ge-0/0/4.401 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 103.102.166.133/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-eqsin ip addr add 2001:df2:e500:fe03::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip link set alias ge-0/0/1.404 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 91.198.174.243/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 2620:0:862:fe05::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip link set alias ge-0/0/1.402 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 91.198.174.241/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-esams ip addr add 2620:0:862:fe04::2/64 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip link set alias ge-0/0/4.401 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 198.35.26.199/31 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 2620:0:863:fe05::2/64 dev eth1
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip link set alias ge-0/0/4.402 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 198.35.26.201/31 dev eth2
+ sudo ip netns exec clab-wmf-lab-mr1-ulsfo ip addr add 2620:0:863:fe06::2/64 dev eth2
root@officepc:/home/cathal/containerlab/wmf-lab# 
```
</details>

##### Connecting to crpd instances
  
Once started you can see the status of the containers as follows:
```
cathal@officepc:~$ sudo clab inspect -n wmf-lab
+----+--------------------------+--------------+-------+------+-------+---------+-----------------+-----------------------+
| #  |           Name           | Container ID | Image | Kind | Group |  State  |  IPv4 Address   |     IPv6 Address      |
+----+--------------------------+--------------+-------+------+-------+---------+-----------------+-----------------------+
|  1 | clab-wmf-lab-cr1-codfw   | e0f6e17e94b1 | crpd  | crpd |       | running | 172.20.20.23/24 | 2001:172:20:20::17/64 |
|  2 | clab-wmf-lab-cr1-eqiad   | 6ccc3035ec33 | crpd  | crpd |       | running | 172.20.20.17/24 | 2001:172:20:20::11/64 |
|  3 | clab-wmf-lab-cr2-codfw   | 672752fd39c7 | crpd  | crpd |       | running | 172.20.20.19/24 | 2001:172:20:20::13/64 |
|  4 | clab-wmf-lab-cr2-eqdfw   | 14ecf8ee88fb | crpd  | crpd |       | running | 172.20.20.9/24  | 2001:172:20:20::9/64  |
|  5 | clab-wmf-lab-cr2-eqiad   | 375a31889191 | crpd  | crpd |       | running | 172.20.20.16/24 | 2001:172:20:20::10/64 |
|  6 | clab-wmf-lab-cr2-eqord   | 2012cf1cb3ef | crpd  | crpd |       | running | 172.20.20.6/24  | 2001:172:20:20::6/64  |
|  7 | clab-wmf-lab-cr2-eqsin   | 485b7c312651 | crpd  | crpd |       | running | 172.20.20.13/24 | 2001:172:20:20::d/64  |
|  8 | clab-wmf-lab-cr2-esams   | 6403b602e21d | crpd  | crpd |       | running | 172.20.20.20/24 | 2001:172:20:20::14/64 |
|  9 | clab-wmf-lab-cr3-eqsin   | a7873effae9f | crpd  | crpd |       | running | 172.20.20.10/24 | 2001:172:20:20::a/64  |
| 10 | clab-wmf-lab-cr3-esams   | e5be79173dc8 | crpd  | crpd |       | running | 172.20.20.12/24 | 2001:172:20:20::c/64  |
| 11 | clab-wmf-lab-cr3-knams   | 49dd8732dc13 | crpd  | crpd |       | running | 172.20.20.8/24  | 2001:172:20:20::8/64  |
| 12 | clab-wmf-lab-cr3-ulsfo   | f6c24e23fefd | crpd  | crpd |       | running | 172.20.20.22/24 | 2001:172:20:20::16/64 |
| 13 | clab-wmf-lab-cr4-ulsfo   | e70800e8553d | crpd  | crpd |       | running | 172.20.20.7/24  | 2001:172:20:20::7/64  |
| 14 | clab-wmf-lab-mr1-codfw   | c397137e6c44 | crpd  | crpd |       | running | 172.20.20.4/24  | 2001:172:20:20::4/64  |
| 15 | clab-wmf-lab-mr1-eqiad   | e5efbf59c922 | crpd  | crpd |       | running | 172.20.20.21/24 | 2001:172:20:20::15/64 |
| 16 | clab-wmf-lab-mr1-eqsin   | 1b5c2dc1bee9 | crpd  | crpd |       | running | 172.20.20.5/24  | 2001:172:20:20::5/64  |
| 17 | clab-wmf-lab-mr1-esams   | 28298c7fe98e | crpd  | crpd |       | running | 172.20.20.2/24  | 2001:172:20:20::2/64  |
| 18 | clab-wmf-lab-mr1-ulsfo   | 62e46e1ee957 | crpd  | crpd |       | running | 172.20.20.14/24 | 2001:172:20:20::e/64  |
| 19 | clab-wmf-lab-pfw3a-codfw | baec9dfb9755 | crpd  | crpd |       | running | 172.20.20.3/24  | 2001:172:20:20::3/64  |
| 20 | clab-wmf-lab-pfw3a-eqiad | d0308e403250 | crpd  | crpd |       | running | 172.20.20.18/24 | 2001:172:20:20::12/64 |
| 21 | clab-wmf-lab-pfw3b-codfw | 213915c020bc | crpd  | crpd |       | running | 172.20.20.15/24 | 2001:172:20:20::f/64  |
| 22 | clab-wmf-lab-pfw3b-eqiad | 38391147f7ee | crpd  | crpd |       | running | 172.20.20.11/24 | 2001:172:20:20::b/64  |
+----+--------------------------+--------------+-------+------+-------+---------+-----------------+-----------------------+
```
  
You can connect to any via SSH via their IPv4 or IPv6 address, the default password is "clab123":
```
athal@officepc:~$ ssh root@172.20.20.23
Warning: Permanently added '172.20.20.23' (ECDSA) to the list of known hosts.
root@172.20.20.23's password: 
Welcome to Ubuntu 18.04.1 LTS (GNU/Linux 5.8.0-43-generic x86_64)

 * Documentation:  https://help.ubuntu.com
 * Management:     https://landscape.canonical.com
 * Support:        https://ubuntu.com/advantage
This system has been minimized by removing packages and content that are
not required on a system that users do not log into.

To restore this content, you can run the 'unminimize' command.

The programs included with the Ubuntu system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/copyright.

Ubuntu comes with ABSOLUTELY NO WARRANTY, to the extent permitted by
applicable law.


===>
           Containerized Routing Protocols Daemon (CRPD)
 Copyright (C) 2018-19, Juniper Networks, Inc. All rights reserved.
                                                                    <===

root@cr1-codfw:~# 
```

Run 'cli' once connected to access the JunOS command line.

                                                                                       
<details>
  <summary>Example output - click to expand</summary>
  
```
root@cr1-codfw:~# cli
root@cr1-codfw> 

root@cr1-codfw> show interfaces routing 
Interface        State Addresses
eth5             Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.221
                       INET6 2620:0:860:fe01::2
                       INET6 fe80::a8c1:abff:fe54:2a12
eth6             Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.218
                       INET6 2620:0:860:fe00::1
                       INET6 fe80::a8c1:abff:fe62:aeec
eth2             Up    MPLS  enabled
                       ISO   enabled
                       INET  198.35.26.203
                       INET6 2620:0:863:fe07::2
                       INET6 fe80::a8c1:abff:fec9:7dc8
eth7             Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.206
                       INET6 2620:0:860:fe05::1
                       INET6 fe80::a8c1:abff:fec0:9482
eth4             Up    MPLS  enabled
                       ISO   enabled
                       INET  103.102.166.139
                       INET6 2001:df2:e500:fe02::2
                       INET6 fe80::a8c1:abff:fe27:70a5
eth1             Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.210
                       INET6 2620:0:860:fe03::1
                       INET6 fe80::a8c1:abff:feea:9e14
eth11.2020       Up    MPLS  enabled
                       ISO   enabled
                       INET  10.192.48.2
                       INET6 2620:0:860:104:fe00::1
                       INET6 fe80::a8c1:abff:feb2:9124
eth11.2004       Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.98
                       INET6 2620:0:860:4:fe00::1
                       INET6 fe80::a8c1:abff:feb2:9124
eth11            Up    MPLS  enabled
                       ISO   enabled
eth3             Up    MPLS  enabled
                       ISO   enabled    
                       INET  208.80.153.200
                       INET6 fe80::a8c1:abff:fe10:406f
eth8.2201        Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.152.242
                       INET6 2620:0:860:201:fe00::1
                       INET6 fe80::a8c1:abff:fe21:eaf1
eth8.2017        Up    MPLS  enabled
                       ISO   enabled
                       INET  10.192.0.2
                       INET6 2620:0:860:101:fe00::1
                       INET6 fe80::a8c1:abff:fe21:eaf1
eth8.2001        Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.2
                       INET6 2620:0:860:1:fe00::1
                       INET6 fe80::a8c1:abff:fe21:eaf1
eth8             Up    MPLS  enabled
                       ISO   enabled
eth10.2019       Up    MPLS  enabled
                       ISO   enabled
                       INET  10.192.32.2
                       INET6 2620:0:860:103:fe00::1
                       INET6 fe80::a8c1:abff:fe71:ea0e
eth10.2003       Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.66
                       INET6 2620:0:860:3:fe00::1
                       INET6 fe80::a8c1:abff:fe71:ea0e
eth10            Up    MPLS  enabled
                       ISO   enabled
lsi              Up    MPLS  enabled
                       ISO   enabled
                       INET6 fe80::c8aa:92ff:fe5b:c9e5
lo.0             Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.192
                       INET6 2620:0:860:ffff::1
eth9.2122        Up    MPLS  enabled
                       ISO   enabled
                       INET  10.192.21.2
                       INET6 2620:0:860:122:fe00::1
                       INET6 fe80::a8c1:abff:fe59:d7f
eth9.2120        Up    MPLS  enabled    
                       ISO   enabled
                       INET  208.80.153.186
                       INET6 fe80::a8c1:abff:fe59:d7f
eth9.2118        Up    MPLS  enabled
                       ISO   enabled
                       INET  10.192.20.2
                       INET6 2620:0:860:118:fe00::1
                       INET6 fe80::a8c1:abff:fe59:d7f
eth9.2018        Up    MPLS  enabled
                       ISO   enabled
                       INET  10.192.16.2
                       INET6 2620:0:860:102:fe00::1
                       INET6 fe80::a8c1:abff:fe59:d7f
eth9.2002        Up    MPLS  enabled
                       ISO   enabled
                       INET  208.80.153.34
                       INET6 2620:0:860:2:fe00::1
                       INET6 fe80::a8c1:abff:fe59:d7f
eth9             Up    MPLS  enabled
                       ISO   enabled
eth0             Up    MPLS  enabled
                       ISO   enabled
                       INET  172.20.20.23
                       INET6 2001:172:20:20::17
                       INET6 fe80::42:acff:fe14:1417

root@cr1-codfw> 
  
root@cr1-codfw> show ospf interface 
Interface           State   Area            DR ID           BDR ID          Nbrs
eth1                PtToPt  0.0.0.0         0.0.0.0         0.0.0.0            1
eth10.2003          DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth10.2019          DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth11.2004          DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth11.2020          DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth2                PtToPt  0.0.0.0         0.0.0.0         0.0.0.0            1
eth4                PtToPt  0.0.0.0         0.0.0.0         0.0.0.0            1
eth5                PtToPt  0.0.0.0         0.0.0.0         0.0.0.0            1
eth6                PtToPt  0.0.0.0         0.0.0.0         0.0.0.0            1
eth8.2001           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth8.2017           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth8.2201           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth9.2002           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth9.2018           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth9.2118           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth9.2120           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
eth9.2122           DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
lo.0                DRother 0.0.0.0         0.0.0.0         0.0.0.0            0

root@cr1-codfw> 

root@cr1-codfw> show ospf database 

    OSPF database, Area 0.0.0.0
 Type       ID               Adv Rtr           Seq      Age  Opt  Cksum  Len 
Router   91.198.174.244   91.198.174.244   0x80000005   946  0x22 0x52ad 144
Router   91.198.174.245   91.198.174.245   0x80000004   951  0x22 0xcc2f 120
Router   91.198.174.246   91.198.174.246   0x80000004   947  0x22 0x9943  84
Router   103.102.166.130  103.102.166.130  0x80000005   940  0x22 0x2c16 120
Router   103.102.166.131  103.102.166.131  0x80000005   940  0x22 0x3304 120
Router   185.212.145.2    185.212.145.2    0x80000005   940  0x22 0x5c45 288
Router   198.35.26.192    198.35.26.192    0x80000003   954  0x22 0x3540 120
Router   198.35.26.193    198.35.26.193    0x80000005   944  0x22 0xd134 144
Router  *208.80.153.192   208.80.153.192   0x80000006   942  0x22 0x4a0e 300
Router   208.80.153.193   208.80.153.193   0x80000006   940  0x22 0x9aff 276
Router   208.80.153.198   208.80.153.198   0x80000004   952  0x22 0x26ee  84
Router   208.80.154.197   208.80.154.197   0x80000006   941  0x22 0x8b47 324
Router   208.80.154.198   208.80.154.198   0x80000004   941  0x22 0x8f43 108
  
root@cr1-codfw> 

root@cr1-codfw> show route protocol ospf 

inet.0: 93 destinations, 93 routes (93 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

10.20.0.0/24       *[OSPF/10] 01:03:09, metric 1192
                       to 208.80.153.220 via eth5
                    >  to 208.80.153.219 via eth6
10.64.0.0/22       *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.4.0/24       *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.5.0/24       *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.16.0/22      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.20.0/24      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.21.0/24      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.32.0/22      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.36.0/24      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.37.0/24      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.48.0/22      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.64.53.0/24      *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
10.128.0.0/24      *[OSPF/10] 01:03:24, metric 392
                    >  to 198.35.26.202 via eth2
10.132.0.0/24      *[OSPF/10] 01:03:14, metric 2002
                    >  to 103.102.166.138 via eth4
91.198.174.0/25    *[OSPF/10] 01:03:09, metric 1192
                    >  to 208.80.153.220 via eth5
                       to 208.80.153.219 via eth6
91.198.174.128/28  *[OSPF/10] 01:03:09, metric 1192
                    >  to 208.80.153.220 via eth5
                       to 208.80.153.219 via eth6
91.198.174.228/31  *[OSPF/10] 01:03:09, metric 1210
                    >  to 208.80.153.220 via eth5
                       to 208.80.153.219 via eth6
91.198.174.244/32  *[OSPF/10] 01:03:09, metric 1190
                    >  to 208.80.153.220 via eth5
                       to 208.80.153.219 via eth6
91.198.174.245/32  *[OSPF/10] 01:03:09, metric 1200
                    >  to 208.80.153.220 via eth5
                       to 208.80.153.219 via eth6
91.198.174.246/32  *[OSPF/10] 01:03:09, metric 1200
                    >  to 208.80.153.220 via eth5
                       to 208.80.153.219 via eth6
91.198.174.248/31  *[OSPF/10] 01:03:09, metric 1190
                       to 208.80.153.220 via eth5
                    >  to 208.80.153.219 via eth6
91.198.174.252/31  *[OSPF/10] 01:03:09, metric 1200
                       to 208.80.153.220 via eth5
                    >  to 208.80.153.219 via eth6
91.198.174.254/31  *[OSPF/10] 01:03:09, metric 1200
                       to 208.80.153.220 via eth5
                    >  to 208.80.153.219 via eth6
103.102.166.0/28   *[OSPF/10] 01:03:14, metric 2002
                    >  to 103.102.166.138 via eth4
103.102.166.16/28  *[OSPF/10] 01:03:14, metric 2002
                    >  to 103.102.166.138 via eth4
103.102.166.130/32 *[OSPF/10] 01:03:09, metric 2010
                    >  to 103.102.166.138 via eth4
103.102.166.131/32 *[OSPF/10] 01:03:14, metric 2000
                    >  to 103.102.166.138 via eth4
103.102.166.136/31 *[OSPF/10] 01:03:24, metric 4390
                    >  to 198.35.26.202 via eth2
103.102.166.140/31 *[OSPF/10] 01:03:14, metric 2010
                    >  to 103.102.166.138 via eth4
185.212.145.2/32   *[OSPF/10] 01:03:14, metric 340
                    >  to 208.80.153.220 via eth5
198.35.26.0/28     *[OSPF/10] 01:03:24, metric 392
                    >  to 198.35.26.202 via eth2
198.35.26.192/32   *[OSPF/10] 01:03:24, metric 400
                    >  to 198.35.26.202 via eth2
198.35.26.193/32   *[OSPF/10] 01:03:24, metric 390
                    >  to 198.35.26.202 via eth2
198.35.26.196/31   *[OSPF/10] 01:03:24, metric 400
                    >  to 198.35.26.202 via eth2
198.35.26.208/31   *[OSPF/10] 01:03:09, metric 760
                    >  to 208.80.153.219 via eth6
                       to 208.80.153.211 via eth1
198.35.26.240/28   *[OSPF/10] 01:03:24, metric 392
                    >  to 198.35.26.202 via eth2
208.80.153.193/32  *[OSPF/10] 01:03:19, metric 10
                    >  to 208.80.153.219 via eth6
                       to 208.80.153.211 via eth1
208.80.153.198/32  *[OSPF/10] 01:03:24, metric 10
                    >  to 208.80.153.211 via eth1
                       to 208.80.153.219 via eth6
208.80.153.212/31  *[OSPF/10] 01:03:19, metric 20
                       to 208.80.153.211 via eth1
                    >  to 208.80.153.219 via eth6
208.80.153.222/31  *[OSPF/10] 01:03:19, metric 250
                    >  to 208.80.153.219 via eth6
                       to 208.80.153.211 via eth1
208.80.154.0/26    *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
208.80.154.64/26   *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
208.80.154.128/26  *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
208.80.154.192/30  *[OSPF/10] 01:03:14, metric 350
                    >  to 208.80.153.220 via eth5
208.80.154.196/32  *[OSPF/10] 01:03:14, metric 340
                    >  to 208.80.153.220 via eth5
208.80.154.197/32  *[OSPF/10] 01:03:09, metric 350
                       to 208.80.153.220 via eth5
                    >  to 208.80.153.219 via eth6
208.80.154.198/32  *[OSPF/10] 01:03:09, metric 250
                    >  to 208.80.153.219 via eth6
                       to 208.80.153.211 via eth1
208.80.154.208/31  *[OSPF/10] 01:03:09, metric 490
                    >  to 208.80.153.219 via eth6
                       to 208.80.153.211 via eth1
208.80.154.214/31  *[OSPF/10] 01:03:19, metric 350
                    >  to 208.80.153.219 via eth6
                       to 208.80.153.211 via eth1
208.80.155.64/28   *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
208.80.155.96/27   *[OSPF/10] 01:03:14, metric 342
                    >  to 208.80.153.220 via eth5
224.0.0.5/32       *[OSPF/10] 01:03:44, metric 1
                       MultiRecv

inet6.0: 51 destinations, 51 routes (51 active, 0 holddown, 0 hidden)

root@cr1-codfw> 
```
</details>                                                                                       
                                                                                       
#### Linux shell inside container

It is possible to connect to the bash shell of any of the crpd containers using SSH as described previously.  You can also use "docker exec" to spawn a new bash shell inside the container.  In both cases the resulting shell runs inside the container with the limited userspace available.
  
As the primary reason for using the containers is network isolation, it can be useful to execute a new shell within the network namespace, rather than fully inside the container.  For example:
  
```
cathal@officepc:~$ sudo ip netns exec clab-wmf-lab-cr1-codfw bash
root@officepc:/home/cathal# 
```
  
Netns names created by clab match the names shown under "clab inspect" above.  Or you can use "sudo ip netns list" to see them.
  
Once you have a shell inside the container you can run normal Linux commands in it, for instance:
  
```
cathal@officepc:~$ sudo ip netns exec clab-wmf-lab-cr1-codfw bash
root@officepc:/home/cathal# 
root@officepc:/home/cathal# mtr -b -w -c 5 91.198.174.130
Start: 2021-08-17T17:15:14+0100
HOST: officepc                                          Loss%   Snt   Last   Avg  Best  Wrst StDev
  1.|-- xe-4-2-0.cr1-eqiad.wikimedia.org (208.80.153.220)  0.0%     5    0.0   0.0   0.0   0.1   0.0
  2.|-- ae0.cr2-eqiad.wikimedia.org (208.80.154.194)       0.0%     5    0.1   0.1   0.0   0.1   0.0
  3.|-- xe-0-1-3.cr2-esams.wikimedia.org (91.198.174.249)  0.0%     5    0.1   0.1   0.0   0.1   0.0
  4.|-- ae1-102.cr3-esams.wikimedia.org (91.198.174.130)   0.0%     5    0.1   0.1   0.1   0.1   0.0
root@officepc:/home/cathal# 
root@officepc:/home/cathal# 
root@officepc:/home/cathal# ip -br addr show | sort -V
eth0@if132       UP             172.20.20.23/24 2001:172:20:20::17/64 fe80::42:acff:fe14:1417/64 
eth1@if166       UP             208.80.153.210/31 2620:0:860:fe03::1/64 fe80::a8c1:abff:feea:9e14/64 
eth2@if148       UP             198.35.26.203/31 2620:0:863:fe07::2/64 fe80::a8c1:abff:fec9:7dc8/64 
eth3@if197       UP             208.80.153.200/31 fe80::a8c1:abff:fe10:406f/64 
eth4@if225       UP             103.102.166.139/31 2001:df2:e500:fe02::2/64 fe80::a8c1:abff:fe27:70a5/64 
eth5@if183       UP             208.80.153.221/31 2620:0:860:fe01::2/64 fe80::a8c1:abff:fe54:2a12/64 
eth6@if213       UP             208.80.153.218/31 2620:0:860:fe00::1/64 fe80::a8c1:abff:fe62:aeec/64 
eth7@if153       UP             208.80.153.206/31 2620:0:860:fe05::1/64 fe80::a8c1:abff:fec0:9482/64 
eth8.2001@eth8   UP             208.80.153.2/27 2620:0:860:1:fe00::1/64 fe80::a8c1:abff:fe21:eaf1/64 
eth8.2017@eth8   UP             10.192.0.2/22 2620:0:860:101:fe00::1/64 fe80::a8c1:abff:fe21:eaf1/64 
eth8.2201@eth8   UP             208.80.152.242/28 2620:0:860:201:fe00::1/64 fe80::a8c1:abff:fe21:eaf1/64 
eth8@if161       UP             
eth9.2002@eth9   UP             208.80.153.34/27 2620:0:860:2:fe00::1/64 fe80::a8c1:abff:fe59:d7f/64 
eth9.2018@eth9   UP             10.192.16.2/22 2620:0:860:102:fe00::1/64 fe80::a8c1:abff:fe59:d7f/64 
eth9.2118@eth9   UP             10.192.20.2/24 2620:0:860:118:fe00::1/64 fe80::a8c1:abff:fe59:d7f/64 
eth9.2120@eth9   UP             208.80.153.186/29 fe80::a8c1:abff:fe59:d7f/64 
eth9.2122@eth9   UP             10.192.21.2/24 2620:0:860:122:fe00::1/64 fe80::a8c1:abff:fe59:d7f/64 
eth9@if133       UP             
eth10.2003@eth10 UP             208.80.153.66/27 2620:0:860:3:fe00::1/64 fe80::a8c1:abff:fe71:ea0e/64 
eth10.2019@eth10 UP             10.192.32.2/22 2620:0:860:103:fe00::1/64 fe80::a8c1:abff:fe71:ea0e/64 
eth10@if135      UP             
eth11.2004@eth11 UP             208.80.153.98/27 2620:0:860:4:fe00::1/64 fe80::a8c1:abff:feb2:9124/64 
eth11.2020@eth11 UP             10.192.48.2/22 2620:0:860:104:fe00::1/64 fe80::a8c1:abff:feb2:9124/64 
eth11@if251      UP             
lo               UNKNOWN        127.0.0.1/8 208.80.153.192/32 2620:0:860:ffff::1/128 ::1/128 
lsi              UNKNOWN        fe80::c8aa:92ff:fe5b:c9e5/64 
```
                                                                    
The equivalent real-world interface (configured as alias) is visible if you run "ip link show":
```
root@officepc:/home/cathal# ip link show eth2
147: eth2@if148: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 65000 qdisc noqueue state UP mode DEFAULT group default 
    link/ether aa:c1:ab:c9:7d:c8 brd ff:ff:ff:ff:ff:ff link-netns clab-wmf-lab-cr4-ulsfo
    alias xe-5/0/1
```

### Stopping the lab
  
Run the stop script top stop the lab and clean up the bridge interfaces
```
sudo ./stop_wmf-lab.sh
```

<details>
  <summary>Example output - click to expand</summary>
  
```  
cathal@officepc:~/containerlab/wmf-lab$ sudo ./stop_wmf-lab.sh 
[sudo] password for cathal: 
+ sudo clab destroy -t wmf-lab.yaml
INFO[0000] Parsing & checking topology file: wmf-lab.yaml 
INFO[0000] Destroying lab: wmf-lab                      
INFO[0001] Removed container: clab-wmf-lab-mr1-eqsin    
INFO[0001] Removed container: clab-wmf-lab-pfw3a-eqiad  
INFO[0001] Removed container: clab-wmf-lab-cr4-ulsfo    
INFO[0001] Removed container: clab-wmf-lab-cr3-knams    
INFO[0001] Removed container: clab-wmf-lab-cr2-eqord    
INFO[0001] Removed container: clab-wmf-lab-cr2-eqdfw    
INFO[0002] Removed container: clab-wmf-lab-mr1-codfw    
INFO[0002] Removed container: clab-wmf-lab-mr1-ulsfo    
INFO[0002] Removed container: clab-wmf-lab-mr1-esams    
INFO[0002] Removed container: clab-wmf-lab-mr1-eqiad    
INFO[0002] Removed container: clab-wmf-lab-pfw3b-codfw  
INFO[0002] Removed container: clab-wmf-lab-cr2-codfw    
INFO[0002] Removed container: clab-wmf-lab-cr2-esams    
INFO[0002] Removed container: clab-wmf-lab-cr2-eqiad    
INFO[0003] Removed container: clab-wmf-lab-pfw3b-eqiad  
INFO[0003] Removed container: clab-wmf-lab-cr3-eqsin    
INFO[0003] Removed container: clab-wmf-lab-cr3-ulsfo    
INFO[0003] Removed container: clab-wmf-lab-pfw3a-codfw  
INFO[0003] Removed container: clab-wmf-lab-cr1-eqiad    
INFO[0003] Removed container: clab-wmf-lab-cr3-esams    
INFO[0003] Removed container: clab-wmf-lab-cr2-eqsin    
INFO[0003] Removed container: clab-wmf-lab-cr1-codfw    
INFO[0003] Removing container entries from /etc/hosts file 
INFO[0003] Deleting network 'clab'...                   
+ sudo ip link set dev asw-a-codfw down
+ sudo brctl delbr asw-a-codfw
+ sudo ip link set dev asw-b-codfw down
+ sudo brctl delbr asw-b-codfw
+ sudo ip link set dev asw-c-codfw down
+ sudo brctl delbr asw-c-codfw
+ sudo ip link set dev asw-d-codfw down
+ sudo brctl delbr asw-d-codfw
+ sudo ip link set dev csw1-c8-eqiad down
+ sudo brctl delbr csw1-c8-eqiad
+ sudo ip link set dev asw2-a-eqiad down
+ sudo brctl delbr asw2-a-eqiad
+ sudo ip link set dev asw2-b-eqiad down
+ sudo brctl delbr asw2-b-eqiad
+ sudo ip link set dev asw2-c-eqiad down
+ sudo brctl delbr asw2-c-eqiad
+ sudo ip link set dev asw2-d-eqiad down
+ sudo brctl delbr asw2-d-eqiad
+ sudo ip link set dev csw1-d5-eqiad down
+ sudo brctl delbr csw1-d5-eqiad
+ sudo ip link set dev asw1-eqsin down
+ sudo brctl delbr asw1-eqsin
+ sudo ip link set dev asw2-esams down
+ sudo brctl delbr asw2-esams
+ sudo ip link set dev asw2-ulsfo down
+ sudo brctl delbr asw2-ulsfo
```
</details>   
