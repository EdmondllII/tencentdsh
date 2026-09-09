#!/usr/bin/env python3
"""Non-destructively inspect a Lighthouse DeepSeek Harness image through TAT.

Credentials are deliberately read only from TENCENTCLOUD_SECRET_ID and
TENCENTCLOUD_SECRET_KEY. The remote probe does not create, stop, delete, or
reconfigure resources; it only reads process, listening-port, and HTTP state.
"""

import argparse
import base64
import json
import os
import sys
import time

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.lighthouse.v20200324 import lighthouse_client
from tencentcloud.lighthouse.v20200324 import models as lighthouse_models
from tencentcloud.tat.v20201028 import tat_client
from tencentcloud.tat.v20201028 import models as tat_models


REMOTE_PROBE = r"""set -u
echo '== identity =='
id
uname -a
echo '== dsh =='
command -v dsh || true
dsh --version 2>&1 || true
echo '== processes =='
pgrep -af '(^|/)(dsh|node)( |$)' || true
echo '== listening port 3080 =='
if command -v ss >/dev/null 2>&1; then
  ss -ltnp 2>&1 | grep -E '(:3080[[:space:]]|:3080$)' || true
elif command -v netstat >/dev/null 2>&1; then
  netstat -ltnp 2>&1 | grep -E '(:3080[[:space:]]|:3080$)' || true
else
  echo 'Neither ss nor netstat is available.'
fi
echo '== loopback HTTP =='
if command -v curl >/dev/null 2>&1; then
  curl --max-time 5 --silent --show-error --output /dev/null \
    --write-out 'http://127.0.0.1:3080/ -> %{http_code}\n' \
    http://127.0.0.1:3080/ || true
else
  echo 'curl is not available.'
fi
"""

TERMINAL_STATES = {
    "SUCCESS", "FAILED", "TIMEOUT", "TASK_TIMEOUT", "DELIVER_FAILED",
    "START_FAILED", "CANCELLED", "TERMINATED",
}


def client_profile(endpoint: str) -> ClientProfile:
    profile = ClientProfile()
    http_profile = HttpProfile()
    http_profile.endpoint = endpoint
    profile.httpProfile = http_profile
    return profile


def credentials() -> credential.Credential:
    secret_id = os.environ.get("TENCENTCLOUD_SECRET_ID")
    secret_key = os.environ.get("TENCENTCLOUD_SECRET_KEY")
    if not secret_id or not secret_key:
        raise RuntimeError(
            "Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY in the shell; "
            "do not put credentials in this script."
        )
    return credential.Credential(secret_id, secret_key)


def describe_instance(cred: credential.Credential, region: str, instance_id: str) -> dict:
    client = lighthouse_client.LighthouseClient(
        cred, region, client_profile("lighthouse.tencentcloudapi.com")
    )
    request = lighthouse_models.DescribeInstancesRequest()
    request.InstanceIds = [instance_id]
    response = json.loads(client.DescribeInstances(request).to_json_string())
    instances = response.get("InstanceSet", [])
    if len(instances) != 1:
        raise RuntimeError(f"Expected one instance for {instance_id}, got {len(instances)}")
    return instances[0]


def decode_output(value: str | None) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value, validate=True).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return value


def run_probe(cred: credential.Credential, region: str, instance_id: str, wait_seconds: int) -> int:
    client = tat_client.TatClient(cred, region, client_profile("tat.tencentcloudapi.com"))
    request = tat_models.RunCommandRequest()
    request.Content = base64.b64encode(REMOTE_PROBE.encode("utf-8")).decode("ascii")
    request.InstanceIds = [instance_id]
    request.CommandName = "dsh-readiness-probe"
    request.Description = "Read-only DSH and port readiness inspection"
    request.CommandType = "SHELL"
    request.Timeout = min(wait_seconds, 300)
    request.SaveCommand = False
    response = json.loads(client.RunCommand(request).to_json_string())
    invocation_id = response["InvocationId"]
    print(json.dumps({"invocation_id": invocation_id, "command_id": response.get("CommandId")}, indent=2))

    deadline = time.monotonic() + wait_seconds
    last_status = None
    while time.monotonic() < deadline:
        request = tat_models.DescribeInvocationTasksRequest()
        filter_by_invocation = tat_models.Filter()
        filter_by_invocation.Name = "invocation-id"
        filter_by_invocation.Values = [invocation_id]
        request.Filters = [filter_by_invocation]
        request.Limit = 100
        request.HideOutput = False
        result = json.loads(client.DescribeInvocationTasks(request).to_json_string())
        tasks = result.get("InvocationTaskSet", [])
        if tasks:
            task = next((item for item in tasks if item.get("InstanceId") == instance_id), tasks[0])
            status = task.get("TaskStatus")
            if status != last_status:
                print(f"TAT task status: {status}")
                last_status = status
            if status in TERMINAL_STATES:
                print("== remote probe output ==")
                task_result = task.get("TaskResult") or {}
                print(decode_output(task_result.get("Output")), end="")
                print("== task summary ==")
                print(json.dumps({
                    key: task.get(key)
                    for key in ("InvocationId", "InvocationTaskId", "CommandId",
                                "TaskStatus", "InstanceId", "StartTime", "EndTime")
                }, ensure_ascii=False, indent=2))
                if task_result.get("ExitCode") not in (None, 0):
                    print(json.dumps({
                        "ExitCode": task_result.get("ExitCode"),
                        "ErrorInfo": task.get("ErrorInfo"),
                    }, ensure_ascii=False, indent=2), file=sys.stderr)
                return 0 if status == "SUCCESS" else 2
        time.sleep(3)
    print(f"Timed out waiting {wait_seconds}s for TAT invocation {invocation_id}.", file=sys.stderr)
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", default="lhins-qojobi8w")
    parser.add_argument("--region", default="ap-beijing")
    parser.add_argument("--wait-seconds", type=int, default=90)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Submit the read-only remote probe. Without this flag only Lighthouse is queried.",
    )
    args = parser.parse_args()
    if args.wait_seconds < 10:
        parser.error("--wait-seconds must be at least 10")

    try:
        cred = credentials()
        instance = describe_instance(cred, args.region, args.instance_id)
        print("== Lighthouse instance ==")
        print(json.dumps({
            key: instance.get(key)
            for key in ("InstanceId", "InstanceState", "PublicAddresses", "BlueprintId", "OsName", "CreatedTime")
        }, ensure_ascii=False, indent=2))
        if not args.execute:
            print("No remote command submitted. Re-run with --execute to run the read-only TAT probe.")
            return 0
        return run_probe(cred, args.region, args.instance_id, args.wait_seconds)
    except (RuntimeError, TencentCloudSDKException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
