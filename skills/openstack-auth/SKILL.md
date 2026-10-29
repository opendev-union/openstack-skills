---
name: openstack-auth
description: >
  Configure and verify OpenStack authentication and project access. Use when
  setting up clouds.yaml or openrc files, creating application credentials,
  fixing "The request you have made requires authentication" (HTTP 401) or
  "Missing value auth-url" errors, switching projects or clouds, checking
  roles, service catalog endpoints, quotas, or usage limits. Also covers
  Keystone admin tasks such as creating projects, users, and role assignments.
compatibility: Requires python-openstackclient. check_cloud.py requires uv or openstacksdk.
metadata:
  version: "0.1.0"
---

# OpenStack Authentication & Projects

## Quick check

```bash
uv run scripts/check_cloud.py --cloud <name>      # identity, endpoints, quotas, admin detection
openstack --os-cloud <name> token issue           # minimal auth test
```

Run `check_cloud.py` first when starting work on an unfamiliar cloud: it reports who you are, which services exist, and how much quota is left.

## Where credentials come from

The CLI resolves auth in this order: command-line `--os-*` flags, then `OS_*` environment variables, then `clouds.yaml` entry selected by `--os-cloud`/`OS_CLOUD`.

`clouds.yaml` search path: `./clouds.yaml`, `~/.config/openstack/clouds.yaml`, `/etc/openstack/clouds.yaml`. Secrets can live separately in `secure.yaml` in the same directories (merged by cloud name).

**Stale `OS_*` variables are the most common cause of confusing auth errors.** If a sourced openrc is mixing with clouds.yaml, clear them:

```bash
unset $(env | grep -o '^OS_[A-Z_]*' | grep -v '^OS_CLOUD$')
```

## clouds.yaml templates

Application credential (preferred for automation; no password stored, scoped to one project):

```yaml
clouds:
  mycloud:
    auth_type: v3applicationcredential
    auth:
      auth_url: https://keystone.example.com:5000/v3
      application_credential_id: "<id>"
      application_credential_secret: "<secret>"
    region_name: RegionOne
    interface: public
    identity_api_version: 3
```

Password auth:

```yaml
clouds:
  mycloud:
    auth:
      auth_url: https://keystone.example.com:5000/v3
      username: alice
      password: "<password>"          # better: put this in secure.yaml
      project_name: demo
      user_domain_name: Default
      project_domain_name: Default
    region_name: RegionOne
    identity_api_version: 3
```

For self-signed endpoints add `cacert: /path/to/ca.pem` (preferred) or `verify: false` (testing only; warn the user).

Converting an openrc: map `OS_AUTH_URL`→`auth_url`, `OS_USERNAME`→`username`, `OS_PROJECT_NAME`→`project_name`, `OS_USER_DOMAIN_NAME`→`user_domain_name`, `OS_PROJECT_DOMAIN_NAME`→`project_domain_name`, `OS_REGION_NAME`→`region_name`, `OS_INTERFACE`→`interface`.

## Application credentials

```bash
openstack application credential create ci-deployer \
  --description "CI pipeline" --expiration 2027-12-31T00:00:00 \
  --role member -f json
openstack application credential list
openstack application credential delete <name-or-id>
```

- The secret is shown **only once** at creation. Write it straight into `clouds.yaml`/`secure.yaml`; do not echo it in chat.
- Credentials are restricted by default: they cannot create other application credentials or trusts. `--unrestricted` lifts that; it is needed for some tooling (e.g. Magnum/Heat trusts) but warn about the risk.
- Use `--access-rules` to limit a credential to specific API paths when the cloud supports it.

## Diagnosing auth errors

| Symptom | Likely cause / fix |
|---|---|
| `Missing value auth-url required for auth plugin password` | No cloud selected: set `OS_CLOUD` or pass `--os-cloud`; check clouds.yaml path/name |
| HTTP 401 | Wrong password/secret, expired app credential, wrong user domain |
| HTTP 401 *"Expecting to find domain in project"* | Add `project_domain_name`/`user_domain_name` |
| HTTP 403 on a command | Missing role for that action (often admin-only) |
| `Could not find requested endpoint in Service Catalog` | Service not deployed, wrong `region_name`, or wrong `interface` |
| SSL `CERTIFICATE_VERIFY_FAILED` | Set `cacert`; system CA bundle lacks the cloud's CA |
| Works in one shell, not another | Leftover `OS_*` env vars (see above) |

Add `--debug` to see the exact auth request and catalog; redact tokens before sharing that output.

## Projects, roles, quotas

```bash
openstack project list --my-projects
openstack role assignment list --user <user> --names --effective
openstack catalog list
openstack quota show                 # current project
openstack limits show --absolute     # usage vs. limits (compute, volume)
```

Admin tasks *(admin)*:

```bash
openstack project create --domain Default --description "Team A" team-a
openstack user create --domain Default --password-prompt alice
openstack role add --project team-a --user alice member
openstack quota set --cores 40 --ram 102400 --instances 20 team-a
openstack quota set --volumes 20 --gigabytes 2000 team-a
openstack quota set --floating-ips 10 --networks 5 --ports 100 team-a
```

Default roles are `reader`, `member`, and `admin` (older clouds may use `_member_`). Check `openstack role list` before assigning.
