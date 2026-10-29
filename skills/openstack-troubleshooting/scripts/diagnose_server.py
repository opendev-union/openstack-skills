# /// script
# requires-python = ">=3.10"
# dependencies = ["openstacksdk>=3.0"]
# ///
"""Collect diagnostics for one OpenStack server in a single pass.

Gathers status, fault, recent instance actions and events, ports, security
group rules, floating IPs, attached volumes, and the console log tail.

Usage:
    uv run diagnose_server.py --cloud mycloud <server-name-or-id> [--json] [--log-lines 40]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import openstack
from openstack import exceptions


def _try(fn, label: str, errors: list[str]) -> Any:
    try:
        return fn()
    except exceptions.ForbiddenException:
        errors.append(f"{label}: forbidden (requires more privileges)")
    except exceptions.SDKException as exc:
        errors.append(f"{label}: {str(exc).splitlines()[0]}")
    return None


def server_summary(server) -> dict:
    flavor = server.flavor or {}
    return {
        "id": server.id,
        "name": server.name,
        "status": server.status,
        "vm_state": server.vm_state,
        "task_state": server.task_state,
        "power_state": server.power_state,
        "fault": server.fault,
        "flavor": flavor.get("original_name") or flavor.get("id"),
        "flavor_detail": {k: flavor.get(k) for k in ("vcpus", "ram", "disk") if k in flavor},
        "image_id": (server.image or {}).get("id") or "(boot from volume)",
        "key_name": server.key_name,
        "availability_zone": server.availability_zone,
        "host": server.compute_host,
        "hypervisor_hostname": server.hypervisor_hostname,
        "instance_name": server.instance_name,
        "created_at": server.created_at,
        "updated_at": server.updated_at,
        "locked": server.is_locked,
    }


def action_history(conn, server, errors: list[str], limit: int = 5) -> list[dict]:
    actions = _try(lambda: list(conn.compute.server_actions(server)), "instance actions", errors) or []
    out = []
    for action in actions[:limit]:
        entry = {
            "action": action.action,
            "request_id": action.request_id,
            "start_time": action.start_time,
            "message": action.message,
            "events": [],
        }
        detail = _try(
            lambda a=action: conn.compute.get_server_action(a.request_id, server),
            f"events for {action.request_id}",
            errors,
        )
        for ev in (detail.events if detail else None) or []:
            ev = ev if isinstance(ev, dict) else ev.to_dict()
            entry["events"].append({
                "event": ev.get("event"),
                "result": ev.get("result"),
                "start_time": ev.get("start_time"),
                "finish_time": ev.get("finish_time"),
                "host": ev.get("host"),
                "traceback": (ev.get("traceback") or "").strip().splitlines()[-1:] or None,
            })
        out.append(entry)
    return out


def network_details(conn, server, errors: list[str]) -> list[dict]:
    ports = _try(lambda: list(conn.network.ports(device_id=server.id)), "ports", errors) or []
    sg_cache: dict[str, dict] = {}
    out = []
    for port in ports:
        sgs = []
        for sg_id in port.security_group_ids or []:
            if sg_id not in sg_cache:
                sg = _try(lambda i=sg_id: conn.network.get_security_group(i), f"security group {sg_id}", errors)
                sg_cache[sg_id] = {
                    "id": sg_id,
                    "name": sg.name if sg else None,
                    "ingress": [
                        _rule_str(r) for r in (sg.security_group_rules if sg else []) if r.get("direction") == "ingress"
                    ],
                }
            sgs.append(sg_cache[sg_id])
        fips = _try(lambda p=port: list(conn.network.ips(port_id=p.id)), "floating ips", errors) or []
        out.append({
            "port_id": port.id,
            "network_id": port.network_id,
            "status": port.status,
            "fixed_ips": [f["ip_address"] for f in port.fixed_ips or []],
            "mac": port.mac_address,
            "port_security": port.is_port_security_enabled,
            "binding_vif_type": port.binding_vif_type,
            "binding_host": port.binding_host_id,
            "floating_ips": [f.floating_ip_address for f in fips],
            "security_groups": sgs,
        })
    return out


def _rule_str(rule: dict) -> str:
    proto = rule.get("protocol") or "any"
    lo, hi = rule.get("port_range_min"), rule.get("port_range_max")
    ports = "" if lo is None else (f":{lo}" if lo == hi else f":{lo}-{hi}")
    src = rule.get("remote_ip_prefix") or (f"sg:{rule['remote_group_id']}" if rule.get("remote_group_id") else "any")
    return f"{rule.get('ethertype', 'IPv4')} {proto}{ports} from {src}"


def volume_details(conn, server, errors: list[str]) -> list[dict]:
    out = []
    for att in server.attached_volumes or []:
        vol_id = att.get("id") if isinstance(att, dict) else att
        vol = _try(lambda v=vol_id: conn.block_storage.get_volume(v), f"volume {vol_id}", errors)
        if vol:
            out.append({
                "id": vol.id,
                "name": vol.name,
                "status": vol.status,
                "size_gb": vol.size,
                "bootable": vol.is_bootable,
                "devices": [a.get("device") for a in vol.attachments or [] if a.get("server_id") == server.id],
            })
        else:
            out.append({"id": vol_id, "status": "unknown"})
    return out


def console_tail(conn, server, lines: int, errors: list[str]) -> list[str]:
    if server.status in ("BUILD", "ERROR") and not server.compute_host:
        return []
    res = _try(lambda: conn.compute.get_server_console_output(server, length=lines), "console log", errors)
    text = (res or {}).get("output", "") if isinstance(res, dict) else ""
    return text.splitlines()[-lines:]


def hints(report: dict) -> list[str]:
    out = []
    s = report["server"]
    fault = (s.get("fault") or {}).get("message", "")
    if "No valid host" in fault:
        out.append("Scheduling failed: try a smaller flavor or another AZ; operators should check placement candidates and scheduler logs.")
    if "maximum number of retries" in fault.lower():
        out.append("Spawn failed on multiple hosts: check nova-compute logs on the hosts named in instance events.")
    if s["status"] == "BUILD":
        out.append("Still building: check the latest action's events for a step that never finished.")
    for p in report["ports"]:
        if p["binding_vif_type"] == "binding_failed":
            out.append(f"Port {p['port_id']} binding failed: Neutron agent on {p['binding_host']} is likely down or misconfigured.")
        if p["status"] != "ACTIVE" and s["status"] == "ACTIVE":
            out.append(f"Port {p['port_id']} is {p['status']} while the server is ACTIVE: data-plane/agent issue.")
        if s["status"] == "ACTIVE" and not p["floating_ips"]:
            out.append(f"Port {p['port_id']} has no floating IP: not reachable from external networks.")
        if p["port_security"] and not any(sg["ingress"] for sg in p["security_groups"]):
            out.append(f"Port {p['port_id']}: security groups allow no ingress traffic.")
    log = "\n".join(report["console_log_tail"])
    if "169.254.169.254" in log and ("timed out" in log.lower() or "failed" in log.lower()):
        out.append("Console log shows metadata service failures: cloud-init could not fetch keys/user data.")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("server", help="Server name or ID")
    parser.add_argument("--cloud", help="Cloud name from clouds.yaml (default: $OS_CLOUD)")
    parser.add_argument("--all-projects", action="store_true", help="Search all projects (admin)")
    parser.add_argument("--log-lines", type=int, default=40, help="Console log lines to include")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    try:
        conn = openstack.connect(cloud=args.cloud)
        server = conn.compute.find_server(args.server, ignore_missing=False, all_projects=args.all_projects)
        server = conn.compute.get_server(server.id)
    except exceptions.DuplicateResource:
        print(f"Multiple servers named '{args.server}'; pass the ID instead.", file=sys.stderr)
        return 2
    except exceptions.ResourceNotFound:
        print(f"Server '{args.server}' not found (use --all-projects as admin for other projects).", file=sys.stderr)
        return 2
    except exceptions.SDKException as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors: list[str] = []
    report = {
        "server": server_summary(server),
        "actions": action_history(conn, server, errors),
        "ports": network_details(conn, server, errors),
        "volumes": volume_details(conn, server, errors),
        "console_log_tail": console_tail(conn, server, args.log_lines, errors),
        "collection_errors": errors,
    }
    report["hints"] = hints(report)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    s = report["server"]
    print(f"Server {s['name']} ({s['id']})")
    print(f"  status={s['status']} vm_state={s['vm_state']} task_state={s['task_state']} power_state={s['power_state']}")
    print(f"  flavor={s['flavor']} {s['flavor_detail']} image={s['image_id']} key={s['key_name']}")
    print(f"  az={s['availability_zone']} host={s['host']} instance_name={s['instance_name']}")
    if s["fault"]:
        print(f"  FAULT: {s['fault'].get('code')} {s['fault'].get('message')}")
    print("\nRecent actions:")
    for a in report["actions"]:
        print(f"  {a['start_time']} {a['action']} {a['request_id']} {a['message'] or ''}")
        for e in a["events"]:
            tb = f"  <- {e['traceback'][0]}" if e["traceback"] else ""
            print(f"      {e['event']}: {e['result']} host={e['host']}{tb}")
    print("\nPorts:")
    for p in report["ports"]:
        print(f"  {p['port_id']} status={p['status']} ips={p['fixed_ips']} fip={p['floating_ips']} "
              f"vif={p['binding_vif_type']} host={p['binding_host']} port_security={p['port_security']}")
        for sg in p["security_groups"]:
            print(f"    sg {sg['name']}: {'; '.join(sg['ingress']) or '(no ingress rules)'}")
    if report["volumes"]:
        print("\nVolumes:")
        for v in report["volumes"]:
            print(f"  {v['id']} {v.get('name') or ''} status={v['status']} size={v.get('size_gb')} devices={v.get('devices')}")
    if report["console_log_tail"]:
        print(f"\nConsole log (last {len(report['console_log_tail'])} lines):")
        for line in report["console_log_tail"]:
            print(f"  | {line}")
    if errors:
        print("\nCould not collect:")
        for e in errors:
            print(f"  - {e}")
    if report["hints"]:
        print("\nHints:")
        for h in report["hints"]:
            print(f"  * {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
