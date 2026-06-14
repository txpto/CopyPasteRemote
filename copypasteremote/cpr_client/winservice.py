"""Run the CopyPasteRemote client as an auto-starting Windows Service.

IMPORTANT — why this is a *launcher* service
--------------------------------------------
A normal Windows Service runs in **Session 0**, which has no interactive desktop.
The client needs the user's clipboard, global keyboard hooks and a tray icon, none
of which work from Session 0. So this service runs as **LocalSystem** and merely
*launches* the real client GUI **inside the active user session** (via
``CreateProcessAsUser``), relaunching it when a user logs in. It keeps the client
running unattended and auto-started, as requested, while the GUI still lives where
it can actually reach the clipboard.

> Simpler alternative: a per-user logon Scheduled Task
> (``scripts/client/install_task.ps1``). Use that if you don't need a service.

Install / manage (elevated, in the project root)::

    set CPR_CLIENT_CMD="C:\CopyPasteRemote\CopyPasteRemote.exe"
    python -m cpr_client.winservice --startup auto install
    python -m cpr_client.winservice start / stop / remove

The command to launch is read from ``%CPR_CLIENT_CMD%`` (full command line) with an
optional working directory in ``%CPR_CLIENT_CWD%``. The PowerShell installer in
``scripts/client/install_service_windows.ps1`` sets these for you.

Requires ``pip install pywin32``.
"""

from __future__ import annotations

import os
import sys
import time

try:
    import servicemanager
    import win32con
    import win32event
    import win32process
    import win32profile
    import win32security
    import win32service
    import win32serviceutil
    import win32ts

    _HAVE_PYWIN32 = True
except Exception:  # pragma: no cover - not on Windows / no pywin32
    _HAVE_PYWIN32 = False

_INVALID_SESSION = 0xFFFFFFFF
_STILL_ACTIVE = 259


def _default_command() -> str:
    """Best-effort default launch command if CPR_CLIENT_CMD is unset."""
    cmd = os.environ.get("CPR_CLIENT_CMD")
    if cmd:
        return cmd
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, os.path.join(repo, "run_client.py"))


if _HAVE_PYWIN32:

    class CprClientLauncherService(win32serviceutil.ServiceFramework):
        _svc_name_ = "CopyPasteRemoteClient"
        _svc_display_name_ = "CopyPasteRemote Client (session launcher)"
        _svc_description_ = (
            "Auto-starts the CopyPasteRemote client GUI inside the interactive "
            "user session (it needs the clipboard, hotkeys and tray)."
        )

        def __init__(self, args):
            super().__init__(args)
            self._stop_evt = win32event.CreateEvent(None, 0, 0, None)
            self._running = True
            self._proc_handle = None
            self._proc_session = _INVALID_SESSION

        # Accept logon/logoff notifications so we react promptly.
        def GetAcceptedControls(self):
            rc = super().GetAcceptedControls()
            rc |= win32service.SERVICE_ACCEPT_SESSIONCHANGE
            return rc

        def SvcOtherEx(self, control, event_type, data):
            if control == win32service.SERVICE_CONTROL_SESSIONCHANGE:
                # Wake the poll loop immediately to (re)launch in the active session.
                # The loop keeps running because self._running is still True; the
                # auto-reset event just shortcuts the 5s wait.
                win32event.SetEvent(self._stop_evt)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._running = False
            self._terminate_child()
            win32event.SetEvent(self._stop_evt)

        def SvcDoRun(self):
            servicemanager.LogInfoMsg("CopyPasteRemoteClient launcher: starting")
            command = _default_command()
            cwd = os.environ.get("CPR_CLIENT_CWD") or None
            while self._running:
                try:
                    self._ensure_running(command, cwd)
                except Exception as exc:  # noqa: BLE001
                    servicemanager.LogErrorMsg("Launcher error: %s" % exc)
                # Poll every 5s (also wakes on stop).
                win32event.WaitForSingleObject(self._stop_evt, 5000)
            servicemanager.LogInfoMsg("CopyPasteRemoteClient launcher: stopped")

        # -- internals ------------------------------------------------------
        def _child_alive(self) -> bool:
            if self._proc_handle is None:
                return False
            try:
                code = win32process.GetExitCodeProcess(self._proc_handle)
                return code == _STILL_ACTIVE
            except Exception:
                return False

        def _terminate_child(self):
            if self._proc_handle is not None:
                try:
                    win32process.TerminateProcess(self._proc_handle, 0)
                except Exception:
                    pass
                self._proc_handle = None

        def _ensure_running(self, command: str, cwd):
            session = win32ts.WTSGetActiveConsoleSessionId()
            if session == _INVALID_SESSION:
                # No one logged in at the console; nothing to do yet.
                return
            # Relaunch if the child died or the active session changed (re-logon).
            if self._child_alive() and session == self._proc_session:
                return
            self._terminate_child()
            self._launch_in_session(session, command, cwd)

        def _launch_in_session(self, session_id: int, command: str, cwd):
            user_token = win32ts.WTSQueryUserToken(session_id)
            try:
                primary = win32security.DuplicateTokenEx(
                    user_token,
                    win32security.SecurityImpersonation,
                    win32con.MAXIMUM_ALLOWED,
                    win32security.TokenPrimary,
                    None,
                )
                env = win32profile.CreateEnvironmentBlock(primary, False)
                startup = win32process.STARTUPINFO()
                startup.lpDesktop = "winsta0\\default"
                flags = win32con.CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_NEW_CONSOLE
                hProcess, hThread, pid, tid = win32process.CreateProcessAsUser(
                    primary, None, command, None, None, False, flags, env, cwd, startup
                )
                try:
                    win32api_close(hThread)
                except Exception:
                    pass
                self._proc_handle = hProcess
                self._proc_session = session_id
                servicemanager.LogInfoMsg(
                    "Launched client in session %d (pid %d): %s" % (session_id, pid, command)
                )
            finally:
                try:
                    win32api_close(user_token)
                except Exception:
                    pass


def win32api_close(handle):
    import win32api

    win32api.CloseHandle(handle)


def main(argv=None):
    if not _HAVE_PYWIN32:
        print("This command requires Windows with pywin32 (pip install pywin32).")
        return 1
    argv = list(argv if argv is not None else sys.argv)
    if len(argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CprClientLauncherService)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    win32serviceutil.HandleCommandLine(CprClientLauncherService, argv=argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
