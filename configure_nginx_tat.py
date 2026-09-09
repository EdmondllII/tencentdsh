#!/usr/bin/env python3
"""Compatibility wrapper for the generic TAT script runner."""

import sys
from pathlib import Path

from tat_exec import main as tat_main


if __name__ == "__main__":
    execute = "--execute" in sys.argv[1:]
    if execute and not __import__("os").environ.get("MAASTAAT_PROXY_KEY"):
        raise SystemExit("Set MAASTAAT_PROXY_KEY before configuring Nginx.")
    sys.argv = [arg for arg in sys.argv if arg != "--execute"]
    sys.argv[0] = "tat_exec.py"
    sys.argv[1:1] = [
        "--instance-id", "lhins-qojobi8w",
        "--script", str(Path(__file__).parent / "scripts" / "configure_nginx.sh"),
        "--command-name", "configure-dsh-nginx",
        "--description", "Install and verify DSH reverse proxy",
        "--parameter-env", "proxy_key=MAASTAAT_PROXY_KEY",
    ]
    if not execute:
        sys.argv.append("--dry-run")
    raise SystemExit(tat_main())
