# /// script
# requires-python = ">=3.10"
# dependencies = ["openstacksdk>=3.0"]
# ///
"""Report identity, service catalog, quotas, and admin access for an OpenStack cloud.

Usage:
    uv run check_cloud.py --cloud mycloud [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

import openstack
from openstack import exceptions


def _safe(fn, default=None):
    try:
        return fn()
    except exceptions.SDKException as exc:
        return default if default is not None else {"error": str(exc).splitlines()[0]}


def identity_info(conn: openstack.connection.Connection) -> dict:
    access = conn.session.auth.get_access(conn.session)
    return {
        "auth_url": conn.config.get_auth_args().get("auth_url"),
        "region": conn.config.get_region_name(),
        "user": access.username,
        "user_id": access.user_id,
        "project": access.project_name,
        "project_id": access.project_id,
        "roles": sorted(access.role_names or []),
        "token_expires": access.expires.isoformat() if access.expires else None,
    }


def catalog_info(conn: openstack.connection.Connection) -> list[dict]:
    access = conn.session.auth.get_access(conn.session)
    region = conn.config.get_region_name()
    interface = conn.config.get_interface() or "public"
    services = []
    for svc in access.service_catalog.catalog:
        url = None
        for ep in svc.get("endpoints", []):
            if ep.get("interface") == interface and (not region or ep.get("region_id", ep.get("region")) == region):
                url = ep.get("url")
                break
        services.append({"type": svc.get("type"), "name": svc.get("name"), "url": url})
    return sorted(services, key=lambda s: s["type"] or "")


def compute_quota(conn, project_id: str) -> dict:
    limits = conn.compute.get_limits().absolute
    return {
        "instances": f"{limits.instances_used}/{limits.instances}",
        "cores": f"{limits.total_cores_used}/{limits.total_cores}",
        "ram_mb": f"{limits.total_ram_used}/{limits.total_ram}",
        "keypairs": limits.keypairs,
    }


def volume_quota(conn, project_id: str) -> dict:
    q = conn.block_storage.get_quota_set(project_id, usage=True)
    usage = q.usage or {}
    return {
        k: f"{usage.get(k, '?')}/{getattr(q, k)}"
        for k in ("volumes", "gigabytes", "snapshots", "backups")
        if getattr(q, k, None) is not None
    }


def network_quota(conn, project_id: str) -> dict:
    q = conn.network.get_quota(project_id, details=True)
    out = {}
    for k in ("networks", "subnets", "ports", "routers", "floating_ips", "security_groups", "security_group_rules"):
        d = getattr(q, k, None)
        if isinstance(d, dict):
            out[k] = f"{d.get('used', '?')}/{d.get('limit', '?')}"
        elif d is not None:
            out[k] = str(d)
    return out


def is_admin(conn) -> bool:
    try:
        list(conn.compute.services())
        return True
    except exceptions.ForbiddenException:
        return False
    except exceptions.SDKException:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cloud", help="Cloud name from clouds.yaml (default: $OS_CLOUD)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    try:
        conn = openstack.connect(cloud=args.cloud)
        ident = identity_info(conn)
    except exceptions.SDKException as exc:
        print(f"AUTH FAILED: {exc}", file=sys.stderr)
        print("Check OS_CLOUD/--cloud, clouds.yaml location, and leftover OS_* env vars.", file=sys.stderr)
        return 1

    services = catalog_info(conn)
    types = {s["type"] for s in services}
    pid = ident["project_id"]

    report = {
        "identity": ident,
        "services": services,
        "quotas": {
            "compute": _safe(lambda: compute_quota(conn, pid)) if "compute" in types else None,
            "volume": _safe(lambda: volume_quota(conn, pid)) if types & {"block-storage", "volumev3"} else None,
            "network": _safe(lambda: network_quota(conn, pid)) if "network" in types else None,
        },
        "admin_api_access": is_admin(conn) if "compute" in types else None,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    i = report["identity"]
    print(f"Cloud:    {args.cloud or '(OS_CLOUD)'}  region={i['region']}")
    print(f"User:     {i['user']} ({i['user_id']})")
    print(f"Project:  {i['project']} ({i['project_id']})")
    print(f"Roles:    {', '.join(i['roles']) or '-'}")
    print(f"Token expires: {i['token_expires']}")
    print(f"Admin API access: {report['admin_api_access']}")
    print("\nServices:")
    for s in services:
        print(f"  {s['type']:<16} {s['name'] or '':<14} {s['url'] or '(no endpoint for region/interface)'}")
    print("\nQuotas (used/limit, -1 = unlimited):")
    for area, q in report["quotas"].items():
        if q:
            print(f"  {area}: " + ", ".join(f"{k}={v}" for k, v in q.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
