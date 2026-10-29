---
name: openstack-networking
description: >
  Build and manage OpenStack Neutron networking with the openstack CLI. Use
  when creating networks, subnets, routers, ports, security groups and rules,
  floating IPs, external gateways, allowed address pairs, port security, or
  provider networks; when exposing a server to the internet; or when a server
  cannot be reached over SSH/ping because of network configuration. Also
  covers operator checks of Neutron agents and OVN.
compatibility: Requires python-openstackclient and a configured clouds.yaml.
metadata:
  version: "0.1.0"
---

# OpenStack Networking (Neutron)

Select the cloud with `--os-cloud <name>` or `OS_CLOUD`. Use `-f json` when you need to parse output. Confirm before deleting networks, routers, or rules others may depend on.

## Mental model

Server NIC = **port** on a **network** with an IP from a **subnet**. Traffic to the internet goes through a **router** whose gateway is on an **external network**. Inbound access from outside needs a **floating IP** mapped to the port, and a **security group** rule allowing the traffic. Security groups are default-deny for ingress.

```bash
openstack network list --external      # find the external/public network
openstack network list --internal
openstack router list
```

## Standard tenant topology (private network with internet access)

```bash
openstack network create app-net
openstack subnet create app-subnet --network app-net \
  --subnet-range 10.20.0.0/24 --dns-nameserver 1.1.1.1
openstack router create app-router
openstack router set app-router --external-gateway public
openstack router add subnet app-router app-subnet
```

Choose a CIDR that does not overlap with networks the user connects from (VPN, office) or other subnets on the same router.

## Expose a server

```bash
# 1. Allow traffic
openstack security group create web --description "HTTP/SSH"
openstack security group rule create web --protocol tcp --dst-port 22 --remote-ip 203.0.113.0/24
openstack security group rule create web --protocol tcp --dst-port 80:443 --remote-ip 0.0.0.0/0
openstack security group rule create web --protocol icmp
openstack server add security group web-1 web

# 2. Floating IP
openstack floating ip create public -f value -c floating_ip_address
openstack server add floating ip web-1 <floating-ip>
```

- Restrict SSH to the user's source range rather than `0.0.0.0/0` when possible; ask if unknown.
- The server's subnet must be attached to a router with an external gateway on the same external network as the floating IP, or association fails with "External network ... is not reachable from subnet".
- Rules between servers: use `--remote-group <sg>` instead of IP ranges.
- IPv6 rules need `--ethertype IPv6`.

## Ports

```bash
openstack port list --server web-1 -f json
openstack port create --network app-net --fixed-ip subnet=app-subnet,ip-address=10.20.0.50 vip-port
openstack port set --allowed-address ip-address=10.20.0.100 <port>    # VRRP/keepalived VIP
openstack port set --no-security-group --disable-port-security <port> # appliances/routers; warn first
```

Disabling port security removes all filtering on that port, including anti-spoofing; confirm with the user before running it.

## Connectivity checklist (config side)

When a server is unreachable, check in order:

1. Server is `ACTIVE` and the guest booted: `openstack console log show web-1 | tail`.
2. It has an IP on the port: `openstack port list --server web-1 -c "Fixed IP Addresses" -c Status`. Port status should be `ACTIVE`.
3. Security groups on the port allow the protocol/port from the client source: `openstack security group rule list <sg> --ingress`.
4. Floating IP is associated: `openstack floating ip list --port <port-id>`.
5. Router has an external gateway and an interface in the server's subnet: `openstack router show app-router -c external_gateway_info -c interfaces_info`.
6. Guest-side: DHCP got the address, cloud-init injected the key, guest firewall is open. Check the console log.

If config looks correct, go to openstack-troubleshooting for agent/data-plane checks.

## Cleanup order

Neutron refuses to delete resources that are in use. Delete in this order: floating IPs, servers/ports, router interfaces (`openstack router remove subnet`), router gateway (`openstack router unset --external-gateway`), router, subnets, network.

## Operator tasks *(admin)*

```bash
openstack network agent list                      # ML2/OVS or LinuxBridge: all should be alive (:-) / UP)
openstack network agent list --router <router>    # which L3 agent hosts the router
openstack network agent list --network <net>      # which DHCP agents serve a network

# Provider/external network
openstack network create public --external --share \
  --provider-network-type flat --provider-physical-network physnet1
openstack subnet create public-subnet --network public --subnet-range 203.0.113.0/24 \
  --gateway 203.0.113.1 --allocation-pool start=203.0.113.100,end=203.0.113.200 --no-dhcp

openstack network rbac create --target-project <project> --action access_as_shared --type network <net>
```

On OVN-based clouds there are no L3/DHCP agents; `openstack network agent list` shows OVN controller and metadata agents instead. Use `ovn-nbctl show` and `ovn-sbctl show` on a controller node for deeper inspection.
