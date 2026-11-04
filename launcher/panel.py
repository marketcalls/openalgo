"""The control panel: one small window to run FastAlgo on a Windows desktop.

Opened from the desktop shortcut:

    pythonw app\\launcher\\panel.py --home C:\\FastAlgo

It owns nothing. The keeper runs the server, and the panel only reads
``run\\status.json`` (through ``launcher.control``) and sends commands, so
closing the window never stops trading. See M3.4 in
``docs/plans/2026-11-05-desktop-panel-and-reset-plan.md``.

tkinter, standard library only; see ``launcher/__init__.py``.
"""

import argparse
import contextlib
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher import control, eject, envfile, state
from launcher.branding import display_name
from launcher.keeper import (
    IS_WINDOWS,
    InstanceLock,
    Paths,
    paths_for,
    port_in_use,
    read_settings,
    write_json,
)

#: How often the status is re-read, in milliseconds.
REFRESH_MS = 1000

#: Lines of the server log shown in the window.
LOG_LINES = 200

RUNNING_STATES = {"starting", "running", "restarting", "stopping", "unsupervised"}

STATE_LABELS = {
    "starting": "Starting",
    "running": "Running",
    "restarting": "Restarting",
    "stopping": "Stopping",
    "stopped": "Stopped",
    "crashed": "Stopped after a problem",
    "error": "Could not start",
    "unsupervised": "Running without supervision",
    "setup": "Not set up yet",
}


def controls_for(status: dict) -> dict[str, bool]:
    """Which buttons are usable in ``status``. Pure, so it is tested without a window."""
    current = status.get("state", "stopped")
    if current == "setup":
        # No .env: the app cannot start until a broker is chosen.
        return dict.fromkeys(
            ("start", "stop", "restart", "open", "settings", "maintenance"), False
        ) | {"setup": True}
    running = current in RUNNING_STATES
    return {
        "start": not running or current == "unsupervised",
        "stop": running and current != "stopping",
        "restart": running and current not in ("stopping", "unsupervised"),
        "open": current == "running",
        "settings": not running,
        "maintenance": not running,
        "setup": False,
    }


def lan_address() -> str | None:
    """This PC's address on the local network, or None when it has none.

    Connecting a UDP socket sends nothing; it only asks the OS which interface
    it would route through.
    """
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 80))  # TEST-NET-1: never routed, nothing is sent
        address = s.getsockname()[0]
        if not address.startswith(("127.", "0.")):
            return address
    return None


def tail(path: Path, lines: int = LOG_LINES) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64 * 1024))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 - opening a folder in Explorer
    else:
        subprocess.Popen(["xdg-open", str(path)])


def uv_command(paths: Paths) -> tuple[list[str], dict]:
    """``uv sync --frozen --no-dev`` with the install's own Python and download cache.

    The same command ``install-desktop.ps1`` runs. ``--no-dev`` because uv
    installs the ``dev`` group by default, and a client needs no test tools.
    """
    uv = paths.home / ("uv.exe" if IS_WINDOWS else "uv")
    exe = str(uv) if uv.exists() else (shutil.which("uv") or "uv")
    env = dict(os.environ)
    if (paths.home / "python").is_dir():
        env["UV_PYTHON_INSTALL_DIR"] = str(paths.home / "python")
    env["UV_CACHE_DIR"] = str(paths.home / "cache")
    env.setdefault("UV_HTTP_RETRIES", "5")
    env.setdefault("UV_PYTHON_PREFERENCE", "only-managed")
    return [exe, "sync", "--frozen", "--no-dev"], env


# --- start at login -----------------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _run_value_name(paths: Paths) -> str:
    return f"{display_name(paths.app)} server"


def set_start_at_login(paths: Paths, on: bool) -> None:
    """Start the keeper (not the panel) when this user logs in, via the per-user Run key."""
    if not IS_WINDOWS:
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            keeper_file = Path(__file__).with_name("keeper.py")
            command = (
                f'"{control._background_python()}" "{keeper_file}" '
                f'--home "{paths.home}" --app "{paths.app}"'
            )
            winreg.SetValueEx(key, _run_value_name(paths), 0, winreg.REG_SZ, command)
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, _run_value_name(paths))


# --- the window -----------------------------------------------------------------


