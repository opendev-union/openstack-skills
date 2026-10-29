# Terraform / OpenTofu Reference

## Complete example: web server with network, volume, and floating IP

`versions.tf`:

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }
}

provider "openstack" {
  cloud = var.cloud
}
```

`variables.tf`:

```hcl
variable "cloud" { type = string }
variable "name" {
  type    = string
  default = "web"
}
variable "image_name" {
  type    = string
  default = "ubuntu-24.04"
}
variable "flavor_name" {
  type    = string
  default = "m1.small"
}
variable "key_pair" { type = string }
variable "cidr" {
  type    = string
  default = "10.40.0.0/24"
}
variable "ssh_source" {
  type        = string
  description = "CIDR allowed to SSH"
}
variable "external_network" {
  type    = string
  default = "public"
}
```

`main.tf`:

```hcl
data "openstack_networking_network_v2" "ext" {
  name     = var.external_network
  external = true
}

data "openstack_images_image_v2" "img" {
  name        = var.image_name
  most_recent = true
}

resource "openstack_networking_network_v2" "net" {
  name = "${var.name}-net"
}

resource "openstack_networking_subnet_v2" "subnet" {
  name            = "${var.name}-subnet"
  network_id      = openstack_networking_network_v2.net.id
  cidr            = var.cidr
  dns_nameservers = ["1.1.1.1"]
}

resource "openstack_networking_router_v2" "router" {
  name                = "${var.name}-router"
  external_network_id = data.openstack_networking_network_v2.ext.id
}

resource "openstack_networking_router_interface_v2" "iface" {
  router_id = openstack_networking_router_v2.router.id
  subnet_id = openstack_networking_subnet_v2.subnet.id
}

resource "openstack_networking_secgroup_v2" "web" {
  name = "${var.name}-sg"
}

resource "openstack_networking_secgroup_rule_v2" "ssh" {
  security_group_id = openstack_networking_secgroup_v2.web.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = var.ssh_source
}

resource "openstack_networking_secgroup_rule_v2" "http" {
  security_group_id = openstack_networking_secgroup_v2.web.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  remote_ip_prefix  = "0.0.0.0/0"
}

resource "openstack_networking_port_v2" "port" {
  name               = "${var.name}-port"
  network_id         = openstack_networking_network_v2.net.id
  security_group_ids = [openstack_networking_secgroup_v2.web.id]
  fixed_ip {
    subnet_id = openstack_networking_subnet_v2.subnet.id
  }
}

resource "openstack_compute_instance_v2" "server" {
  name        = var.name
  image_id    = data.openstack_images_image_v2.img.id
  flavor_name = var.flavor_name
  key_pair    = var.key_pair
  user_data   = file("${path.module}/cloud-init.yaml")

  network {
    port = openstack_networking_port_v2.port.id
  }

  lifecycle {
    ignore_changes = [image_id] # avoid replacement when a newer image is published
  }
}

resource "openstack_blockstorage_volume_v3" "data" {
  name = "${var.name}-data"
  size = 50
}

resource "openstack_compute_volume_attach_v2" "data" {
  instance_id = openstack_compute_instance_v2.server.id
  volume_id   = openstack_blockstorage_volume_v3.data.id
}

resource "openstack_networking_floatingip_v2" "fip" {
  pool = var.external_network
}

resource "openstack_networking_floatingip_associate_v2" "fip" {
  floating_ip = openstack_networking_floatingip_v2.fip.address
  port_id     = openstack_networking_port_v2.port.id
  depends_on  = [openstack_networking_router_interface_v2.iface]
}

output "public_ip" {
  value = openstack_networking_floatingip_v2.fip.address
}
```

## Boot from volume

```hcl
resource "openstack_compute_instance_v2" "db" {
  name        = "db"
  flavor_name = "m1.medium"
  key_pair    = var.key_pair

  block_device {
    uuid                  = data.openstack_images_image_v2.img.id
    source_type           = "image"
    destination_type      = "volume"
    volume_size           = 40
    boot_index            = 0
    delete_on_termination = false
  }

  network {
    port = openstack_networking_port_v2.db.id
  }
}
```

## Remote state on OpenStack object storage

The native `swift` backend was removed in Terraform 1.3. Use the `s3` backend against the cloud's S3-compatible endpoint (Swift `s3api` or Ceph RGW). Create keys with `openstack ec2 credentials create` and a container with `openstack container create terraform-state`.

```hcl
terraform {
  backend "s3" {
    bucket                      = "terraform-state"
    key                         = "web/terraform.tfstate"
    region                      = "us-east-1" # placeholder; ignored by most S3-compatible endpoints
    endpoints                   = { s3 = "https://s3.example.com" }
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
```

Pass the EC2 access/secret keys via `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, not in the file. State locking with `use_lockfile = true` requires Terraform 1.10+ and conditional-write support on the endpoint; otherwise coordinate runs another way (e.g. CI concurrency limits).

## Importing existing resources

```hcl
import {
  to = openstack_compute_instance_v2.legacy
  id = "<server-uuid>"
}
```

Then `terraform plan -generate-config-out=generated.tf`, review, and move the generated blocks into the module. Expect drift on `network`, `user_data`, and `block_device` blocks.

## Common provider errors

| Error | Fix |
|---|---|
| `Error creating OpenStack compute client: ... No suitable endpoint` | Wrong `region` or cloud lacks the service; check `openstack catalog list` |
| `Resource not found` on data source | Name mismatch or image not visible to the project |
| `Multiple results found` on data source | Add filters (`most_recent`, `visibility`, `tags`) |
| Floating IP associate fails with "not reachable" | Add `depends_on` on the router interface |
| Instance replaced on every plan | Attribute that forces new resource is changing; check plan for `# forces replacement` |
