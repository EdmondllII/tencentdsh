#!/usr/bin/env python3
"""Inspect or add a Lighthouse firewall port rule.

The Lighthouse API replaces the complete rule list on modification, so this
script reads and preserves all existing rules before adding the requested one.
"""

import argparse
import json
import os
import sys

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.lighthouse.v20200324 import lighthouse_client, models


def profile() -> ClientProfile:
    http = HttpProfile()
    http.endpoint = "lighthouse.tencentcloudapi.com"
    result = ClientProfile()
    result.httpProfile = http
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", default="lhins-qojobi8w")
    parser.add_argument("--region", default="ap-beijing")
    parser.add_argument("--port", default="443")
    parser.add_argument("--protocol", default="TCP", choices=("TCP", "UDP"))
    parser.add_argument("--cidr", default="0.0.0.0/0", help="Allowed IPv4 source CIDR")
    parser.add_argument("--description", default="DSH Nginx reverse proxy")
    parser.add_argument(
        "--remove-port", action="append", default=[], metavar="PORT",
        help="Remove ACCEPT rules for this TCP/UDP port (repeatable)",
    )
    parser.add_argument("--execute", action="store_true", help="Apply the rule")
    args = parser.parse_args()

    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    if not secret_id or not secret_key:
        print("Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY first.", file=sys.stderr)
        return 1

    client = lighthouse_client.LighthouseClient(
        credential.Credential(secret_id, secret_key), args.region, profile()
    )
    query = models.DescribeFirewallRulesRequest()
    query.InstanceId = args.instance_id
    query.Limit = 100
    response = json.loads(client.DescribeFirewallRules(query).to_json_string())
    rules = response.get("FirewallRuleSet", [])
    print(json.dumps({
        "instance_id": args.instance_id,
        "firewall_version": response.get("FirewallVersion"),
        "rules": rules,
    }, ensure_ascii=False, indent=2))

    already_present = any(
        rule.get("Protocol") == args.protocol
        and rule.get("Port") == args.port
        and rule.get("CidrBlock") == args.cidr
        and rule.get("Action", "ACCEPT") == "ACCEPT"
        for rule in rules
    )
    removals = {
        (args.protocol, port)
        for port in args.remove_port
    }
    if already_present and not removals:
        print("Requested rule already exists; no change needed.")
        return 0
    if not args.execute:
        print("No change made. Re-run with --execute to apply the rule.")
        return 0

    outgoing = []
    for source in rules:
        if (
            source.get("Protocol"), source.get("Port")
        ) in removals and source.get("Action", "ACCEPT") == "ACCEPT":
            continue
        rule = models.FirewallRule()
        for key in ("Protocol", "Port", "CidrBlock", "Ipv6CidrBlock", "Action", "FirewallRuleDescription"):
            value = source.get(key)
            # DescribeFirewallRules returns unused fields as empty strings,
            # but ModifyFirewallRules rejects an explicitly empty CIDR field.
            if value not in (None, ""):
                setattr(rule, key, value)
        outgoing.append(rule)
    added = models.FirewallRule()
    added.Protocol = args.protocol
    added.Port = args.port
    added.CidrBlock = args.cidr
    added.Action = "ACCEPT"
    added.FirewallRuleDescription = args.description
    outgoing.append(added)

    update = models.ModifyFirewallRulesRequest()
    update.InstanceId = args.instance_id
    update.FirewallRules = outgoing
    if response.get("FirewallVersion") is not None:
        update.FirewallVersion = response["FirewallVersion"]
    result = client.ModifyFirewallRules(update)
    print("Firewall updated:", result.to_json_string())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TencentCloudSDKException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
