#!/usr/bin/env python3
"""Run a local shell script on a Lighthouse instance through TAT.

This is the shared transport layer for all instance-level operations. The
script itself remains an ordinary local .sh file.
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.tat.v20201028 import models, tat_client


TERMINAL_STATES = {
    "SUCCESS", "FAILED", "TIMEOUT", "TASK_TIMEOUT", "DELIVER_FAILED",
    "START_FAILED", "CANCELLED", "TERMINATED",
}


def make_profile(endpoint: str) -> ClientProfile:
    http = HttpProfile()
    http.endpoint = endpoint
    profile = ClientProfile()
    profile.httpProfile = http
    return profile


def decode_output(value: str | None) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value, validate=True).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return value


def parse_parameter_env(values: list[str]) -> dict[str, str]:
    parameters = {}
    for value in values:
        try:
            name, env_name = value.split("=", 1)
        except ValueError as error:
            raise RuntimeError(f"Invalid --parameter-env value {value!r}; expected NAME=ENV_VAR") from error
        if not name or not env_name:
            raise RuntimeError(f"Invalid --parameter-env value {value!r}")
        secret = os.getenv(env_name)
        if not secret:
            raise RuntimeError(f"Environment variable {env_name} is empty or unset")
        parameters[name] = secret
    return parameters


def run_script(args: argparse.Namespace, script: str, parameters: dict[str, str]) -> int:
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    if not secret_id or not secret_key:
        raise RuntimeError("Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY first.")

    content = script if script.startswith("#!") else "#!/bin/bash\n" + script
    client = tat_client.TatClient(
        credential.Credential(secret_id, secret_key),
        args.region,
        make_profile("tat.tencentcloudapi.com"),
    )
    request = models.RunCommandRequest()
    request.Content = base64.b64encode(content.encode("utf-8")).decode("ascii")
    request.InstanceIds = [args.instance_id]
    request.CommandName = args.command_name
    request.Description = args.description
    request.CommandType = "SHELL"
    request.Timeout = min(args.timeout, 86400)
    request.SaveCommand = False
    if parameters:
        request.EnableParameter = True
        request.Parameters = json.dumps(parameters, ensure_ascii=False)
    started = json.loads(client.RunCommand(request).to_json_string())
    invocation_id = started["InvocationId"]
    print(json.dumps({"invocation_id": invocation_id, "command_id": started.get("CommandId")}, indent=2))

    deadline = time.monotonic() + args.wait_seconds
    last_status = None
    while time.monotonic() < deadline:
        query = models.DescribeInvocationTasksRequest()
        invocation_filter = models.Filter()
        invocation_filter.Name = "invocation-id"
        invocation_filter.Values = [invocation_id]
        query.Filters = [invocation_filter]
        query.Limit = 100
        query.HideOutput = False
        response = json.loads(client.DescribeInvocationTasks(query).to_json_string())
        tasks = response.get("InvocationTaskSet", [])
        task = next((item for item in tasks if item.get("InstanceId") == args.instance_id), None)
        if task:
            status = task.get("TaskStatus")
            if status != last_status:
                print(f"TAT task status: {status}")
                last_status = status
            if status in TERMINAL_STATES:
                result = task.get("TaskResult") or {}
                print("== remote output ==")
                print(decode_output(result.get("Output")), end="")
                if result.get("ExitCode") not in (None, 0):
                    print(f"\nRemote exit code: {result['ExitCode']}", file=sys.stderr)
                return 0 if status == "SUCCESS" else 2
        time.sleep(args.poll_seconds)
    print(f"Timed out waiting {args.wait_seconds}s for {invocation_id}.", file=sys.stderr)
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--region", default="ap-beijing")
    parser.add_argument("--command-name", default="dsh-scheduler-command")
    parser.add_argument("--description", default="Cloud scheduler instance command")
    parser.add_argument("--timeout", type=int, default=300, help="Remote command timeout in seconds")
    parser.add_argument("--wait-seconds", type=int, default=360, help="How long to poll TAT")
    parser.add_argument("--poll-seconds", type=int, default=3)
    parser.add_argument(
        "--parameter-env", action="append", default=[], metavar="NAME=ENV_VAR",
        help="Pass an environment variable as a TAT hidden parameter (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the script without submitting it")
    args = parser.parse_args()
    if args.timeout < 1 or args.wait_seconds < 1 or args.poll_seconds < 1:
        parser.error("timeout, wait-seconds, and poll-seconds must be positive")
    try:
        script = args.script.read_text(encoding="utf-8")
        if not script.strip():
            raise RuntimeError(f"Script is empty: {args.script}")
        if args.dry_run:
            print(script, end="")
            return 0
        return run_script(args, script, parse_parameter_env(args.parameter_env))
    except (OSError, RuntimeError, TencentCloudSDKException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
