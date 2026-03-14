#!/usr/bin/env python3
"""Admin CLI for AU student subscriptions."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from student_registry import package_labels

DEFAULT_REGISTRY_URL = "https://arxiv-digest-relay.vercel.app/api/students"


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body)
            message = payload.get("error", exc.reason)
        except json.JSONDecodeError:
            message = body or exc.reason
        raise RuntimeError(str(message)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the student registry: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Student registry returned invalid JSON.") from exc


def fetch_subscriptions(
    registry_url: str,
    *,
    admin_token: str,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    result = post_json(
        registry_url,
        {
            "action": "admin_list",
            "admin_token": admin_token,
            "include_inactive": include_inactive,
        },
    )
    return list(result.get("subscriptions", []))


def resolve_admin_token(explicit: str | None) -> str:
    token = (explicit or os.environ.get("STUDENT_ADMIN_TOKEN", "")).strip()
    if token:
        return token
    return getpass.getpass("Student admin token: ").strip()


def render_subscription_rows(subscriptions: list[dict[str, Any]]) -> str:
    labels = package_labels()
    rows = []
    for item in subscriptions:
        package_text = ", ".join(labels.get(package_id, package_id) for package_id in item["package_ids"])
        state = "active" if item.get("active", True) else "inactive"
        rows.append(
            f"{item['email']} | {state} | {item['max_papers_per_week']}/week | {package_text}"
        )
    return "\n".join(rows)


def compute_package_counts(subscriptions: list[dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for item in subscriptions:
        for package_id in item.get("package_ids", []):
            counts[package_id] += 1
    return counts


def write_csv(path: Path, subscriptions: list[dict[str, Any]]) -> None:
    labels = package_labels()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["email", "active", "max_papers_per_week", "package_ids", "package_labels", "created_at", "updated_at"]
        )
        for item in subscriptions:
            package_ids = list(item.get("package_ids", []))
            writer.writerow(
                [
                    item.get("email", ""),
                    item.get("active", True),
                    item.get("max_papers_per_week", ""),
                    ",".join(package_ids),
                    ", ".join(labels.get(package_id, package_id) for package_id in package_ids),
                    item.get("created_at", ""),
                    item.get("updated_at", ""),
                ]
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-url", default=DEFAULT_REGISTRY_URL)
    parser.add_argument("--admin-token", default="")

    subparsers = parser.add_subparsers(dest="command", required=False)

    list_parser = subparsers.add_parser("list", help="List student subscriptions.")
    list_parser.add_argument("--include-inactive", action="store_true")

    stats_parser = subparsers.add_parser("stats", help="Show student subscription summary.")
    stats_parser.add_argument("--include-inactive", action="store_true")

    export_parser = subparsers.add_parser("export-csv", help="Export subscriptions to CSV.")
    export_parser.add_argument("output")
    export_parser.add_argument("--include-inactive", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "list"
    token = resolve_admin_token(args.admin_token)
    if not token:
        print("Error: admin token is required.")
        return 1

    try:
        subscriptions = fetch_subscriptions(
            args.registry_url,
            admin_token=token,
            include_inactive=getattr(args, "include_inactive", False),
        )
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    if command == "list":
        print(render_subscription_rows(subscriptions))
        return 0

    if command == "stats":
        active_count = sum(1 for item in subscriptions if item.get("active", True))
        print(f"Subscriptions: {active_count} active / {len(subscriptions)} total")
        counts = compute_package_counts(subscriptions)
        labels = package_labels()
        for package_id, count in counts.most_common():
            print(f"- {labels.get(package_id, package_id)}: {count}")
        return 0

    if command == "export-csv":
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(output_path, subscriptions)
        print(f"Wrote {len(subscriptions)} subscriptions to {output_path}")
        return 0

    print(f"Error: unknown command {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