class Panel:
    def __init__(self, root: tk.Tk, paths: Paths):
        self.root = root
        self.paths = paths
        self.name = display_name(paths.app)
        self.events: queue.Queue = queue.Queue()
        self.status: dict = {}
        self.busy: str | None = None  # a long task in progress, by name
        self.log_source: Path | None = None
        self.log_size = -1
        self._after_id = None

        root.title(f"{self.name} Control Panel")
        root.minsize(640, 560)
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        self._build()
        self._load_settings()
        self.refresh()
        self.root.after(200, self._drain_events)

    # layout --------------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        self.banner = ttk.Frame(outer)
        self.banner_label = ttk.Label(self.banner, foreground="#9a5b00", wraplength=560)
        self.banner_label.pack(side="left", fill="x", expand=True)
        self.banner_button = ttk.Button(
            self.banner, text="Finish installation", command=self.finish_install
        )
        self.banner_button.pack(side="right")

        top = ttk.LabelFrame(outer, text="Server", padding=8)
        top.pack(fill="x", **pad)
        self.top = top
        self.state_label = ttk.Label(top, font=("Segoe UI", 12, "bold"))
        self.state_label.grid(row=0, column=0, columnspan=4, sticky="w")
        self.message_label = ttk.Label(top, wraplength=600)
        self.message_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))
        self.buttons = {
            "start": ttk.Button(top, text="Start", command=self.start),
            "stop": ttk.Button(top, text="Stop", command=self.stop),
            "restart": ttk.Button(top, text="Restart", command=self.restart),
            "open": ttk.Button(top, text=f"Open {self.name}", command=self.open_app),
            "setup": ttk.Button(top, text="Set up your broker", command=self.setup_broker),
        }
        for column, button in enumerate(self.buttons.values()):
            button.grid(row=2, column=column, sticky="w", padx=(0, 6))
        self.address_label = ttk.Label(top, foreground="#555")
        self.address_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        middle = ttk.Frame(outer)
        middle.pack(fill="x", **pad)
        net = ttk.LabelFrame(middle, text="Network", padding=8)
        net.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.port_vars = {k: tk.StringVar() for k in ("http", "websocket", "zmq")}
        labels = {"http": "Web port", "websocket": "Live data port", "zmq": "Internal port"}
        self.settings_widgets = []
        for row, (key, var) in enumerate(self.port_vars.items()):
            ttk.Label(net, text=labels[key]).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(net, textvariable=var, width=8)
            entry.grid(row=row, column=1, sticky="w", pady=1)
            self.settings_widgets.append(entry)
        self.lan_var = tk.BooleanVar()
        lan = ttk.Checkbutton(
            net, text="Allow phones and other computers on my network", variable=self.lan_var
        )
        lan.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.settings_widgets.append(lan)
        save = ttk.Button(net, text="Save network settings", command=self.save_network)
        save.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.settings_widgets.append(save)
        self.network_note = ttk.Label(net, foreground="#555", wraplength=260)
        self.network_note.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        opts = ttk.LabelFrame(middle, text="Options", padding=8)
        opts.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.option_vars = {
            k: tk.BooleanVar() for k in ("auto_restart", "keep_awake", "start_at_login")
        }
        option_labels = {
            "auto_restart": "Restart automatically if it stops",
            "keep_awake": "Keep this PC awake while running",
            "start_at_login": "Start when I sign in to Windows",
        }
        for row, (key, var) in enumerate(self.option_vars.items()):
            ttk.Checkbutton(
                opts,
                text=option_labels[key],
                variable=var,
                command=lambda k=key: self.save_option(k),
            ).grid(row=row, column=0, sticky="w")
        ttk.Label(
            opts,
            text="Keeping awake stops idle sleep only. A closed laptop lid still sleeps.",
            foreground="#555",
            wraplength=260,
        ).grid(row=3, column=0, sticky="w", pady=(4, 0))

        tools = ttk.Frame(outer)
        tools.pack(fill="x", **pad)
        self.maintenance = [
            ttk.Button(tools, text="Switch broker (reset)", command=self.switch_broker),
            ttk.Button(tools, text="Repair dependencies", command=self.repair),
        ]
        for button in self.maintenance:
            button.pack(side="left", padx=(0, 6))
        ttk.Button(
            tools, text="Open install folder", command=lambda: open_folder(self.paths.home)
        ).pack(side="right")
        ttk.Button(
            tools, text="Open log folder", command=lambda: open_folder(self.paths.server_logs)
        ).pack(side="right", padx=(0, 6))

        logs = ttk.LabelFrame(outer, text="Log", padding=4)
        logs.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(
            logs, height=12, wrap="none", font=("Consolas", 9), state="disabled"
        )
        scroll = ttk.Scrollbar(logs, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    # settings ------------------------------------------------------------

    def _env_text(self) -> str:
        try:
            return (self.paths.app / ".env").read_text(encoding="utf-8")
        except OSError:
            return ""

    def _load_settings(self) -> None:
        network = envfile.read_network(self._env_text())
        self.port_vars["http"].set(str(network.http_port))
        self.port_vars["websocket"].set(str(network.websocket_port))
        self.port_vars["zmq"].set(str(network.zmq_port))
        self.lan_var.set(network.allow_lan)
        settings = read_settings(self.paths)
        for key, var in self.option_vars.items():
            var.set(bool(settings.get(key)))

    def save_option(self, key: str) -> None:
        settings = read_settings(self.paths)
        settings[key] = self.option_vars[key].get()
        write_json(self.paths.settings, settings)
        if key == "start_at_login":
            try:
                set_start_at_login(self.paths, settings[key])
            except OSError:
                messagebox.showerror(
                    self.name, "Windows did not allow changing the start-up setting."
                )
                self.option_vars[key].set(not settings[key])
                settings[key] = not settings[key]
                write_json(self.paths.settings, settings)
        if key in ("auto_restart", "keep_awake") and self.status.get("supervised"):
            self.network_note.configure(text="Option saved. It applies from the next start.")

    def save_network(self) -> None:
        try:
            network = envfile.Network(
                http_port=int(self.port_vars["http"].get()),
                websocket_port=int(self.port_vars["websocket"].get()),
                zmq_port=int(self.port_vars["zmq"].get()),
                allow_lan=self.lan_var.get(),
            )
        except ValueError:
            messagebox.showerror(self.name, "Ports must be whole numbers.")
            return
        problem = envfile.network_problem(network)
        if problem:
            messagebox.showerror(self.name, problem)
            return
        text = self._env_text()
        if not text:
            messagebox.showerror(
                self.name, "The settings file is missing. Use Switch broker to create a fresh one."
            )
            return
        old = envfile.read_network(text)
        busy = [
            p
            for p, before in (
                (network.http_port, old.http_port),
                (network.websocket_port, old.websocket_port),
                (network.zmq_port, old.zmq_port),
            )
            if p != before and port_in_use(p)
        ]
        if busy:
            messagebox.showerror(
                self.name, f"Port {busy[0]} is already used by another program. Choose another."
            )
            return
        env_path = self.paths.app / ".env"
        tmp = env_path.with_name(".env.panel-tmp")
        tmp.write_text(envfile.apply_network(text, network), encoding="utf-8", newline="\n")
        os.replace(tmp, env_path)
        note = "Saved."
        if network.http_port != old.http_port:
            redirect = envfile.read_values(self._env_text()).get("REDIRECT_URL", "")
            note += f" Update the redirect URL in your broker's app settings to {redirect}"
        self.network_note.configure(text=note)

    # actions ---------------------------------------------------------------

    def _in_background(self, name: str, work) -> None:
        """Run ``work`` off the window's thread; its result comes back as an event."""
        self.busy = name
        self.refresh()

        def run():
            try:
                self.events.put((name, "done", work()))
            except Exception as e:  # noqa: BLE001 - reported in the window
                self.events.put((name, "failed", e))

        threading.Thread(target=run, daemon=True).start()

    def start(self) -> None:
        self._in_background("start", lambda: control.start(self.paths))

    def stop(self) -> None:
        self._in_background("stop", lambda: control.stop(self.paths))

    def restart(self) -> None:
        self._in_background("restart", lambda: control.restart(self.paths))

    def open_app(self) -> None:
        port = envfile.read_network(self._env_text()).http_port
        webbrowser.open(f"http://127.0.0.1:{port}")

    def repair(self) -> None:
        if not messagebox.askokcancel(
            self.name,
            "Reinstall missing or damaged dependencies? This needs the internet and can take a few minutes.",
        ):
            return
        command, env = uv_command(self.paths)
        self._show_log_text("Repairing dependencies...\n")

        def work():
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            process = subprocess.Popen(
                command,
                cwd=self.paths.app,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
                text=True,
                errors="replace",
            )
            for line in process.stdout:
                self.events.put(("repair", "line", line))
            return process.wait()

        self._in_background("repair", work)

    def finish_install(self) -> None:
        script = self.paths.home / "install-desktop.ps1"
        if not script.exists():
            messagebox.showerror(
                self.name, "The installer is missing from the install folder. Contact support."
            )
            return
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            creationflags=subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0,
        )
        self.root.destroy()

    def switch_broker(self) -> None:
        SwitchBrokerDialog(self)

    def setup_broker(self) -> None:
        SwitchBrokerDialog(self, first_setup=True)

    # events and refresh -------------------------------------------------

    def _drain_events(self) -> None:
        with contextlib.suppress(queue.Empty):
            while True:
                name, kind, value = self.events.get_nowait()
                if kind == "line":
                    self._append_log(value)
                    continue
                self.busy = None
                if kind == "failed":
                    messagebox.showerror(self.name, f"That did not work: {value}")
                elif name == "start" and not value:
                    messagebox.showerror(
                        self.name, "The server could not be started. See the log for the reason."
                    )
                elif name == "stop" and not value:
                    messagebox.showerror(
                        self.name, "The server did not stop in time. Try Stop again."
                    )
                elif name == "repair":
                    self._append_log(
                        "\nDependencies are ready.\n"
                        if value == 0
                        else "\nRepair did not finish. Check the internet connection and try again.\n"
                    )
                    self.log_source = None
                elif name == "reset" and value:
                    value()
                self.refresh()
        self.root.after(200, self._drain_events)

    def refresh(self) -> None:
        with contextlib.suppress(OSError):
            self.status = control.status(self.paths)
        if not (self.paths.app / ".env").exists() and not self.status.get("supervised"):
            self.status = {
                "state": "setup",
                "message": "Choose your broker and enter its API key to finish setting up.",
            }
        current = self.status.get("state", "stopped")
        label = STATE_LABELS.get(current, current.title())
        if current == "running" and self.status.get("port"):
            label += f" on port {self.status['port']}"
        self.state_label.configure(text=label)
        message = self.status.get("message", "")
        if self.status.get("last_error") and current in ("crashed", "restarting"):
            message += f"\nLast error: {self.status['last_error']}"
        if self.busy:
            message = {
                "start": "Starting...",
                "stop": "Stopping...",
                "restart": "Restarting...",
                "repair": "Repairing dependencies...",
                "reset": "Resetting...",
            }.get(self.busy, message)
        self.message_label.configure(text=message)

        enabled = controls_for(self.status)
        for key, button in self.buttons.items():
            button.state(["!disabled"] if enabled[key] and not self.busy else ["disabled"])
        if enabled["setup"]:
            self.buttons["setup"].grid()
        else:
            self.buttons["setup"].grid_remove()
        for widget in self.settings_widgets + self.maintenance:
            usable = enabled["settings"] and not self.busy
            widget.state(["!disabled"] if usable else ["disabled"])

        network = envfile.read_network(self._env_text())
        address = f"On this PC: http://127.0.0.1:{network.http_port}"
        if network.allow_lan:
            lan = lan_address()
            address += (
                f"    On your phone: http://{lan}:{network.http_port}"
                if lan
                else "    (no network connection found)"
            )
        self.address_label.configure(text=address)

        install_ok = (self.paths.home / "install.ok").exists() or not (
            self.paths.home / "uv.exe"
        ).exists()
        if install_ok:
            self.banner.pack_forget()
        else:
            self.banner_label.configure(
                text="Installation is not finished. Connect to the internet and finish it."
            )
            self.banner.pack(fill="x", before=self.top, pady=(0, 6))

        if self.busy != "repair":
            self._refresh_log()
        # One pending refresh at a time: actions call refresh() directly, and
        # each call must replace the scheduled one, not add a second chain.
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(REFRESH_MS, self.refresh)

    def _refresh_log(self) -> None:
        source = self.status.get("log_file")
        path = Path(source) if source else None
        if path is None or not path.exists():
            return
        size = path.stat().st_size
        if path == self.log_source and size == self.log_size:
            return
        self.log_source, self.log_size = path, size
        self._show_log_text(tail(path))

    def _show_log_text(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


class SwitchBrokerDialog:
    """Reset to a fresh install for a new broker (launcher.eject), with its backup."""

    def __init__(self, panel: Panel, first_setup: bool = False):
        self.panel = panel
        self.first_setup = first_setup
        paths = panel.paths
        self.title = "Set up your broker" if first_setup else "Switch broker"
        self.win = tk.Toplevel(panel.root)
        self.win.title(self.title)
        self.win.transient(panel.root)
        self.win.grab_set()
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)

        intro = (
            f"Choose the broker {panel.name} will trade through and enter the API key and secret "
            "from its developer settings."
            if first_setup
            else f"This starts {panel.name} fresh for a new broker: your login, settings, orders, "
            "logs and saved strategies are removed. Everything is saved to a backup first. "
            "Dependencies are kept, so nothing is downloaded again."
        )
        ttk.Label(frame, wraplength=440, text=intro).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        sample = envfile.read_values((paths.app / ".sample.env").read_text(encoding="utf-8"))
        brokers = sorted(b.strip() for b in sample.get("VALID_BROKERS", "").split(",") if b.strip())
        self.vars = {
            k: tk.StringVar() for k in ("broker", "key", "secret", "mkey", "msecret", "confirm")
        }
        rows = [
            (
                "broker",
                "Broker",
                ttk.Combobox(
                    frame, textvariable=self.vars["broker"], values=brokers, state="readonly"
                ),
            ),
            ("key", "API key", ttk.Entry(frame, textvariable=self.vars["key"], width=40)),
            (
                "secret",
                "API secret",
                ttk.Entry(frame, textvariable=self.vars["secret"], width=40, show="*"),
            ),
            (
                "mkey",
                "Market data API key",
                ttk.Entry(frame, textvariable=self.vars["mkey"], width=40),
            ),
            (
                "msecret",
                "Market data API secret",
                ttk.Entry(frame, textvariable=self.vars["msecret"], width=40, show="*"),
            ),
        ]
        self.market_widgets = []
        for row, (key, label, widget) in enumerate(rows, start=1):
            text = ttk.Label(frame, text=label)
            text.grid(row=row, column=0, sticky="w", pady=2)
            widget.grid(row=row, column=1, sticky="we", pady=2)
            if key in ("mkey", "msecret"):
                self.market_widgets += [text, widget]
        self.vars["broker"].trace_add("write", lambda *_: self._broker_changed())
        self._broker_changed()

        self.keep_scripts = tk.BooleanVar(value=True)
        self.keep_history = tk.BooleanVar(value=True)
        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.go = ttk.Button(buttons, text=self.title, command=self.run)
        self.go.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.win.destroy).pack(side="right", padx=(0, 6))
        self.size_label = ttk.Label(frame, foreground="#555")
        if first_setup:
            return
        ttk.Checkbutton(
            frame,
            text="Keep my scripts and chart indicators",
            variable=self.keep_scripts,
            command=self._update_size,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            frame,
            text="Keep downloaded historical data",
            variable=self.keep_history,
            command=self._update_size,
        ).grid(row=7, column=0, columnspan=2, sticky="w")
        self.size_label.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="Type RESET to confirm").grid(
            row=9, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(frame, textvariable=self.vars["confirm"], width=12).grid(
            row=9, column=1, sticky="w", pady=(8, 0)
        )
        self._update_size()

    def _keep(self) -> set[str]:
        keep = set()
        if self.keep_scripts.get():
            keep.add("scripts")
        if self.keep_history.get():
            keep.add("history")
        return keep

    def _broker_changed(self) -> None:
        xts = self.vars["broker"].get() in envfile.XTS_BROKERS
        for widget in self.market_widgets:
            if xts:
                widget.grid()
            else:
                widget.grid_remove()

    def _update_size(self) -> None:
        try:
            planned = state.plan(self.panel.paths.app, self._keep())
            self.size_label.configure(
                text=f"About {eject.human_size(planned.total_size)} will be backed up and removed."
            )
        except state.NoReleaseList:
            self.size_label.configure(text="This installation cannot be reset. Contact support.")
            self.go.state(["disabled"])

    def run(self) -> None:
        v = {k: var.get() for k, var in self.vars.items()}
        if not self.first_setup and v["confirm"].strip() != "RESET":
            messagebox.showerror(self.title, "Type RESET to confirm.", parent=self.win)
            return
        broker = envfile.Broker(
            v["broker"].strip().lower(), v["key"], v["secret"], v["mkey"], v["msecret"]
        )
        sample = envfile.read_values(
            (self.panel.paths.app / ".sample.env").read_text(encoding="utf-8")
        )
        problem = envfile.broker_problem(broker, sample.get("VALID_BROKERS", ""))
        if problem:
            messagebox.showerror(self.title, problem, parent=self.win)
            return
        paths, keep, panel = self.panel.paths, self._keep(), self.panel
        if self.first_setup:
            write_first_env(paths, broker)
            self.win.destroy()
            panel._load_settings()
            redirect = envfile.read_values((paths.app / ".env").read_text(encoding="utf-8")).get(
                "REDIRECT_URL", ""
            )
            if messagebox.askyesno(
                self.title,
                f"In your {broker.name} developer settings, set the redirect URL to:\n{redirect}\n\n"
                f"Start {panel.name} now? You will create your login, then log in to {broker.name}.",
            ):
                panel.start()
            panel.refresh()
            return
        self.win.destroy()

        def work():
            try:
                _plan, backup = eject.reset(broker, paths.app, keep, paths.home / "backups")
            except eject.ResetRefused as e:
                message = str(e)
                return lambda: messagebox.showerror("Switch broker", message)
            redirect = envfile.read_values((paths.app / ".env").read_text(encoding="utf-8")).get(
                "REDIRECT_URL", ""
            )

            def done():
                panel._load_settings()
                if messagebox.askyesno(
                    "Switch broker",
                    f"Done. A backup was saved to {backup}.\n\nIn your {broker.name} developer settings, set the "
                    f"redirect URL to:\n{redirect}\n\nStart {panel.name} now? You will create a new login, then "
                    f"log in to {broker.name}.",
                ):
                    panel.start()

            return done

        panel._in_background("reset", work)


def write_first_env(paths: Paths, broker: envfile.Broker) -> None:
    """The first ``.env`` of a new install: fresh secrets, the broker, phones allowed.

    Other devices on the network are allowed by default (owner decision,
    2026-11-05); the panel's checkbox turns it off.
    """
    sample = (paths.app / ".sample.env").read_text(encoding="utf-8")
    text = envfile.fresh_env(sample, broker)
    network = envfile.read_network(text)
    text = envfile.apply_network(
        text,
        envfile.Network(
            network.http_port, network.websocket_port, network.zmq_port, allow_lan=True
        ),
    )
    env_path = paths.app / ".env"
    tmp = env_path.with_name(".env.panel-tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, env_path)


def dpi_aware() -> None:
    """Draw at the screen's real resolution.

    Without this Windows treats the panel as an old program and enlarges it as
    a bitmap on scaled displays (125%, 150%), which blurs every letter.
    """
    if IS_WINDOWS:
        import ctypes

        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shcore.SetProcessDpiAwareness(1)


def default_home() -> Path | None:
    """C:\\FastAlgo when this file sits in C:\\FastAlgo\\app\\launcher."""
    app = Path(__file__).resolve().parent.parent
    return app.parent if (app.parent / ("uv.exe" if IS_WINDOWS else "uv")).exists() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="panel")
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--app", type=Path)
    args = parser.parse_args(argv)
    if args.home is None:
        parser.error("--home is required outside the desktop install")
    paths = paths_for(args.home, args.app)

    dpi_aware()
    root = tk.Tk()
    lock = InstanceLock(paths.run / "panel.lock")
    if not lock.acquire():
        root.withdraw()
        messagebox.showinfo(display_name(paths.app), "The control panel is already open.")
        root.destroy()
        return 0
    try:
        with contextlib.suppress(tk.TclError):
            ttk.Style(root).theme_use("vista" if IS_WINDOWS else "clam")
        Panel(root, paths)
        root.mainloop()
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
