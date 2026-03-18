#!/usr/bin/env python3
"""Terminal bootstrap for friends setting up their own arXiv Digest fork."""

from __future__ import annotations

import argparse
import getpass
import json
import re
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import yaml

from setup.data import AU_STUDENT_TRACK_LABELS
from setup.student_presets import build_au_student_config
from student_registry import AVAILABLE_STUDENT_PACKAGES


DEFAULT_SOURCE_REPO = "SilkeDainese/arxiv-digest"
DEFAULT_SETUP_URL = "https://arxiv-digest-production-93ba.up.railway.app"
DOWNLOAD_PATTERNS = (
    "config.yaml",
    "config.yml",
    "config*.yaml",
    "config*.yml",
)
DOWNLOAD_STABLE_AGE_SECONDS = 1.0
AU_STUDENT_TERMINAL_TRACKS = list(AVAILABLE_STUDENT_PACKAGES)


class SetupError(RuntimeError):
    """Raised when a terminal-setup step fails."""


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return its completed process."""
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise SetupError(f"{' '.join(args)}: {detail}")
    return result


def gh_json(args: list[str]) -> dict | list:
    """Run a gh command that returns JSON."""
    result = run_command(["gh", *args])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError(f"Could not parse JSON from {' '.join(args)}") from exc


def prompt(text: str, *, default: str | None = None, required: bool = True) -> str:
    """Prompt for a normal terminal input."""
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{text}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("Please enter a value.")


def prompt_secret(text: str, *, required: bool = True) -> str:
    """Prompt for a secret value without echoing it."""
    while True:
        value = getpass.getpass(f"{text}: ").strip()
        if value or not required:
            return value
        print("Please enter a value.")


def prompt_yes_no(text: str, *, default: bool = True) -> bool:
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    while True:
        value = input(f"{text} [{hint}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def prompt_choice(
    text: str,
    options: list[tuple[str, str, str]],
    *,
    default: str,
) -> str:
    """Prompt the user to choose one labeled option."""
    option_map = {key: (label, detail) for key, label, detail in options}
    if default not in option_map:
        raise ValueError(f"Unknown default choice: {default}")

    print(text)
    for key, label, detail in options:
        default_note = " (default)" if key == default else ""
        print(f"  {key}) {label}{default_note}")
        print(f"     {detail}")

    while True:
        value = input(f"Choose [{default}]: ").strip().lower()
        if not value:
            return default
        if value in option_map:
            return value
        print("Please choose one of: " + ", ".join(key for key, _, _ in options))


def pick_downloaded_config(downloads_dir: Path, started_at: float) -> Path | None:
    """Return the newest freshly-downloaded config file, if any."""
    candidates: list[Path] = []
    for pattern in DOWNLOAD_PATTERNS:
        for path in downloads_dir.glob(pattern):
            if not path.is_file():
                continue
            if path.suffix not in {".yaml", ".yml"}:
                continue
            if path.stat().st_size <= 0:
                continue
            if path.stat().st_mtime < started_at:
                continue
            if path.name.endswith(".crdownload"):
                continue
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def wait_for_downloaded_config(
    downloads_dir: Path,
    *,
    started_at: float,
    timeout_seconds: int,
) -> Path:
    """Wait until a config file appears in Downloads and becomes stable."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        candidate = pick_downloaded_config(downloads_dir, started_at)
        if candidate:
            age = time.time() - candidate.stat().st_mtime
            if age >= DOWNLOAD_STABLE_AGE_SECONDS:
                return candidate
        time.sleep(2)
    raise SetupError(
        f"Timed out waiting for config.yaml in {downloads_dir}. "
        "Pass --config-path if the file is elsewhere."
    )


def rewrite_top_level_scalar(text: str, key: str, value: str) -> str:
    """Replace or append a top-level YAML scalar while preserving the rest."""
    replacement = f"{key}: {json.dumps(value)}"
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return text.rstrip() + f"\n{replacement}\n"


