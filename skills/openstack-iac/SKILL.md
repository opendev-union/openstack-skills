---
name: openstack-iac
description: >
  Define OpenStack infrastructure as code with Heat (HOT templates) or
  Terraform/OpenTofu using the terraform-provider-openstack provider. Use when
  writing or debugging Heat templates and stacks, `openstack stack` commands,
  CREATE_FAILED/UPDATE_FAILED stacks, Terraform resources like
  openstack_compute_instance_v2 or openstack_networking_network_v2, provider
  configuration with clouds.yaml, or importing existing OpenStack resources.
compatibility: Heat requires python-heatclient and a cloud with the orchestration service. Terraform requires Terraform >= 1.5 or OpenTofu.
metadata:
  version: "0.1.0"
---

# OpenStack Infrastructure as Code

## Choosing a tool

- **Heat**: native to the cloud, no external state file, and used under the hood by some services (e.g. Magnum's Heat driver). Only works if the cloud deploys Heat: check `openstack catalog list | grep orchestration`.
- **Terraform/OpenTofu**: works on any OpenStack cloud, multi-cloud, larger ecosystem. Needs remote state storage (the cloud's S3-compatible endpoint works well).

Default to Terraform unless the user already uses Heat or the cloud lacks external access for Terraform runners.

## Heat quick reference

```bash
openstack orchestration template validate -t stack.yaml -e env.yaml
openstack stack create -t stack.yaml -e env.yaml --parameter key_name=mykey --wait web
openstack stack list
openstack stack output show web --all
openstack stack update -t stack.yaml -e env.yaml --dry-run web    # preview changes
openstack stack update -t stack.yaml -e env.yaml --wait web
openstack stack delete --wait web                                   # confirm first
```

### Debugging failed stacks

```bash
openstack stack failures list --long web          # failed resources with error messages, nested too
openstack stack event list --nested-depth 3 web
openstack stack resource list -n 3 --filter status=CREATE_FAILED web
```

The error usually names the underlying API error (quota, flavor not found, no valid host). Fix it with the relevant skill, then `openstack stack update` or, for a failed create, delete and recreate. `openstack stack check web` refreshes resource status if the stack and reality have drifted.

See [heat.md](heat.md) for a complete template (network, router, security group, server, floating IP) and common intrinsic functions.

## Terraform quick reference

```hcl
terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }
}

provider "openstack" {
  cloud = "mycloud"   # entry in clouds.yaml; no credentials in .tf files
}
```

```bash
terraform init && terraform plan -out tfplan && terraform apply tfplan
terraform import openstack_compute_instance_v2.web <server-id>
```

- Keep credentials in `clouds.yaml`/`secure.yaml` or `OS_*` env vars, never in `.tf` files or committed `.tfvars`.
- Look up shared resources with data sources (`openstack_images_image_v2`, `openstack_networking_network_v2` with `external = true`, `openstack_compute_flavor_v2`) instead of hardcoding IDs.
- Attach floating IPs and security groups through Neutron ports (`openstack_networking_port_v2`, `openstack_networking_floatingip_associate_v2`). The older compute-API floating IP and security group resources are deprecated.
- Changing `image_id`, `flavor_name` (unless resize is allowed), `user_data`, or `key_pair` on `openstack_compute_instance_v2` forces replacement. Point this out in plan reviews and suggest `lifecycle { ignore_changes = [image_id] }` when images are updated regularly.

See [terraform.md](terraform.md) for a full working module (network, router, security group, port, server, volume, floating IP) and a remote state backend on OpenStack object storage.

If the terraform-skill is available, use it for general Terraform concerns (module structure, testing, state operations, CI). This skill covers only the OpenStack-specific parts.
