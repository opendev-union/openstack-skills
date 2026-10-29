---
name: openstack-kubernetes
description: >
  Run Kubernetes on OpenStack. Use when creating or scaling Magnum clusters
  and cluster templates (`openstack coe`), creating Octavia load balancers,
  listeners, pools, members, and health monitors, or configuring
  cloud-provider-openstack (openstack-cloud-controller-manager, Cinder CSI,
  Manila CSI) so Kubernetes Services of type LoadBalancer and
  PersistentVolumes work on OpenStack. Also covers debugging LoadBalancer
  services stuck pending and PVCs stuck provisioning.
compatibility: Requires python-openstackclient with python-magnumclient and python-octaviaclient; kubectl and helm for cluster-side components.
metadata:
  version: "0.1.0"
---

# Kubernetes on OpenStack

Select the cloud with `--os-cloud <name>` or `OS_CLOUD`. Confirm before deleting clusters or load balancers.

Three building blocks:

1. **Magnum**: OpenStack-managed Kubernetes clusters (if the cloud offers it: `openstack catalog list | grep container-infra`).
2. **Octavia**: load balancers (`openstack loadbalancer ...`), used directly or by Kubernetes.
3. **cloud-provider-openstack**: in-cluster components that let Kubernetes create Octavia LBs and Cinder volumes. Magnum installs these for you; self-managed clusters (kubeadm, k3s, RKE2, Cluster API) need them installed.

## Magnum clusters

```bash
openstack coe cluster template list
openstack coe cluster template show <template> -f json     # check labels: kube_tag, CNI, driver
openstack coe cluster create k8s-1 \
  --cluster-template <template> \
  --master-count 3 --node-count 3 \
  --keypair mykey [--flavor m1.large] [--master-flavor m1.medium]
openstack coe cluster show k8s-1 -c status -c status_reason -c health_status
openstack coe cluster config k8s-1 --dir ~/.kube/k8s-1     # writes kubeconfig
export KUBECONFIG=~/.kube/k8s-1/config
```

| Task | Command |
|---|---|
| Scale workers | `openstack coe cluster resize k8s-1 5` |
| Node groups | `openstack coe nodegroup create k8s-1 gpu --flavor g1.large --node-count 2` |
| Upgrade | `openstack coe cluster upgrade k8s-1 <new-template>` |
| Delete | `openstack coe cluster delete k8s-1` |

Templates are usually provided by the operator; available labels depend on the Magnum driver (the Cluster API Helm driver and the legacy Heat driver differ). Read existing templates before writing new ones.

When creation fails, read `status_reason`. With the Heat driver, also run `openstack stack failures list --long <stack_id>` using the cluster's `stack_id`. Common causes: quota (instances, floating IPs, load balancers, security groups), image missing required properties (e.g. `os_distro`), or nodes unable to reach the Keystone/Magnum public endpoints.

## Octavia load balancers

```bash
openstack loadbalancer create --name web-lb --vip-subnet-id app-subnet --wait
openstack loadbalancer listener create --name web-http --protocol HTTP --protocol-port 80 --wait web-lb
openstack loadbalancer pool create --name web-pool --lb-algorithm ROUND_ROBIN \
  --listener web-http --protocol HTTP --wait
openstack loadbalancer member create --subnet-id app-subnet --address 10.20.0.11 --protocol-port 8080 --wait web-pool
openstack loadbalancer member create --subnet-id app-subnet --address 10.20.0.12 --protocol-port 8080 --wait web-pool
openstack loadbalancer healthmonitor create --delay 5 --timeout 3 --max-retries 3 \
  --type HTTP --url-path /healthz --wait web-pool
# Public access: floating IP on the VIP port
openstack floating ip create public --port $(openstack loadbalancer show web-lb -f value -c vip_port_id)
```

- Each change puts the LB in `PENDING_UPDATE`; further changes fail with 409 until it returns to `ACTIVE`. Use `--wait` on every step.
- Members must allow traffic from the LB in their security groups (amphora driver: from the VIP subnet; OVN provider: from the client source).
- TLS termination: listener `--protocol TERMINATED_HTTPS --default-tls-container-ref <barbican-secret-container>`.
- Providers: `openstack loadbalancer provider list`. `amphora` supports L7 and HTTP; `ovn` is L4 only (TCP/UDP/SCTP) but faster to create.
- Check status: `openstack loadbalancer status show web-lb` shows operating status for every listener, pool, and member.

## cloud-provider-openstack (self-managed clusters)

Create an application credential for the cluster (see openstack-auth), then a `cloud.conf`:

```ini
[Global]
auth-url = https://keystone.example.com:5000/v3
application-credential-id = <id>
application-credential-secret = <secret>
region = RegionOne

[LoadBalancer]
floating-network-id = <external-network-id>
subnet-id = <node-subnet-id>
```

```bash
kubectl -n kube-system create secret generic cloud-config --from-file=cloud.conf
helm repo add cpo https://kubernetes.github.io/cloud-provider-openstack
helm install occm cpo/openstack-cloud-controller-manager -n kube-system
helm install cinder-csi cpo/openstack-cinder-csi -n kube-system
```

Check each chart's values for how it consumes the secret: chart values change between releases, so read `helm show values` before installing. Kubelets must run with `--cloud-provider=external` for the controller manager to initialize nodes.

StorageClass for Cinder:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: cinder-ssd
provisioner: cinder.csi.openstack.org
parameters:
  type: ssd
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```

Useful Service annotations for Octavia: `loadbalancer.openstack.org/keep-floatingip`, `loadbalancer.openstack.org/internal: "true"` (no floating IP), `loadbalancer.openstack.org/flavor-id`, and `loadbalancer.openstack.org/proxy-protocol`.

## Debugging

| Symptom | Check |
|---|---|
| Service `type: LoadBalancer` stuck `<pending>` | `kubectl describe svc`; `kubectl -n kube-system logs` for openstack-cloud-controller-manager; Octavia/floating IP quota; `openstack loadbalancer list` for an LB in `ERROR` |
| LB `ACTIVE` but members `ERROR`/`OFFLINE` | Health monitor path/port; node security group allows NodePort range (30000-32767) from the LB |
| PVC stuck `Pending` | `kubectl describe pvc`; cinder-csi controller logs; volume type exists; Cinder quota; AZ of the volume vs. node (use `WaitForFirstConsumer`) |
| Volume attach timeout | `openstack volume show` status; node's `nova-compute` and `cinder-volume` health (see openstack-troubleshooting) |
| Nodes stay `NotReady` with taint `node.cloudprovider.kubernetes.io/uninitialized` | Cloud controller manager not running or can't authenticate |
| LB in `ERROR` / stuck `PENDING_*` | Operator: `openstack loadbalancer amphora list --loadbalancer <lb>`, Octavia worker/health-manager logs, then `openstack loadbalancer failover <lb>` |
