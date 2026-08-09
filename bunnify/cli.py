"""Bunnify CLI — open shortcuts in the default browser."""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable

import click

from bunnify.client import (
    DEFAULT_BASE_URL,
    ClientError,
    fetch_keys,
    resolve_shortcut,
)
from bunnify.interactive import read_shortcut_query


def open_url(url: str, *, opener: Callable[[str], bool] | None = None) -> None:
    """Open ``url`` in the platform default browser."""
    open_fn = opener or webbrowser.open
    opened = open_fn(url)
    if opened is False:
        raise ClientError(f"Failed to open browser for {url}")


def pick_key_with_fzf(
    keys: list[str],
    *,
    query: str = "",
    fzf_bin: str | None = None,
) -> str | None:
    """Fuzzy-pick a shortcut key via fzf. Returns ``None`` if cancelled."""
    binary = fzf_bin or shutil.which("fzf")
    if not binary:
        raise ClientError(
            "fzf not found on PATH. Install fzf or pass an exact shortcut."
        )
    command = [
        binary,
        "--prompt=bunnify> ",
        "--height=40%",
        "--layout=reverse",
        "--exit-0",
    ]
    if query:
        command.extend(["--query", query, "--select-1"])
    try:
        completed = subprocess.run(
            command,
            input="\n".join(keys) + ("\n" if keys else ""),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClientError("fzf timed out") from exc
    if completed.returncode != 0:
        return None
    selected = completed.stdout.strip()
    return selected or None


def matching_keys(keys: list[str], prefix: str) -> list[str]:
    """Return keys that start with ``prefix`` (case-insensitive)."""
    needle = prefix.lower()
    return [key for key in keys if key.lower().startswith(needle)]


def build_query_from_args(args: tuple[str, ...]) -> str:
    return " ".join(args).strip()


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("shortcut_args", nargs=-1)
@click.option(
    "--base-url",
    default=DEFAULT_BASE_URL,
    show_default=True,
    envvar="BUNNIFY_BASE_URL",
    help="Base URL of the local Bunnify server.",
)
@click.option(
    "--list-keys",
    is_flag=True,
    help="Print shortcut keys (one per line) for fzf / shell completion.",
)
@click.option(
    "--fzf",
    "use_fzf",
    is_flag=True,
    help="Fuzzy-pick a shortcut with fzf, then open it (optional params follow).",
)
@click.option(
    "--print-url",
    is_flag=True,
    help="Print the resolved URL instead of opening a browser.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Resolve and print the URL without opening a browser.",
)
def main(
    shortcut_args: tuple[str, ...],
    base_url: str,
    list_keys: bool,
    use_fzf: bool,
    print_url: bool,
    dry_run: bool,
) -> None:
    """
    Open a Bunnify shortcut in your default browser.

    \b
    Interactive (in-CLI tab completion):
      bunnify

    \b
    Direct:
      bunnify vault
      bunnify pr 12345

    \b
    Fuzzy pick (fzf) for argv / shell completion workflows:
      bunnify --fzf
      bunnify --list-keys | fzf
    """
    try:
        _run(
            shortcut_args=shortcut_args,
            base_url=base_url,
            list_keys=list_keys,
            use_fzf=use_fzf,
            print_url=print_url or dry_run,
            open_browser=not (print_url or dry_run),
        )
    except ClientError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)


def _run(
    *,
    shortcut_args: tuple[str, ...],
    base_url: str,
    list_keys: bool,
    use_fzf: bool,
    print_url: bool,
    open_browser: bool,
    opener: Callable[[str], bool] | None = None,
    input_fn: Callable[[str], str] | None = None,
    fzf_picker: Callable[..., str | None] | None = None,
) -> None:
    if list_keys:
        for key in fetch_keys(base_url=base_url):
            click.echo(key)
        return

    query = build_query_from_args(shortcut_args)
    picker = fzf_picker or pick_key_with_fzf

    if use_fzf:
        keys = fetch_keys(base_url=base_url)
        seed = shortcut_args[0] if shortcut_args else ""
        params = " ".join(shortcut_args[1:]).strip() if len(shortcut_args) > 1 else ""
        selected = picker(keys, query=seed)
        if selected is None:
            raise ClientError("No shortcut selected")
        query = f"{selected} {params}".strip()
    elif not query:
        keys = fetch_keys(base_url=base_url)
        query = read_shortcut_query(keys=keys, input_fn=input_fn)
        if query is None:
            raise ClientError("Cancelled")
    else:
        # Direct mode: ambiguous sole-token prefixes go through fzf.
        parts = query.split(None, 1)
        key_token = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        keys = fetch_keys(base_url=base_url)
        if key_token not in keys:
            matches = matching_keys(keys, key_token)
            if len(matches) > 1:
                selected = picker(matches, query=key_token)
                if selected is None:
                    raise ClientError("No shortcut selected")
                query = f"{selected} {rest}".strip()
            elif len(matches) == 1:
                query = f"{matches[0]} {rest}".strip()

    resolved = resolve_shortcut(query, base_url=base_url, strict=True)
    if print_url:
        click.echo(resolved.url)
    if open_browser:
        open_url(resolved.url, opener=opener)
        click.echo(f"opened {resolved.url}", err=True)


if __name__ == "__main__":
    main()
