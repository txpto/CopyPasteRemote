"""Administration CLI for the orchestrator.

Run on the server box (it talks directly to the SQLite store and config, not over
the network).  Typical first-time setup::

    python -m cpr_server.admin_cli init --public-url https://1.2.3.4:8765
    python -m cpr_server.admin_cli add-machine --slot 1 --name "PC-Casa" \\
        --client-config clients/pc-casa.json
    python -m cpr_server.admin_cli add-machine --slot 2 --name "PC-Oficina" \\
        --client-config clients/pc-oficina.json
    python -m cpr_server.admin_cli list

The ``add-machine`` command can emit a ready-to-use client config file containing
the server URL, the machine's credentials and the shared pool key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from cpr_shared import crypto

from .auth import make_bearer
from .config import ServerConfig
from .storage import Storage, StorageError


def _store(config: ServerConfig) -> Storage:
    config.ensure_dirs()
    return Storage(config.db_path, config.blobs_dir)


def _save_config_file(path: str, config: ServerConfig) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config.to_dict(), fh, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init(args, config: ServerConfig) -> int:
    """Create/refresh a server config file and a fresh pool key."""
    out = args.config or "server-config.json"
    if os.path.exists(out) and not args.force:
        print("Refusing to overwrite existing %s (use --force)" % out, file=sys.stderr)
        return 2

    if args.public_url:
        config.public_url = args.public_url
    if args.pool_id:
        config.pool_id = args.pool_id

    if args.pool_passphrase:
        key = crypto.key_from_passphrase(args.pool_passphrase, config.pool_id)
    else:
        key = crypto.generate_key()
    config.pool_key_b64 = crypto.key_to_b64(key)

    if not config.admin_api_key:
        import secrets

        config.admin_api_key = secrets.token_urlsafe(32)

    _save_config_file(out, config)
    # Initialise the database and record the key fingerprint.
    store = _store(config)
    store.set_meta("pool_key_fp", crypto.key_fingerprint(key))
    store.set_meta("admin_api_key", config.admin_api_key)
    store.close()

    print("Wrote %s" % out)
    print("  pool_id          : %s" % config.pool_id)
    print("  pool key fp      : %s" % crypto.key_fingerprint(key))
    print("  admin_api_key    : %s" % config.admin_api_key)
    print("  public_url       : %s" % config.public_url)
    print()
    print("Keep this file safe: it contains the pool key and admin key.")
    print("Next: register machines with 'add-machine'.")
    return 0


def cmd_add_machine(args, config: ServerConfig) -> int:
    store = _store(config)
    try:
        token = store.add_machine(
            args.slot, args.name, token=args.token, pool=args.pool or "default"
        )
    except StorageError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        store.close()
        return 2

    bearer = make_bearer(args.slot, token)
    print("Registered machine:")
    print("  slot   : %d" % args.slot)
    print("  name   : %s" % args.name)
    print("  pool   : %s" % (args.pool or "default"))
    print("  token  : %s" % token)
    print("  bearer : %s" % bearer)

    if args.client_config:
        if not config.pool_key_b64:
            print(
                "\nWARNING: server config has no pool_key_b64; the generated client "
                "config will omit the pool key. Add 'pool_key' to it manually.",
                file=sys.stderr,
            )
        client_cfg = {
            "server_url": config.public_url,
            "machine_id": args.slot,
            "machine_name": args.name,
            "token": token,
            "pool_id": config.pool_id,
            "pool_key": config.pool_key_b64,
            "verify_tls": True,
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.client_config)), exist_ok=True)
        with open(args.client_config, "w", encoding="utf-8") as fh:
            json.dump(client_cfg, fh, indent=2)
        try:
            os.chmod(args.client_config, 0o600)
        except OSError:
            pass
        print("\nWrote client config -> %s" % args.client_config)
        print("Copy that file to the Windows machine as %%APPDATA%%\\CopyPasteRemote\\config.json")
    store.close()
    return 0


def cmd_list(args, config: ServerConfig) -> int:
    store = _store(config)
    machines = store.list_machines()
    store.close()
    if not machines:
        print("No machines registered yet.")
        return 0
    print("%-5s %-20s %-12s %-8s %-12s %s"
          % ("SLOT", "NAME", "POOL", "ENABLED", "LAST_SEEN", "CREATED"))
    import datetime

    for m in machines:
        last = (
            datetime.datetime.fromtimestamp(m["last_seen"]).strftime("%Y-%m-%d %H:%M")
            if m["last_seen"]
            else "never"
        )
        created = datetime.datetime.fromtimestamp(m["created_at"]).strftime("%Y-%m-%d")
        print(
            "%-5d %-20s %-12s %-8s %-12s %s"
            % (m["id"], m["name"][:20], (m.get("pool") or "default")[:12],
               "yes" if m["enabled"] else "no", last, created)
        )
    return 0


def cmd_set_pool(args, config: ServerConfig) -> int:
    store = _store(config)
    try:
        store.set_pool(args.slot, args.pool)
    except StorageError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        store.close()
        return 2
    store.close()
    print("Slot %d moved to pool '%s'" % (args.slot, args.pool))
    return 0


def cmd_set_acl(args, config: ServerConfig) -> int:
    def parse(spec):
        if spec is None:
            return None  # leave unchanged
        spec = spec.strip()
        if spec in ("", "open", "all"):
            return []  # clear/open
        return [int(x) for x in spec.replace(",", " ").split()]

    store = _store(config)
    try:
        store.set_acl(args.slot, parse(args.push), parse(args.pull))
    except StorageError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        store.close()
        return 2
    store.close()
    print("ACL updated for slot %d (push=%s pull=%s)" % (args.slot, args.push, args.pull))
    return 0


def cmd_rotate(args, config: ServerConfig) -> int:
    store = _store(config)
    try:
        token = store.rotate_token(args.slot)
    except StorageError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        store.close()
        return 2
    store.close()
    print("New token for slot %d: %s" % (args.slot, token))
    print("New bearer: %s" % make_bearer(args.slot, token))
    return 0


def cmd_enable(args, config: ServerConfig) -> int:
    store = _store(config)
    try:
        store.set_enabled(args.slot, not args.disable)
    except StorageError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        store.close()
        return 2
    store.close()
    print("Slot %d %s" % (args.slot, "disabled" if args.disable else "enabled"))
    return 0


def cmd_remove(args, config: ServerConfig) -> int:
    store = _store(config)
    store.delete_machine(args.slot)
    store.close()
    print("Removed slot %d" % args.slot)
    return 0


def cmd_show_admin_key(args, config: ServerConfig) -> int:
    store = _store(config)
    key = config.admin_api_key or store.get_meta("admin_api_key")
    store.close()
    print(key or "(none configured)")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cpr-admin", description="CopyPasteRemote admin CLI")
    p.add_argument("--config", help="Server config file (default: $CPR_SERVER_CONFIG or built-ins)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="Create a server config + fresh pool key")
    s.add_argument("--public-url", help="Public URL clients use, e.g. https://1.2.3.4:8765")
    s.add_argument("--pool-id", help="Pool identifier (default: default)")
    s.add_argument("--pool-passphrase", help="Derive the pool key from a passphrase instead of random")
    s.add_argument("--force", action="store_true", help="Overwrite an existing config file")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add-machine", help="Register a machine in the pool")
    s.add_argument("--slot", type=int, required=True, help="Slot/mailbox number (1..255)")
    s.add_argument("--name", required=True, help="Human friendly name")
    s.add_argument("--pool", default="default", help="Pool name (machines only see their pool)")
    s.add_argument("--token", help="Use a specific token (default: generate one)")
    s.add_argument("--client-config", help="Write a ready-to-use client config JSON here")
    s.set_defaults(func=cmd_add_machine)

    s = sub.add_parser("list", help="List registered machines")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("set-pool", help="Move a machine to a different pool")
    s.add_argument("--slot", type=int, required=True)
    s.add_argument("--pool", required=True)
    s.set_defaults(func=cmd_set_pool)

    s = sub.add_parser("set-acl", help="Set per-mailbox ACLs (who may push/pull this mailbox)")
    s.add_argument("--slot", type=int, required=True)
    s.add_argument("--push", help="Slots allowed to push here: 'open' or e.g. '1,3,5'")
    s.add_argument("--pull", help="Slots allowed to read here: 'open' or e.g. '1,3,5'")
    s.set_defaults(func=cmd_set_acl)

    s = sub.add_parser("rotate", help="Rotate a machine's token")
    s.add_argument("--slot", type=int, required=True)
    s.set_defaults(func=cmd_rotate)

    s = sub.add_parser("enable", help="Enable (or --disable) a machine")
    s.add_argument("--slot", type=int, required=True)
    s.add_argument("--disable", action="store_true")
    s.set_defaults(func=cmd_enable)

    s = sub.add_parser("remove", help="Delete a machine and its mailbox")
    s.add_argument("--slot", type=int, required=True)
    s.set_defaults(func=cmd_remove)

    s = sub.add_parser("show-admin-key", help="Print the admin API key")
    s.set_defaults(func=cmd_show_admin_key)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ServerConfig.load(args.config)
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
