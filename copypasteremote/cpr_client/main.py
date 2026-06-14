"""Client entry point: wire config + clipboard + agent + hotkeys + tray.

Modes:
  (default)   run the tray app with global hotkeys
  --no-tray   run headless (hotkeys only) until Ctrl+C
  --check     test the connection, print server info and the pool, then exit
  --setup     write a starter config file and open it
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

from cpr_shared.version import __version__

from .config import ClientConfig, default_config_path


def _setup_logging(cfg: ClientConfig) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if cfg.log_file:
        try:
            os.makedirs(os.path.dirname(cfg.log_file), exist_ok=True)
            handlers.append(logging.FileHandler(cfg.log_file, encoding="utf-8"))
        except OSError:
            pass
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def _make_clipboard():
    """Select the clipboard backend for the current OS."""
    if os.name == "nt":
        from .clipboard_win import WindowsClipboard

        return WindowsClipboard()
    import platform

    if platform.system() in ("Linux", "Darwin"):
        from .clipboard_posix import ClipboardUnavailable, PosixClipboard

        try:
            return PosixClipboard()
        except ClipboardUnavailable as exc:
            raise SystemExit(
                "Clipboard backend unavailable: %s\n"
                "On Linux install wl-clipboard (Wayland) or xclip/xsel (X11)." % exc
            )
    raise SystemExit("Unsupported platform for the CopyPasteRemote client.")


def cmd_setup(args) -> int:
    path = args.config or default_config_path()
    if os.path.exists(path) and not args.force:
        print("Config already exists at %s (use --force to overwrite)" % path)
    else:
        cfg = ClientConfig()
        cfg.save(path)
        print("Wrote a starter config to %s" % path)
    print("Edit it to set server_url, machine_id, token and pool_key, then run the client.")
    try:
        if os.name == "nt":
            os.startfile(os.path.dirname(path))  # type: ignore[attr-defined]
    except Exception:
        pass
    return 0


def cmd_check(args) -> int:
    cfg = ClientConfig.load(args.config)
    print("Config: %s" % cfg.config_path)
    try:
        cfg.validate()
    except ValueError as exc:
        print("Config problem: %s" % exc)
        return 2
    from .transport import RestClient

    rest = RestClient(cfg.server_url, int(cfg.machine_id), cfg.token, cfg.verify_tls, cfg.ca_cert)
    try:
        info = rest.info()
        pool = rest.get_pool()  # authenticated; also carries pool_key_fp now
        print("Server OK: %s v%s (protocol %s, crypto %s)"
              % (info.get("app"), info.get("version"), info.get("protocol"),
                 pool.get("crypto_backend")))
        from cpr_shared import crypto

        local_fp = crypto.key_fingerprint(crypto.key_from_b64(cfg.pool_key))
        srv_fp = pool.get("pool_key_fp")
        match = "OK" if (srv_fp and srv_fp == local_fp) else "MISMATCH/unknown"
        print("Pool key fingerprint: local=%s server=%s [%s]" % (local_fp, srv_fp, match))
        print("You are slot %d. Pool:" % pool.get("you", -1))
        for m in pool.get("machines", []):
            print("  - slot %d  %-20s %s%s"
                  % (m["slot"], m["name"],
                     "online" if m["online"] else "offline",
                     "  [clip waiting]" if m.get("has_clip") else ""))
        return 0
    except Exception as exc:  # noqa: BLE001
        print("Connection failed: %s" % exc)
        return 1


def run_app(args) -> int:
    cfg = ClientConfig.load(args.config)
    _setup_logging(cfg)
    log = logging.getLogger("cpr.client")
    try:
        cfg.validate()
    except ValueError as exc:
        print("Invalid config (%s): %s" % (cfg.config_path, exc))
        # Offer the graphical wizard if a display is available.
        from .wizard import gui_available, run_wizard

        if gui_available():
            print("Opening the setup wizard...")
            if run_wizard(cfg.config_path):
                cfg = ClientConfig.load(args.config)
            else:
                return 2
        else:
            print("Run 'cpr-client --wizard' (GUI) or '--setup', or edit the file.")
            return 2
        try:
            cfg.validate()
        except ValueError as exc2:
            print("Still invalid: %s" % exc2)
            return 2

    from .agent import Agent
    from .hotkeys import HotkeyManager

    clipboard = _make_clipboard()

    use_tray = not args.no_tray
    if use_tray:
        from .tray import CprTray, TrayEvents

        tray = CprTray(cfg)
        events = TrayEvents(tray)
    else:
        tray = None
        events = _ConsoleEvents()

    agent = Agent(cfg, clipboard, events=events)
    try:
        info = agent.check_server()
        log.info("Connected to %s v%s", info.get("app"), info.get("version"))
    except Exception as exc:  # noqa: BLE001
        log.error("Could not reach server: %s", exc)
        # Keep running; the WS layer will keep retrying.

    agent.connect_ws()
    hotkeys = HotkeyManager(
        cfg,
        on_push=agent.push,
        on_pull=agent.pull,
        on_pull_own=agent.pull_own,
        on_error=events.on_error,
    )
    hotkeys.start()
    _print_hotkey_help(cfg)

    if use_tray:
        tray.attach(agent, hotkeys)
        try:
            tray.run()  # blocks until Quit
        finally:
            hotkeys.stop()
            agent.close()
        return 0

    # Headless mode.
    stop = threading.Event()
    try:
        while not stop.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        hotkeys.stop()
        agent.close()
    return 0


def _print_hotkey_help(cfg: ClientConfig) -> None:
    log = logging.getLogger("cpr.client")
    pushes = ", ".join("%s->slot %s" % (v, k) for k, v in sorted(cfg.push_hotkeys.items()))
    pulls = ", ".join("%s->slot %s" % (v, k) for k, v in sorted(cfg.pull_hotkeys.items()))
    log.info("Push hotkeys: %s", pushes)
    log.info("Pull hotkeys: %s", pulls)
    log.info("Paste my mailbox: %s", cfg.pull_own_hotkey)


class _ConsoleEvents:
    """Minimal event sink for headless mode."""

    def on_hello(self, machines): logging.getLogger("cpr.client").info("Pool: %d machines", len(machines))
    def on_presence(self, slot, online):
        logging.getLogger("cpr.client").info("slot %s %s", slot, "online" if online else "offline")
    def on_connection(self, connected):
        logging.getLogger("cpr.client").info("WebSocket %s", "up" if connected else "down")
    def on_clip_available(self, slot, info):
        logging.getLogger("cpr.client").info("Clip available in slot %s: %s", slot, info.get("summary"))
    def on_pushed(self, slot, env):
        logging.getLogger("cpr.client").info("Pushed %s to slot %d", env.human_summary(), slot)
    def on_pulled(self, slot, env):
        logging.getLogger("cpr.client").info("Pulled %s from slot %d", env.human_summary(), slot)
    def on_progress(self, direction, done, total): ...
    def on_error(self, message): logging.getLogger("cpr.client").error(message)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cpr-client", description="CopyPasteRemote client")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--no-tray", action="store_true", help="Run headless (no system tray)")
    parser.add_argument("--check", action="store_true", help="Test connection and exit")
    parser.add_argument("--setup", action="store_true", help="Write a starter config and exit")
    parser.add_argument("--wizard", action="store_true", help="Open the graphical setup wizard")
    parser.add_argument("--force", action="store_true", help="With --setup, overwrite existing config")
    parser.add_argument("--version", action="version", version="CopyPasteRemote %s" % __version__)
    args = parser.parse_args(argv)

    if args.setup:
        return cmd_setup(args)
    if args.wizard:
        from .wizard import gui_available, run_wizard

        if not gui_available():
            print("No GUI available (Tkinter not found). Use --setup instead.")
            return 2
        return 0 if run_wizard(args.config) else 1
    if args.check:
        return cmd_check(args)
    return run_app(args)


if __name__ == "__main__":
    sys.exit(main())
