---
name: openstack-compute
description: >
  Manage OpenStack Nova servers and Glance images with the openstack CLI.
  Use when launching, stopping, resizing, rebuilding, rescuing, snapshotting,
  or deleting servers/VMs/instances; choosing flavors; managing keypairs and
  cloud-init user data; uploading or converting images; using server groups,
  availability zones, or boot-from-volume. Also covers operator tasks such as
  flavors with extra specs, host aggregates, live migration, and evacuation.
compatibility: Requires python-openstackclient and a configured clouds.yaml.
metadata:
  version: "0.1.0"
---

# OpenStack Compute (Nova + Glance)

Select the cloud with `--os-cloud <name>` or `OS_CLOUD`. Use `-f json` when you need to parse output. Confirm before delete/rebuild.

## Launch a server

Gather the inputs first; each must resolve to exactly one resource:

```bash
openstack flavor list --sort-column RAM
openstack image list --status active
openstack network list
openstack keypair list
openstack security group list
openstack availability zone list --compute   # only if the user cares about AZ
```

Then create and wait:

```bash
openstack server create web-1 \
  --flavor m1.small --image ubuntu-24.04 \
  --network private --key-name mykey \
  --security-group default --security-group web \
  --user-data cloud-init.yaml \
  --wait -f json
```

- No keypair yet? `openstack keypair create --public-key ~/.ssh/id_ed25519.pub mykey`. Avoid generating private keys server-side; if you must, save the output to a file with mode 600 and don't print it.
- Multiple networks require `--network` per NIC, or `--nic net-id=<id>,v4-fixed-ip=<ip>` / `--port <port-id>` for control.
- On some clouds a network is mandatory when more than one is visible: "Multiple possible networks found".
- To be reachable from outside, the server also needs a floating IP and a security group rule; see the openstack-networking skill.
- If the result is `ERROR`, run `openstack server show <name> -c fault -f json` and switch to openstack-troubleshooting.

### Boot from volume

Persistent root disk that survives server deletion (unless `delete_on_termination`):

```bash
openstack server create db-1 --flavor m1.medium --network private --key-name mykey \
  --image ubuntu-24.04 --boot-from-volume 40 --wait
```

Or from an existing bootable volume: `--volume <volume>`.

### Placement controls

- Anti-affinity (spread across hosts): `openstack server group create --policy anti-affinity web-grp`, then `--hint group=<group-id>` on create. Policies: `affinity`, `anti-affinity`, `soft-affinity`, `soft-anti-affinity`.
- Pick an AZ: `--availability-zone az1`.

## cloud-init user data

```yaml
#cloud-config
package_update: true
packages: [nginx]
users:
  - default
  - name: deploy
    ssh_authorized_keys: ["ssh-ed25519 AAAA... deploy"]
    sudo: ALL=(ALL) NOPASSWD:ALL
runcmd:
  - systemctl enable --now nginx
```

Check whether it ran with `openstack console log show web-1 | tail -50`.

## Lifecycle

| Goal | Command |
|---|---|
| Stop / start | `openstack server stop web-1` / `openstack server start web-1` |
| Reboot (hard if hung) | `openstack server reboot [--hard] web-1` |
| Resize | `openstack server resize --flavor m1.large --wait web-1` then `openstack server resize confirm web-1` (or `resize revert`) |
| Rebuild with new image (wipes root disk) | `openstack server rebuild --image ubuntu-24.04 web-1` |
| Rescue (boot rescue image to repair disk) | `openstack server rescue web-1` / `openstack server unrescue web-1` |
| Snapshot to image | `openstack server image create --name web-1-snap --wait web-1` |
| Console URL | `openstack console url show web-1` |
| Console log | `openstack console log show --lines 100 web-1` |
| Shelve (free host resources, keep data) | `openstack server shelve web-1` / `openstack server unshelve web-1` |
| Lock against changes | `openstack server lock web-1` |
| Delete | `openstack server delete --wait web-1` (confirm first) |

Resizing to a smaller root disk is not supported. A server in `VERIFY_RESIZE` that is never confirmed is auto-confirmed after a cloud-configured interval.

## Images (Glance)

```bash
openstack image create ubuntu-24.04 \
  --disk-format qcow2 --container-format bare \
  --file noble-server-cloudimg-amd64.img \
  --property os_distro=ubuntu --property os_version=24.04 \
  --property hw_disk_bus=scsi --property hw_scsi_model=virtio-scsi \
  --private
openstack image set --property hw_qemu_guest_agent=yes ubuntu-24.04
openstack image save --file out.qcow2 <image>
```

- Ceph-backed clouds boot much faster from `raw` images: `qemu-img convert -f qcow2 -O raw in.qcow2 out.raw`, upload with `--disk-format raw`.
- Visibility: `--private`, `--shared` (then `openstack image add project <image> <project>`; the consumer must accept with `openstack image set --accept <image>`), `--community`, `--public` *(admin)*.
- Large uploads can be done asynchronously with `openstack image create --import` when the cloud supports interoperable image import.

## Operator tasks *(admin)*

```bash
# Flavors
openstack flavor create --vcpus 4 --ram 8192 --disk 40 --public m1.large
openstack flavor set --property hw:cpu_policy=dedicated --property hw:mem_page_size=large m1.pinned
openstack flavor set --property aggregate_instance_extra_specs:ssd=true m1.ssd

# Aggregates and AZs
openstack aggregate create --zone az1 agg-ssd
openstack aggregate add host agg-ssd compute-01
openstack aggregate set --property ssd=true agg-ssd

# Hosts
openstack compute service list --service nova-compute
openstack compute service set --disable --disable-reason "maintenance" compute-01 nova-compute
openstack server list --all-projects --host compute-01

# Move servers
openstack server migrate --live-migration --wait <server>               # scheduler picks host
openstack server migrate --live-migration --host compute-02 --wait <server>
openstack server migrate --wait <server> && openstack server resize confirm <server>   # cold
openstack server evacuate <server>        # only when the source host is down and fenced
```

Before evacuating, confirm the source host is really down (`openstack compute service list` shows `down` and the host is powered off or fenced). Evacuating a live host risks two copies of the server writing the same disk.

For draining a host, list its servers, disable the service, then live-migrate one at a time and verify each reaches `ACTIVE` on a new host.
