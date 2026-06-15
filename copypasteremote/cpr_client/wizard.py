"""Tiny graphical setup wizard (Tkinter, standard library).

Lets a non-technical user fill in the client configuration (server URL, machine
id/name, token, pool key, options) and test the connection, then saves
``config.json``. Invoked with ``run_client.py --wizard`` or offered when the
config is missing/invalid.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import ClientConfig, default_config_path

log = logging.getLogger("cpr.client.wizard")


def gui_available() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except Exception:
        return False


def run_wizard(config_path: Optional[str] = None) -> bool:
    """Open the wizard. Returns True if a config was saved."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    path = config_path or default_config_path()
    cfg = ClientConfig.load(path)

    saved = {"ok": False}

    root = tk.Tk()
    root.title("CopyPasteRemote - Configuración")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid()

    ttk.Label(frm, text="Configuración del cliente CopyPasteRemote",
              font=("Segoe UI", 12, "bold")).grid(column=0, row=0, columnspan=2, pady=(0, 12))

    rows = [
        ("server_url", "URL del servidor", "https://IP_PUBLICA:8765"),
        ("machine_id", "Nº de máquina (slot)", ""),
        ("machine_name", "Nombre de la máquina", ""),
        ("token", "Token", ""),
        ("pool_key", "Clave de pool (base64)", ""),
        ("ca_cert", "Certificado CA (opcional)", ""),
    ]
    vars_ = {}
    r = 1
    for key, label, hint in rows:
        ttk.Label(frm, text=label).grid(column=0, row=r, sticky="w", pady=3)
        v = tk.StringVar(value=str(getattr(cfg, key, "") or ""))
        e = ttk.Entry(frm, textvariable=v, width=46, show="*" if key == "token" else "")
        e.grid(column=1, row=r, sticky="w", pady=3)
        if hint and not v.get():
            v.set("")
        vars_[key] = v
        r += 1

    # Boolean options.
    bool_opts = [
        ("verify_tls", "Verificar TLS", True),
        ("auto_paste", "Pegar automáticamente", True),
        ("copy_before_send", "Copiar (Ctrl+C) antes de enviar", False),
        ("auto_apply_incoming", "Aplicar automáticamente lo entrante (seguir)", False),
    ]
    bvars = {}
    for key, label, default in bool_opts:
        bv = tk.BooleanVar(value=bool(getattr(cfg, key, default)))
        ttk.Checkbutton(frm, text=label, variable=bv).grid(
            column=0, row=r, columnspan=2, sticky="w")
        bvars[key] = bv
        r += 1

    status = ttk.Label(frm, text="", foreground="#555")
    status.grid(column=0, row=r, columnspan=2, sticky="w", pady=(8, 0))
    r += 1

    def collect_into(target: ClientConfig):
        target.server_url = vars_["server_url"].get().strip()
        try:
            target.machine_id = int(vars_["machine_id"].get().strip() or 0)
        except ValueError:
            target.machine_id = 0
        target.machine_name = vars_["machine_name"].get().strip()
        target.token = vars_["token"].get().strip()
        target.pool_key = vars_["pool_key"].get().strip()
        target.ca_cert = vars_["ca_cert"].get().strip()
        for key, bv in bvars.items():
            setattr(target, key, bool(bv.get()))

    def on_test():
        collect_into(cfg)
        try:
            from .transport import RestClient

            rest = RestClient(cfg.server_url, int(cfg.machine_id), cfg.token,
                              cfg.verify_tls, cfg.ca_cert)
            info = rest.info()
            pool = rest.get_pool()
            status.config(text="OK: %s v%s, eres el slot %s"
                          % (info.get("app"), info.get("version"), pool.get("you")),
                          foreground="#177245")
        except Exception as exc:  # noqa: BLE001
            status.config(text="Error: %s" % exc, foreground="#a11")

    def on_save():
        collect_into(cfg)
        try:
            cfg.validate()
        except ValueError as exc:
            messagebox.showerror("Configuración incompleta", str(exc))
            return
        saved_path = cfg.save(path)
        saved["ok"] = True
        messagebox.showinfo("Guardado", "Configuración guardada en:\n%s" % saved_path)
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(column=0, row=r, columnspan=2, pady=(12, 0))
    ttk.Button(btns, text="Probar conexión", command=on_test).grid(column=0, row=0, padx=4)
    ttk.Button(btns, text="Guardar", command=on_save).grid(column=1, row=0, padx=4)
    ttk.Button(btns, text="Cancelar", command=root.destroy).grid(column=2, row=0, padx=4)

    root.mainloop()
    return saved["ok"]
