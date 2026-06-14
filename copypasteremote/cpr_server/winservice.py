"""Run the CopyPasteRemote orchestrator as an auto-starting Windows Service.

A network daemon like the orchestrator is a perfect fit for a Windows Service
(it needs no interactive desktop), so this wraps uvicorn in a
``win32serviceutil.ServiceFramework``.

Install / manage (from an elevated prompt, in the project root)::

    python -m cpr_server.winservice --startup auto install
    python -m cpr_server.winservice start
    python -m cpr_server.winservice stop
    python -m cpr_server.winservice remove

The service reads its configuration from ``%CPR_SERVER_CONFIG%`` (set it as a
machine-level environment variable, e.g. with the PowerShell installer in
``scripts/server/install_service_windows.ps1``) or falls back to
``server-config.json`` next to this project.

Requires ``pip install pywin32`` on the server host.
"""

from __future__ import annotations

import os
import sys
import threading

# Repo root (this file is cpr_server/winservice.py).
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    _HAVE_PYWIN32 = True
except Exception:  # pragma: no cover - not on Windows / no pywin32
    _HAVE_PYWIN32 = False


if _HAVE_PYWIN32:

    class CprServerService(win32serviceutil.ServiceFramework):
        _svc_name_ = "CopyPasteRemoteServer"
        _svc_display_name_ = "CopyPasteRemote Orchestrator"
        _svc_description_ = (
            "CopyPasteRemote shared-clipboard orchestrator (REST + WebSocket API)."
        )

        def __init__(self, args):
            super().__init__(args)
            self._stop_evt = win32event.CreateEvent(None, 0, 0, None)
            self._server = None
            self._thread = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self._server is not None:
                self._server.should_exit = True
            win32event.SetEvent(self._stop_evt)

        def SvcDoRun(self):
            servicemanager.LogInfoMsg("CopyPasteRemoteServer: starting")
            try:
                self._run()
            except Exception as exc:  # noqa: BLE001
                servicemanager.LogErrorMsg("CopyPasteRemoteServer error: %s" % exc)
                raise

        def _run(self):
            # Make relative paths (e.g. ./data) resolve against the project root.
            os.chdir(_REPO)
            if _REPO not in sys.path:
                sys.path.insert(0, _REPO)

            import uvicorn

            from cpr_server.config import ServerConfig
            from cpr_server.main import create_app

            config_path = os.environ.get("CPR_SERVER_CONFIG") or os.path.join(
                _REPO, "server-config.json"
            )
            cfg = ServerConfig.load(config_path if os.path.isfile(config_path) else None)
            app = create_app(cfg)

            ssl_kwargs = {}
            if cfg.tls_certfile and cfg.tls_keyfile:
                ssl_kwargs = {
                    "ssl_certfile": cfg.tls_certfile,
                    "ssl_keyfile": cfg.tls_keyfile,
                }

            uvconfig = uvicorn.Config(
                app, host=cfg.host, port=cfg.port, log_level=cfg.log_level, **ssl_kwargs
            )
            self._server = uvicorn.Server(uvconfig)

            # uvicorn skips signal handlers off the main thread, so run it in one.
            self._thread = threading.Thread(target=self._server.run, name="cpr-uvicorn")
            self._thread.start()
            servicemanager.LogInfoMsg(
                "CopyPasteRemoteServer: listening on %s:%d" % (cfg.host, cfg.port)
            )
            win32event.WaitForSingleObject(self._stop_evt, win32event.INFINITE)
            if self._thread:
                self._thread.join(timeout=10)
            servicemanager.LogInfoMsg("CopyPasteRemoteServer: stopped")


def main(argv=None):
    if not _HAVE_PYWIN32:
        print("This command requires Windows with pywin32 (pip install pywin32).")
        return 1
    argv = list(argv if argv is not None else sys.argv)
    if len(argv) == 1:
        # Allow the Service Control Manager to start us.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CprServerService)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    win32serviceutil.HandleCommandLine(CprServerService, argv=argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