def prepare_config_text(config_path: Path, fork_repo: str) -> str:
    """Load the downloaded config and point github_repo at the new fork."""
    text = config_path.read_text()
    return rewrite_top_level_scalar(text, "github_repo", fork_repo)


def prepare_generated_config_text(config_text: str, fork_repo: str) -> str:
    """Point a generated YAML config at the new fork."""
    return rewrite_top_level_scalar(config_text, "github_repo", fork_repo)


def repo_exists(repo: str) -> bool:
    """Return True if the given repo already exists."""
    result = run_command(
        ["gh", "repo", "view", repo, "--json", "nameWithOwner"],
        check=False,
    )
    return result.returncode == 0


def wait_for_repo(repo: str, timeout_seconds: int = 180) -> None:
    """Poll until GitHub finishes creating the fork."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if repo_exists(repo):
            return
        time.sleep(2)
    raise SetupError(f"Timed out waiting for {repo} to appear on GitHub.")


def ensure_fork(source_repo: str, fork_repo: str) -> None:
    """Create the friend's fork if it doesn't exist yet."""
    if repo_exists(fork_repo):
        print(f"Using existing repo: {fork_repo}")
        return

    source_name = source_repo.split("/", 1)[1]
    fork_name = fork_repo.split("/", 1)[1]
    args = ["gh", "api", "-X", "POST", f"repos/{source_repo}/forks"]
    if fork_name != source_name:
        args.extend(["-f", f"name={fork_name}"])
    run_command(args)
    wait_for_repo(fork_repo)
    print(f"Fork created: {fork_repo}")


def get_default_branch(repo: str) -> str:
    """Return the repo's default branch name."""
    data = gh_json(["repo", "view", repo, "--json", "defaultBranchRef"])
    branch = data.get("defaultBranchRef", {}).get("name", "").strip()
    if not branch:
        raise SetupError(f"Could not determine the default branch for {repo}.")
    return branch


