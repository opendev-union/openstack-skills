---
name: openstack-skills
description: >
  Operate and troubleshoot OpenStack clouds as a user or an operator. Use this
  skill when the user mentions OpenStack, clouds.yaml, openrc, Keystone, Nova,
  Neutron, Cinder, Swift, Glance, Heat, Octavia, Magnum, Placement, or the
  `openstack` CLI. Also use for creating servers/VMs, networks, routers,
  security groups, floating IPs, volumes, object storage, load balancers,
  Kubernetes clusters on OpenStack, Heat templates, Terraform with the
  OpenStack provider, or debugging errors like "No valid host was found",
  servers stuck in BUILD/ERROR, or volumes stuck attaching.
compatibility: Requires python-openstackclient and a configured clouds.yaml. Helper scripts require uv (or Python 3.10+ with openstacksdk).
metadata:
  version: "0.1.0"
---

# OpenStack Skills

Top-level skill for OpenStack. Each sub-skill can also be installed and used on its own.

| Skill | Covers |
|---|---|
| [openstack-auth](skills/openstack-auth/SKILL.md) | clouds.yaml, openrc, application credentials, projects, roles, quotas |
| [openstack-compute](skills/openstack-compute/SKILL.md) | Nova servers, flavors, keypairs, Glance images, resize/migrate, snapshots |
| [openstack-networking](skills/openstack-networking/SKILL.md) | Neutron networks, subnets, routers, security groups, floating IPs, ports |
| [openstack-storage](skills/openstack-storage/SKILL.md) | Cinder volumes, snapshots, backups; Swift containers and objects |
| [openstack-troubleshooting](skills/openstack-troubleshooting/SKILL.md) | Failed servers/volumes/networks, service health, logs, scheduling failures |
| [openstack-iac](skills/openstack-iac/SKILL.md) | Heat templates and Terraform/OpenTofu with the OpenStack provider |
| [openstack-kubernetes](skills/openstack-kubernetes/SKILL.md) | Magnum clusters, Octavia load balancers, cloud-provider-openstack |

## Routing

| User intent | Skill |
|---|---|
| Can't authenticate, set up a cloud, create app credentials, check quotas | openstack-auth |
| Launch, resize, rebuild, snapshot, or migrate a server; upload an image | openstack-compute |
| Connect servers to networks or the internet, open ports, fix connectivity config | openstack-networking |
| Create/attach/extend volumes, back up data, store objects | openstack-storage |
| Something is broken or stuck, or an error message needs explaining | openstack-troubleshooting |
| Describe infrastructure as code, create stacks, write Terraform | openstack-iac |
| Run Kubernetes on OpenStack, expose services with load balancers | openstack-kubernetes |

If a request spans skills (e.g. "launch a web server reachable from the internet"), start with the first logical step (networking) and move on to the next skill when it is done.

## Shared Rules (apply to every skill)

1. **Pick the cloud explicitly.** Use `--os-cloud <name>` or `export OS_CLOUD=<name>`. If several clouds exist in `clouds.yaml` and the user hasn't said which, ask.
2. **Verify auth first.** Run `openstack token issue -f value -c project_id` before a multi-step workflow. On failure, switch to openstack-auth.
3. **Parse machine output.** Use `-f json` (or `-f value -c <column>`) when you need values from a command; never scrape tables.
4. **Look before you change.** Run `list`/`show` to confirm names resolve to exactly one resource. Names are not unique in OpenStack; prefer IDs once known.
5. **Confirm destructive actions.** Before `delete`, `rebuild`, `set --state`, `purge`, evacuate, or anything affecting other projects, show what will be affected and get an explicit "yes".
6. **Never expose secrets.** Do not print passwords, application credential secrets, or tokens. Redact them in output and never commit `clouds.yaml`/`secure.yaml`.
7. **Know your role.** Commands marked *(admin)* need the admin role. If one returns HTTP 403, tell the user it requires operator privileges instead of retrying.
8. **Wait properly.** Use `--wait` where supported; otherwise poll `show` with a delay instead of assuming success.

## Helper Scripts

Some skills ship Python scripts built on `openstacksdk`. They declare their dependencies inline (PEP 723), so `uv run` installs them automatically:

```bash
uv run skills/openstack-auth/scripts/check_cloud.py --cloud mycloud
uv run skills/openstack-troubleshooting/scripts/diagnose_server.py --cloud mycloud <server>
```

Without uv: `pip install openstacksdk` and run them with `python`.

## Documentation

When unsure about a command or flag, check `openstack help <command>` first, then the upstream docs at https://docs.openstack.org/.
