# Heat Reference

## Complete template: web server with private network and floating IP

`stack.yaml`:

```yaml
heat_template_version: 2021-04-16

description: Web server on a private network with a floating IP

parameters:
  key_name:
    type: string
    constraints:
      - custom_constraint: nova.keypair
  image:
    type: string
    default: ubuntu-24.04
    constraints:
      - custom_constraint: glance.image
  flavor:
    type: string
    default: m1.small
    constraints:
      - custom_constraint: nova.flavor
  public_net:
    type: string
    default: public
    constraints:
      - custom_constraint: neutron.network
  cidr:
    type: string
    default: 10.30.0.0/24
  ssh_source:
    type: string
    default: 0.0.0.0/0

resources:
  net:
    type: OS::Neutron::Net

  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: net }
      cidr: { get_param: cidr }
      dns_nameservers: [1.1.1.1]

  router:
    type: OS::Neutron::Router
    properties:
      external_gateway_info:
        network: { get_param: public_net }

  router_iface:
    type: OS::Neutron::RouterInterface
    properties:
      router: { get_resource: router }
      subnet: { get_resource: subnet }

  sg:
    type: OS::Neutron::SecurityGroup
    properties:
      rules:
        - { protocol: tcp, port_range_min: 22, port_range_max: 22, remote_ip_prefix: { get_param: ssh_source } }
        - { protocol: tcp, port_range_min: 80, port_range_max: 80, remote_ip_prefix: 0.0.0.0/0 }
        - { protocol: icmp }

  port:
    type: OS::Neutron::Port
    properties:
      network: { get_resource: net }
      fixed_ips: [{ subnet: { get_resource: subnet } }]
      security_groups: [{ get_resource: sg }]

  server:
    type: OS::Nova::Server
    properties:
      image: { get_param: image }
      flavor: { get_param: flavor }
      key_name: { get_param: key_name }
      networks: [{ port: { get_resource: port } }]
      user_data_format: RAW
      user_data: |
        #cloud-config
        packages: [nginx]
        runcmd: [systemctl enable --now nginx]

  fip:
    type: OS::Neutron::FloatingIP
    depends_on: router_iface
    properties:
      floating_network: { get_param: public_net }
      port_id: { get_resource: port }

outputs:
  public_ip:
    value: { get_attr: [fip, floating_ip_address] }
  private_ip:
    value: { get_attr: [server, first_address] }
```

The `depends_on: router_iface` on the floating IP matters: without it Heat may create the floating IP before the subnet is routed, failing with "External network is not reachable from subnet".

## Environment file

`env.yaml`:

```yaml
parameters:
  key_name: mykey
  ssh_source: 203.0.113.0/24
resource_registry:
  My::WebServer: web-server.yaml      # custom nested template type
```

## Intrinsic functions

| Function | Use |
|---|---|
| `get_param: name` | Template parameter |
| `get_resource: name` | ID of another resource |
| `get_attr: [res, attr, ...]` | Resource attribute (e.g. `[server, networks, net-name, 0]`) |
| `str_replace: {template: ..., params: {...}}` | Inject values into user data |
| `list_join: [',', [a, b]]` | Join a list |
| `if: [cond, a, b]` with `conditions:` | Conditional properties/resources |
| `repeat` | Generate lists (e.g. SG rules per port) |

## Scaling groups

```yaml
  web_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 3
      resource_def:
        type: My::WebServer
        properties:
          name: web-%index%
```

Use `OS::Heat::AutoScalingGroup` with scaling policies only if the cloud has Aodh for alarms.

## Template versions

Use the newest version the cloud supports: `openstack orchestration template version list`. `2021-04-16` (Wallaby) is safe for most current clouds; fall back to `2018-08-31` on older ones.
