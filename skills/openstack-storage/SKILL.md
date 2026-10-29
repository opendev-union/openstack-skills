---
name: openstack-storage
description: >
  Manage OpenStack block storage (Cinder) and object storage (Swift) with the
  openstack CLI. Use when creating, attaching, detaching, extending, retyping,
  snapshotting, backing up, transferring, or deleting volumes; choosing volume
  types; or creating containers, uploading/downloading objects, large object
  segmentation, and temporary URLs. Also covers operator fixes for volumes
  stuck in attaching, detaching, deleting, or error states.
compatibility: Requires python-openstackclient. Large Swift uploads and temp URLs use python-swiftclient.
metadata:
  version: "0.1.0"
---

# OpenStack Storage (Cinder + Swift)

Select the cloud with `--os-cloud <name>` or `OS_CLOUD`. Use `-f json` when you need to parse output. Confirm before deleting volumes, snapshots, backups, or containers: data loss is permanent.

## Volumes

```bash
openstack volume type list                       # pick a type (e.g. ssd, hdd); omit for default
openstack volume create data-1 --size 100 --type ssd [--availability-zone nova]
openstack server add volume web-1 data-1 [--device /dev/vdb]
openstack volume show data-1 -c status -c attachments -f json
```

- `--device` is only a hint; the guest decides the actual name. Inside the guest, find the disk with `lsblk` and by serial: `/dev/disk/by-id/virtio-<first 20 chars of volume id>`.
- The volume and server must be in compatible AZs unless the cloud allows cross-AZ attach.
- Multi-attach requires a volume type with `multiattach="<is> True"` and a cluster-aware filesystem in the guests.

| Goal | Command |
|---|---|
| Detach | `openstack server remove volume web-1 data-1` (unmount in the guest first) |
| Extend | `openstack volume set --size 200 data-1`, then grow the partition/filesystem in the guest (`growpart`, `resize2fs`/`xfs_growfs`) |
| Change type/backend | `openstack volume set --type hdd --retype-policy on-demand data-1` |
| Bootable volume from image | `openstack volume create root-1 --image ubuntu-24.04 --size 40 --bootable` |
| Image from volume | `openstack image create --volume data-1 data-1-img` |
| Transfer to another project | `openstack volume transfer request create data-1` → recipient runs `openstack volume transfer request accept --auth-key <key> <id>` |

Extending an attached (in-use) volume needs compute API microversion 2.51+ and backend support; if it fails, detach, extend, reattach.

## Snapshots and backups

- **Snapshot**: fast, lives on the same backend, depends on the source volume. Good for short-term rollback.
- **Backup**: full/incremental copy to a separate backup store (often Swift or Ceph). Survives losing the volume or backend.

```bash
openstack volume snapshot create --volume data-1 [--force] data-1-snap   # --force for in-use volumes
openstack volume create data-1-restored --snapshot data-1-snap
openstack volume backup create --name data-1-bk [--incremental] [--force] data-1
openstack volume backup restore data-1-bk <target-volume-or-new-name>
openstack volume backup list
```

For consistent snapshots of an in-use volume, quiesce the application or freeze the filesystem (`fsfreeze -f /mnt/data`) first; unfreeze right after.

A volume with snapshots cannot be deleted until the snapshots are deleted.

## Object storage (Swift)

```bash
openstack container create backups
openstack object create backups db.sql.gz [--name 2026/db.sql.gz]
openstack object list backups --prefix 2026/
openstack object save backups 2026/db.sql.gz --file db.sql.gz
openstack container show backups              # object count and bytes
openstack object delete backups 2026/db.sql.gz
```

- Files over 5 GiB must be segmented. Use swiftclient: `swift upload --segment-size 1G backups bigfile.tar`. It creates a static/dynamic large object manifest automatically.
- Public read container: `openstack container set --property X-Container-Read=".r:*,.rlistings" site`. Confirm with the user before making data public.
- Object expiry: `openstack object set --property X-Delete-After=86400 backups tmp.bin`.
- S3 compatibility: many clouds expose an S3 API (Swift `s3api` or Ceph RGW). Create EC2-style keys with `openstack ec2 credentials create` and use any S3 client against the cloud's S3 endpoint.

### Temporary URLs

```bash
openstack object store account set --property Temp-URL-Key=<random-secret>
swift tempurl GET 3600 /v1/AUTH_<project_id>/backups/db.sql.gz <random-secret>
```

Prefix the output path with the Swift endpoint host from `openstack catalog show object-store`. Keep the key out of chat output.

## Operator fixes *(admin)*

Volumes stuck in a transitional state usually mean a lost RPC message or a backend failure. First find out why (cinder-volume logs, `openstack volume service list`), then reset only if the real state is known.

```bash
openstack volume service list                         # cinder-volume/backup/scheduler should be "up"
openstack volume show <vol> -c status -c attachments -c os-vol-host-attr:host
openstack volume set --state available <vol>          # reset status
openstack volume set --state error <vol>              # mark failed so it can be deleted
openstack volume set --detached <vol>                 # reset attach status only
openstack volume delete --force <vol>
openstack volume migrate --host <host@backend#pool> <vol>
```

Resetting state does not change the backend or the hypervisor. If a volume shows `available` but is still attached on the compute host, the guest can see stale data or the next attach can fail. Verify against the backend and `virsh domblklist <instance>` before resetting, and clean up stale attachments with `openstack volume attachment list`/`delete` (microversion 3.27+).
