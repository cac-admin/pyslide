# -*- coding: utf-8 -*-
""" Command line interface for ``pyslide-remote``."""

from __future__ import annotations

import argparse
import json
import sys

from . import _auth, _config
from ._errors import RemoteError


__all__ = ["main", "build_parser"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_JOB = 2
EXIT_JOB_FAILED = 3


def build_parser():
    """ Build the ``pyslide-remote`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="pyslide-remote",
        description=(
            "Send a slide to a compatible annotation server, wait for it, and "
            "download the results."
        ),
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="server profile to use (default: the active profile)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON instead of a summary",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide upload, polling, and download progress",
    )

    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser(
        "init", help="configure a server profile, interactively by default"
    )
    init.add_argument(
        "--from",
        dest="from_file",
        default=None,
        metavar="FILE",
        help="import a config file downloaded from a server",
    )
    init.add_argument("--url", default=None, help="server base URL")
    init.add_argument(
        "--name", default=None, help="profile name (default: 'default')"
    )
    init.add_argument(
        "--token", default=None, help="paste an existing API token"
    )
    init.add_argument(
        "--no-verify",
        action="store_true",
        help="do not verify TLS certificates for this profile",
    )
    init.add_argument(
        "--timeout", type=float, default=None, help="request timeout in seconds"
    )
    init.add_argument(
        "--no-login",
        action="store_true",
        help="save the profile without asking for credentials",
    )

    sub.add_parser("profiles", help="list saved profiles")

    use = sub.add_parser("use", help="switch the active profile")
    use.add_argument("name", help="profile to activate")

    login = sub.add_parser("login", help="obtain and store an API token")
    login.add_argument("--username", default=None)
    login.add_argument("--password", default=None)
    login.add_argument(
        "--token", default=None, help="store a pasted token instead"
    )

    sub.add_parser("logout", help="forget the stored token for a profile")

    doctor = sub.add_parser(
        "doctor", help="diagnose configuration, connectivity, and login"
    )
    doctor.add_argument("--url", default=None, help="check this URL instead")

    annotate = sub.add_parser(
        "annotate", help="submit a slide and download its results"
    )
    annotate.add_argument("slide", help="path to the slide file")
    annotate.add_argument(
        "--no-wait",
        action="store_true",
        help="return once the job is submitted instead of waiting",
    )
    annotate.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="seconds between status checks (default: 5)",
    )
    annotate.add_argument(
        "--results-dir",
        default=None,
        help="parent directory for downloads "
        "(default: ./pyslide_remote_results/<job_id>/)",
    )
    annotate.add_argument(
        "--timeout", type=float, default=None, help="request timeout in seconds"
    )

    status = sub.add_parser(
        "status", help="check a slide's job without uploading"
    )
    status.add_argument("slide", help="path to the slide file")
    status.add_argument(
        "--timeout", type=float, default=None, help="request timeout in seconds"
    )

    return parser


def _print_result(result, *, as_json=False):
    """ Print an annotate or status result."""
    if as_json:
        print(json.dumps(result, indent=2, default=str, sort_keys=True))
        return

    if result.get("message"):
        print(result["message"])
    print(f"job:       {result.get('job_id')}")
    print(f"status:    {result.get('status')}")
    print(f"submitted: {result.get('submitted')}")
    if result.get("results_dir"):
        print(f"results:   {result['results_dir']}")
    for path in result.get("paths") or []:
        print(f"  {path}")


def _result_exit_code(result, *, command):
    """ Map a result onto a process exit code."""
    if result.get("status") == "failed":
        return EXIT_JOB_FAILED
    if command == "status" and result.get("job_id") is None:
        return EXIT_NO_JOB
    return EXIT_OK


def _cmd_init(args):
    """ Create or update a profile, then optionally log in."""
    token = args.token
    name = args.name
    settings = {}

    if args.from_file:
        imported = _config.read_connect_file(args.from_file)
        name = name or imported["name"]
        settings.update(imported["settings"])
        token = token or imported["token"]
        print(f"Imported {settings['base_url']} from {args.from_file}")
    else:
        url = args.url
        if not url:
            url = input("Server base URL: ").strip()
        if not url:
            print("A server URL is required.", file=sys.stderr)
            return EXIT_ERROR
        settings["base_url"] = _config.normalize_base_url(url)

    name = name or _config.DEFAULT_PROFILE
    if args.no_verify:
        settings["verify"] = False
    if args.timeout is not None:
        settings["timeout"] = args.timeout

    saved = _config.save_profile(name, settings)
    print(f"Saved profile {name!r} -> {saved['base_url']}")

    # Confirm the URL is a compatible server before any upload.
    from ._client import RemoteClient

    client = RemoteClient(profile=name)
    try:
        capabilities = client.capabilities()
        client.check_protocol(capabilities)
    except RemoteError as exc:
        print(f"Warning: could not verify the server: {exc}", file=sys.stderr)
        print("Run 'pyslide-remote doctor' after fixing it.", file=sys.stderr)
    else:
        print(f"Server protocol: {capabilities.get('protocol')}")

    if token:
        _auth.save_token(token, profile=name)
        print("Stored the supplied token.")
    elif not args.no_login:
        try:
            _auth.ensure_token(client, profile=name, force_login=True)
        except (RemoteError, EOFError, KeyboardInterrupt) as exc:
            print(f"Skipped login: {exc}", file=sys.stderr)
            print(
                "Run 'pyslide-remote login' when you are ready.",
                file=sys.stderr,
            )
            return EXIT_OK
        print("Logged in and stored the token.")

    print(f"Next: pyslide-remote annotate <slide>")
    return EXIT_OK


def _cmd_profiles(args):
    """ List profiles, marking the active one."""
    profiles = _config.list_profiles()
    if args.json:
        print(
            json.dumps(
                {
                    "current": _config.current_profile_name(),
                    "profiles": profiles,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_OK

    if not profiles:
        print("No profiles yet. Run: pyslide-remote init")
        return EXIT_OK

    active = _config.current_profile_name()
    for name in sorted(profiles):
        marker = "*" if name == active else " "
        base_url = profiles[name].get("base_url", "(no URL)")
        has_token = "token" if _auth.load_token(name) else "no token"
        print(f"{marker} {name}  {base_url}  [{has_token}]")
    return EXIT_OK


def _cmd_use(args):
    """ Switch the active profile."""
    _config.use_profile(args.name)
    print(f"Active profile: {args.name}")
    return EXIT_OK


def _cmd_login(args):
    """ Store a token, either pasted or obtained by logging in."""
    profile = _config.resolve_profile_name(args.profile)
    if args.token:
        _auth.save_token(args.token, profile=profile)
        print(f"Stored a token for profile {profile!r}.")
        return EXIT_OK

    from ._client import RemoteClient

    client = RemoteClient(profile=profile)
    _auth.ensure_token(
        client,
        profile=profile,
        force_login=True,
        username=args.username,
        password=args.password,
    )
    print(f"Logged in; token stored for profile {profile!r}.")
    return EXIT_OK


def _cmd_logout(args):
    """ Remove the stored token for a profile."""
    profile = _config.resolve_profile_name(args.profile)
    if _auth.clear_token(profile):
        print(f"Removed the stored token for profile {profile!r}.")
    else:
        print(f"No token was stored for profile {profile!r}.")
    return EXIT_OK


def _cmd_doctor(args):
    """ Run diagnostics and report them."""
    from ._doctor import format_report, run_checks

    checks = run_checks(args.profile, base_url=args.url)
    if args.json:
        print(
            json.dumps(
                [check.as_dict() for check in checks], indent=2, sort_keys=True
            )
        )
    else:
        print(format_report(checks))

    failed = any(check.ok is False for check in checks)
    return EXIT_ERROR if failed else EXIT_OK


def _cmd_annotate(args, *, submit=True):
    """ Run annotate or status and print the result."""
    from ._annotate import annotate

    show_progress = False if (args.json or args.quiet) else None
    result = annotate(
        args.slide,
        profile=args.profile,
        wait=not getattr(args, "no_wait", False) if submit else False,
        poll_interval=getattr(args, "poll_interval", 5.0),
        results_dir=getattr(args, "results_dir", None),
        timeout=args.timeout,
        submit=submit,
        progress=show_progress,
    )
    _print_result(result, as_json=args.json)
    return _result_exit_code(result, command=args.command)


_COMMANDS = {
    "init": _cmd_init,
    "profiles": _cmd_profiles,
    "use": _cmd_use,
    "login": _cmd_login,
    "logout": _cmd_logout,
    "doctor": _cmd_doctor,
    "annotate": _cmd_annotate,
    "status": lambda args: _cmd_annotate(args, submit=False),
}


def main(argv=None):
    """ Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_ERROR

    try:
        return _COMMANDS[args.command](args)
    except RemoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
