# OpenStack Agent Skills

Agent skills that teach AI coding agents (Cursor, Claude Code, Codex, Copilot, Kiro, and others that support the [Agent Skills](https://agentskills.io) format) how to use and operate OpenStack clouds with the `openstack` CLI and `openstacksdk`.

They cover both **cloud users** (launch servers, build networks, manage volumes) and **operators** (service health, scheduling failures, stuck resources, log tracing), targeting generic upstream OpenStack.

## Skills

| Skill | Covers |
|---|---|
| [openstack-skills](SKILL.md) | Top-level router and shared safety rules |
| [openstack-auth](skills/openstack-auth/SKILL.md) | clouds.yaml, application credentials, projects, roles, quotas |
| [openstack-compute](skills/openstack-compute/SKILL.md) | Nova servers, flavors, keypairs, Glance images, migrations |
| [openstack-networking](skills/openstack-networking/SKILL.md) | Neutron networks, routers, security groups, floating IPs, ports |
| [openstack-storage](skills/openstack-storage/SKILL.md) | Cinder volumes, snapshots, backups; Swift objects |
| [openstack-troubleshooting](skills/openstack-troubleshooting/SKILL.md) | Failed resources, service health, logs, scheduling |
| [openstack-iac](skills/openstack-iac/SKILL.md) | Heat templates, Terraform/OpenTofu provider |
| [openstack-kubernetes](skills/openstack-kubernetes/SKILL.md) | Magnum, Octavia, cloud-provider-openstack |

## Install

Copy the skills into your agent's skills directory:

| Agent | Project location | Personal location |
|---|---|---|
| Cursor | `.cursor/skills/` | `~/.cursor/skills/` |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Others | `.agents/skills/` | `~/.agents/skills/` |

All skills, as one bundle (the top-level `SKILL.md` routes to the others):

```bash
git clone <repo-url> ~/.cursor/skills/openstack-skills
```

Individual skills (each one is self-contained):

```bash
cp -r skills/openstack-troubleshooting ~/.cursor/skills/
```

```powershell
Copy-Item -Recurse skills\openstack-troubleshooting $HOME\.cursor\skills\
```

To pick up changes automatically while developing, symlink instead of copying (`ln -s` on Linux/macOS, `New-Item -ItemType SymbolicLink` on Windows).

## Prerequisites

- [python-openstackclient](https://docs.openstack.org/python-openstackclient/latest/) (`pip install python-openstackclient`), plus `python-heatclient`, `python-octaviaclient`, `python-magnumclient`, and `osc-placement` for the corresponding skills
- A `clouds.yaml` with at least one cloud (see [openstack-auth](skills/openstack-auth/SKILL.md))
- [uv](https://docs.astral.sh/uv/) to run the helper scripts (they declare dependencies inline), or Python 3.10+ with `openstacksdk`

## Helper scripts

| Script | Purpose |
|---|---|
| `skills/openstack-auth/scripts/check_cloud.py` | Identity, service catalog, quotas, admin detection |
| `skills/openstack-troubleshooting/scripts/diagnose_server.py` | One-shot server diagnostics with hints |

```bash
uv run skills/openstack-auth/scripts/check_cloud.py --cloud mycloud
uv run skills/openstack-troubleshooting/scripts/diagnose_server.py --cloud mycloud web-1
```

## Contributing

- One skill per directory under `skills/`, with a `SKILL.md` whose `name` matches the directory.
- Keep `SKILL.md` under 500 lines; move long examples into sibling reference files linked from `SKILL.md`.
- Each skill must work when installed alone: don't link to files in other skills, refer to other skills by name instead.
- Mark admin-only commands with *(admin)* and require confirmation for destructive actions.
- Run the validator before committing:

```bash
uv run scripts/validate_skills.py
```
