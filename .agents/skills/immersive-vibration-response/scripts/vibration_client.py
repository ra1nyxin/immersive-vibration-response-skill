#!/usr/bin/env python3
"""Send a single command to the local ESP32 vibration bridge."""

from __future__ import annotations

import argparse
import socket


def build_command(args: argparse.Namespace) -> str:
    if args.action in {"ping", "status", "scan", "services", "stop"}:
        return args.action.upper()
    if args.action == "hit":
        return f"HIT {args.value}"
    if args.action == "set":
        return f"SET {args.value}"
    raise ValueError(f"unsupported action: {args.action}")


def send_command(host: str, port: int, command: str, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=timeout) as client:
        client.settimeout(timeout)
        client.sendall((command + "\n").encode("ascii"))
        response = bytearray()
        while not response.endswith(b"\n"):
            chunk = client.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
    return response.decode("ascii", errors="replace").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25363)
    parser.add_argument("--timeout", type=float, default=2.0)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for name in ("ping", "status", "scan", "services", "stop"):
        subparsers.add_parser(name)
    hit = subparsers.add_parser("hit", help="queue additive firmware damage, usually 1 through 10")
    hit.add_argument("value", type=float)
    set_level = subparsers.add_parser("set", help="set a direct firmware level, rarely needed")
    set_level.add_argument("value", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    print(send_command(arguments.host, arguments.port, build_command(arguments), arguments.timeout))