def clone_repo(repo: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Clone the repo into a temporary directory."""
    tmpdir = tempfile.TemporaryDirectory(prefix="arxiv-digest-friend-")
    target = Path(tmpdir.name) / repo.split("/", 1)[1]
    run_command(["gh", "repo", "clone", repo, str(target), "--", "--depth=1"])
    return tmpdir, target


def upload_config(repo: str, config_text: str, *, author_name: str) -> None:
    """Commit config.yaml into the fork."""
    branch = get_default_branch(repo)
    tmpdir, checkout = clone_repo(repo)
    try:
        (checkout / "config.yaml").write_text(config_text)
        run_command(["git", "config", "user.name", author_name], cwd=checkout)
        run_command(
            ["git", "config", "user.email", f"{author_name}@users.noreply.github.com"],
            cwd=checkout,
        )
        run_command(["git", "add", "config.yaml"], cwd=checkout)
        diff = run_command(["git", "diff", "--cached", "--quiet"], cwd=checkout, check=False)
        if diff.returncode == 0:
            print("config.yaml already matches the fork.")
            return
        run_command(["git", "commit", "-m", "Add config.yaml via terminal setup"], cwd=checkout)
        run_command(["git", "push", "origin", f"HEAD:{branch}"], cwd=checkout)
    finally:
        tmpdir.cleanup()


def set_actions_secret(repo: str, name: str, value: str) -> None:
    """Write one GitHub Actions secret."""
    run_command(
        [
            "gh",
            "secret",
            "set",
            name,
            "-R",
            repo,
            "-a",
            "actions",
            "--body",
            value,
        ]
    )


def set_actions_variable(repo: str, name: str, value: str) -> None:
    """Write one GitHub Actions variable."""
    run_command(["gh", "variable", "set", name, "-R", repo, "--body", value])


def configure_actions(repo: str, *, source_repo: str) -> None:
    """Enable Actions and let the workflow write keyword stats back."""
    run_command(
        [
            "gh",
            "api",
            "-X",
            "PUT",
            f"repos/{repo}/actions/permissions",
            "-f",
            "enabled=true",
            "-f",
            "allowed_actions=all",
        ]
    )
    run_command(
        [
            "gh",
            "api",
            "-X",
            "PUT",
            f"repos/{repo}/actions/permissions/workflow",
            "-f",
            "default_workflow_permissions=write",
            "-F",
            "can_approve_pull_request_reviews=false",
        ]
    )
    run_command(["gh", "workflow", "enable", "digest.yml", "-R", repo], check=False)
    run_command(["gh", "workflow", "enable", "sync-upstream.yml", "-R", repo], check=False)
    set_actions_variable(repo, "UPSTREAM_REPO", source_repo)


def collect_optional_ai_secrets() -> dict[str, str]:
    """Prompt for optional AI-provider secrets."""
    secrets: dict[str, str] = {}
    gemini = prompt_secret("GEMINI_API_KEY (optional)", required=False)
    if gemini:
        secrets["GEMINI_API_KEY"] = gemini
    anthropic = prompt_secret("ANTHROPIC_API_KEY (optional)", required=False)
    if anthropic:
        secrets["ANTHROPIC_API_KEY"] = anthropic
    return secrets


def collect_secret_values(
    *, recipient_email: str = "", recipient_in_config: bool = False
) -> tuple[dict[str, str], str]:
    """Prompt for the secrets to install in the new fork."""
    mode = prompt_choice(
        "\nChoose how this fork should deliver email:",
        [
            (
                "1",
                "Invite token / relay",
                "Use a DIGEST_RELAY_TOKEN from the setup wizard or a maintainer invite.",
            ),
            (
                "2",
                "Your own Gmail / SMTP",
                "Use SMTP_USER and SMTP_PASSWORD so mail sends from your own mailbox.",
            ),
            (
                "3",
                "Prepare repo only",
                "Upload config and enable Actions now, but skip all secrets for the moment.",
            ),
        ],
        default="1",
    )

    if mode == "3":
        return {}, mode

    secrets: dict[str, str] = {}
    if recipient_in_config:
        recipient = prompt(
            "RECIPIENT_EMAIL (optional; leave blank to use config.yaml)",
            required=False,
        )
        if recipient:
            secrets["RECIPIENT_EMAIL"] = recipient
    else:
        secrets["RECIPIENT_EMAIL"] = prompt("Recipient email", default=recipient_email or None)

    if mode == "1":
        secrets["DIGEST_RELAY_TOKEN"] = prompt_secret("DIGEST_RELAY_TOKEN")
    else:
        secrets["SMTP_USER"] = prompt("SMTP_USER")
        secrets["SMTP_PASSWORD"] = prompt_secret("SMTP_PASSWORD")

    secrets.update(collect_optional_ai_secrets())

    return secrets, mode


def collect_au_student_track_ids() -> list[str]:
    """Prompt for AU student package interests."""
    while True:
        selected: list[str] = []
        print("\nChoose the astronomy packages this student wants:")
        for track_id in AU_STUDENT_TERMINAL_TRACKS:
            label = AU_STUDENT_TRACK_LABELS[track_id]
            if prompt_yes_no(f"Interested in {label}?", default=True):
                selected.append(track_id)
        if selected:
            return selected
        print("Pick at least one package.")


def build_au_student_terminal_config() -> tuple[str, str]:
    """Build an AU student config directly in the terminal."""
    student_name = prompt("Student name", required=False)
    student_email = prompt("Student email")
    track_ids = collect_au_student_track_ids()
    reading_mode = prompt_choice(
        "\nChoose the weekly reading style:",
        [
            (
                "1",
                "Simple + important",
                "Readable weekly highlights with a slightly wider net.",
            ),
            (
                "2",
                "Only the biggest papers",
                "A stricter shortlist of the most important papers each week.",
            ),
        ],
        default="1",
    )
    config = build_au_student_config(
        student_name=student_name,
        student_email=student_email,
        track_ids=track_ids,
        reading_mode="simple_and_important" if reading_mode == "1" else "biggest_only",
    )
    return (
        yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True),
        student_email,
    )


def verify_gh_ready() -> None:
    """Ensure gh is installed and authenticated before starting."""
    try:
        run_command(["gh", "auth", "status"])
    except FileNotFoundError as exc:
        raise SetupError("GitHub CLI (`gh`) is required but not installed.") from exc


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", default=DEFAULT_SOURCE_REPO)
    parser.add_argument("--setup-url", default=DEFAULT_SETUP_URL)
    parser.add_argument("--downloads-dir", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--config-path", type=Path)
    parser.add_argument("--fork-name")
    parser.add_argument("--repo", help="Use an existing OWNER/REPO instead of creating a fork.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--au-student", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-run", action="store_true")
    return parser


def main() -> int:
    """Run the end-to-end terminal setup flow."""
    args = build_parser().parse_args()
    verify_gh_ready()

    user = gh_json(["api", "user"])
    login = str(user["login"]).strip()
    target_repo = args.repo or f"{login}/{args.fork_name or args.source_repo.split('/', 1)[1]}"

    ensure_fork(args.source_repo, target_repo)

    config_path = args.config_path
    config_text: str
    recipient_email = ""
    recipient_in_config = False

    if config_path is not None:
        if not config_path.exists():
            raise SetupError(f"Config file not found: {config_path}")
        config_text = prepare_config_text(config_path, target_repo)
    else:
        config_source = "2" if args.au_student else prompt_choice(
            "\nChoose how to build the digest config:",
            [
                (
                    "1",
                    "Setup wizard in browser",
                    "Open Streamlit, download config.yaml, then let this script finish the repo setup.",
                ),
                (
                    "2",
                    "AU student packages in terminal",
                    "Answer yes/no for the astronomy packages and generate the AU student config here.",
                ),
            ],
            default="1",
        )
        if config_source == "2":
            generated_config, recipient_email = build_au_student_terminal_config()
            recipient_in_config = True
            config_text = prepare_generated_config_text(generated_config, target_repo)
        else:
            if not args.no_browser:
                print(f"Opening the setup wizard: {args.setup_url}")
                webbrowser.open(args.setup_url)
            print(f"Waiting for config.yaml in {args.downloads_dir} ...")
            started_at = time.time()
            config_path = wait_for_downloaded_config(
                args.downloads_dir,
                started_at=started_at,
                timeout_seconds=args.timeout,
            )
            print(f"Found config file: {config_path}")
            config_text = prepare_config_text(config_path, target_repo)

    upload_config(target_repo, config_text, author_name=login)
    print(f"Uploaded config.yaml to {target_repo}")

    print("\nNow choose what to set up for this fork.")
    secrets, secret_mode = collect_secret_values(
        recipient_email=recipient_email,
        recipient_in_config=recipient_in_config,
    )
    for name, value in secrets.items():
        set_actions_secret(target_repo, name, value)
        print(f"Set secret: {name}")

    configure_actions(target_repo, source_repo=args.source_repo)
    print("Enabled Actions and workflow write permissions.")

    if secret_mode == "3":
        print(
            "Repo setup is complete. Add a delivery method later with either "
            "DIGEST_RELAY_TOKEN or SMTP_USER and SMTP_PASSWORD."
        )
        print(f"Then open https://github.com/{target_repo}/actions to run it.")
    elif not args.no_run and prompt_yes_no("Run the first digest now?", default=True):
        run_command(["gh", "workflow", "run", "digest.yml", "-R", target_repo])
        print(f"Triggered the digest workflow: https://github.com/{target_repo}/actions")
    else:
        print(f"Setup complete. Open https://github.com/{target_repo}/actions to run it.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        raise SystemExit(1)
