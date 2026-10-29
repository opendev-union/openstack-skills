---
name: openstack-troubleshooting
description: >
  Diagnose and fix OpenStack failures for both cloud users and operators. Use
  when a server is stuck in BUILD or ERROR, "No valid host was found",
  "Exceeded maximum number of retries", a server is unreachable, a volume is
  stuck attaching or deleting, a port is DOWN, an API returns 5xx or times
  out, services or agents are down, or when reading Nova, Neutron, Cinder,
  Placement, Keystone, or RabbitMQ logs and tracing request IDs.
compatibility: Requires python-openstackclient. diagnose_server.py requires uv or openstacksdk. Operator sections assume shell access to control/compute nodes.
metadata:
  version: "0.1.0"
---

# OpenStack Troubleshooting

Select the cloud with `--os-cloud <name>` or `OS_CLOUD`. Gather evidence before changing anything, and confirm before any state reset or restart.

## Workflow

1. **Identify the failing resource and its exact error.** Capture the resource ID, status, `fault`/error message, and the request ID (`req-...`).
2. **Collect diagnostics.** For servers, run the bundled script:
   ```bash
   uv run scripts/diagnose_server.py --cloud <name> <server-name-or-id>
   ```
   It gathers status, fault, instance actions and events, ports, security groups, floating IPs, volumes, and the console log tail in one pass.
3. **Match against the tables below** (user-visible first, then operator).
4. **If you're a regular user and the cause is on the cloud side**, give the user a report for their cloud operator: resource ID, request ID, timestamp (UTC), error text, and what was ruled out.
5. **If you're an operator**, follow the request ID through the service logs (see "Tracing a request").

Get a request ID from any CLI call with `--debug` (look for `x-openstack-request-id`), from `openstack server event list <server>`, or from the error message.

## User-visible symptoms

| Symptom | Check | Typical cause / fix |
|---|---|---|
| Server `ERROR`, fault "No valid host was found" | `openstack server show <s> -c fault` | Flavor too large for any host, AZ/aggregate mismatch, image properties no host supports, quota on hypervisor capacity. Try a smaller flavor or another AZ; otherwise report to operator |
| Fault "Exceeded maximum number of retries" | instance events | Scheduling succeeded but spawn failed on several hosts (port binding, volume, image download). Operator must read nova-compute logs |
| Fault "Build of instance aborted: Volume ... did not finish being created" | `openstack volume show` | Boot-from-volume image copy too slow; retry with a raw image or pre-created volume |
| Fault mentions "Port binding failed" / `binding_failed` | `openstack port show <p> -c binding_vif_type` | Neutron agent down on target host or bad provider mapping (operator) |
| Stuck in `BUILD` > ~10 min | instance actions | Lost RPC message or slow image download; delete and recreate. Report persistent cases |
| "Quota exceeded for cores/ram/instances" | `openstack limits show --absolute` | Free resources or request a quota increase |
| SSH "Permission denied (publickey)" | console log for cloud-init | Wrong key, wrong default user (`ubuntu`, `cloud-user`, `debian`...), cloud-init failed to reach the metadata service |
| SSH timeout / no ping | openstack-networking connectivity checklist | Missing SG rule, no floating IP, router lacks gateway, guest firewall |
| Console log shows metadata service timeouts (169.254.169.254) | port status, router | Metadata agent/OVN metadata down, or subnet not on a router with metadata access (operator) |
| Volume stuck `attaching`/`detaching` | `openstack volume show` attachments | Lost RPC or backend error; operator reset (see openstack-storage) |
| HTTP 503/504 from API | retry with `--debug` | API service or load balancer overloaded/down (operator) |
| HTTP 409 Conflict | error text | Resource in a transitional state or locked; wait or unlock |

## Operator: health overview *(admin)*

```bash
openstack compute service list          # nova-compute/conductor/scheduler: State "up", Status "enabled"
openstack network agent list            # Alive ":-)" / True
openstack volume service list           # cinder-volume/scheduler/backup: "up"
openstack orchestration service list    # if Heat is deployed
openstack loadbalancer amphora list     # if Octavia uses amphorae
openstack hypervisor list --long        # vCPU/RAM usage per host
```

A service shown as `down` has not reported to the database within the heartbeat window (default ~60s). Common causes: the process died, RabbitMQ connectivity lost, or clock skew between nodes.

## Operator: "No valid host was found"

```bash
openstack server show <s> -c flavor -c "OS-EXT-AZ:availability_zone" -c image
openstack flavor show <flavor> -c properties
openstack image show <image> -c properties
# Does placement have any candidate? (requires osc-placement)
openstack allocation candidate list --resource VCPU=2 --resource MEMORY_MB=4096 --resource DISK_GB=20
openstack resource provider list
openstack resource provider usage show <rp-uuid>
openstack resource provider inventory list <rp-uuid>      # check allocation_ratio and reserved
```

- No allocation candidates means a placement problem: capacity, allocation ratios, missing traits, or the compute node isn't registered. New compute hosts need `nova-manage cell_v2 discover_hosts --verbose` (unless `discover_hosts_in_cells_interval` is set).
- Candidates exist but scheduling fails means a scheduler filter rejected them. Grep nova-scheduler logs for the request ID; filter lines like `Filter AggregateInstanceExtraSpecsFilter returned 0 hosts` name the culprit.
- Orphaned allocations (from failed migrations or deletes) eat capacity: `nova-manage placement audit --verbose` (add `--delete` only after reviewing).

## Operator: tracing a request

Log locations vary by deployment:

| Deployment | Location |
|---|---|
| Distro packages | `/var/log/nova/`, `/var/log/neutron/`, `/var/log/cinder/`, ... |
| Kolla-Ansible | `/var/log/kolla/<service>/`, or `docker logs`/`podman logs <container>` |
| OpenStack-Ansible | `journalctl -u <service>` inside the service's LXC container or host |
| Kubernetes-based (openstack-helm, RHOSO) | `kubectl logs -n openstack <pod>` |

```bash
grep -r "req-<id>" /var/log/nova/ /var/log/neutron/ /var/log/cinder/
```

The request ID changes between services; follow the `global_request_id` or the instance UUID across services. For a failed build, read in this order: nova-api, nova-conductor, nova-scheduler, nova-compute on the chosen host (`OS-EXT-SRV-ATTR:host`), then neutron-server and cinder-volume for port or volume errors.

## Operator: messaging and database

```bash
rabbitmqctl cluster_status
rabbitmqctl list_queues name messages consumers | awk '$2 > 100'   # backlogged queues
rabbitmqctl list_queues name consumers | awk '$2 == 0'            # queues nobody consumes
```

Growing queues with zero consumers usually mean the consuming service is down. Look for `AMQP server on ... is unreachable` and `MessagingTimeout` in service logs. For database issues, look for `DBConnectionError` / `Too many connections` and check the Galera cluster: `SHOW STATUS LIKE 'wsrep_cluster_size';`.

## Operator: recovering stuck resources

Only after the root cause is understood:

```bash
openstack server set --state active <server>     # or --state error to allow delete
openstack server reboot --hard <server>
openstack server delete --force <server>
```

`--state active` only changes the database record. Verify the real state on the hypervisor (`virsh list --all` on `OS-EXT-SRV-ATTR:host`, matching `OS-EXT-SRV-ATTR:instance_name`) first.

For Neutron: a port stuck `DOWN` with `binding:vif_type=binding_failed` usually needs the agent on that host fixed and the server hard-rebooted or migrated. For volumes, see the openstack-storage skill's operator section.
