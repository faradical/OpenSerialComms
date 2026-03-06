from __future__ import annotations

import shlex
import threading
from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, RichLog, Static

from .api import SerialPort, connect, list_serial_ports

COMMANDS: list[tuple[str, str, str]] = [
    (">", "Write a message to the connected serial port.\n", ">hello world"),
    ("help", "Open the help screen.\n", "help"),
    ("clear", "Clear the visible message stream.\n", "clear"),
    ("close", "Close the current serial connection.\n", "close"),
    ("exit", "Close the serial connection and quit.\n", "exit"),
    ("log \"path/to/file\"", "Start/continue logging stream history to file.\n", "log \"serial.log\""),
    ("open <port>", "Open a new connection (only when disconnected).\n", "open COM5"),
    ("run \"path/to/file\"", "Write file contents to the connected port.\n", "run \"commands.txt\""),
]


class PortSelectionScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss_none", "Cancel")]

    def __init__(self, ports: list[str]) -> None:
        super().__init__()
        self.ports = ports

    def compose(self) -> ComposeResult:
        yield Static("Select a serial port to connect to:", id="port-title")
        items = [ListItem(Label(f"[{port}]")) for port in self.ports]
        yield ListView(*items, id="port-list")
        yield Static("OpenSerialComms 0.1.0", id="port-banner")

    def on_mount(self) -> None:
        lv = self.query_one("#port-list", ListView)
        if self.ports:
            lv.index = 0

    @on(ListView.Selected)
    def on_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            self.dismiss(None)
            return
        text = event.item.query_one(Label).renderable
        value = str(text).strip("[]")
        self.dismiss(value)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "return_only", "Return")]

    def compose(self) -> ComposeResult:
        items = [ListItem(Label(f"{cmd}\n  {desc}")) for cmd, desc, _ in COMMANDS]
        yield Static("OSC Commands", id="help-title")
        yield ListView(*items, id="help-list")
        with Horizontal(id="help-buttons"):
            yield Button("select command", id="select", variant="primary")
            yield Button("return", id="return")

    def on_mount(self) -> None:
        lv = self.query_one("#help-list", ListView)
        if COMMANDS:
            lv.index = 0
        # self.query_one("#select", Button).focus()
        lv.focus()

    def _selected_sample(self) -> str:
        lv = self.query_one("#help-list", ListView)
        idx = lv.index or 0
        idx = max(0, min(idx, len(COMMANDS) - 1))
        return COMMANDS[idx][2]

    @on(Button.Pressed, "#select")
    def on_select(self) -> None:
        self.dismiss(self._selected_sample())

    @on(Button.Pressed, "#return")
    def on_return(self) -> None:
        self.dismiss(None)

    def action_return_only(self) -> None:
        self.dismiss(None)


class OscApp(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #stream { height: 1fr; border: solid #444444; }
    #mid { height: 6; border: solid #444444; }
    #command-input { width: 2fr; }
    #command-output { width: 1fr; border: solid #444444; padding: 0 1; }
    #banner { 
        height: 3;
        border: solid #444444;
    }
    #banner-left { 
        content-align: left middle;
        width: 1fr;
        padding: 0 1;
    }
    #banner-middle { 
        content-align: center middle;
        width: 1fr;
        padding: 0 1;
    }
    #banner-right { 
        content-align: right middle;
        width: 1fr;
        padding: 0 1;
    }
    #help-title, #port-title { height: 3; content-align: center middle; }
    #help-list, #port-list { height: 1fr; border: solid #444444; }
    #help-buttons { height: 3; align: center middle; }
    #port-banner { height: 1; border: solid #444444; padding: 0 1; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, port: str | None, baud: str | int, timeout: str | int | float) -> None:
        super().__init__()
        self.requested_port = port
        self.baud = baud
        self.timeout = timeout
        self.serial_port: SerialPort | None = None
        self.history: list[str] = []
        self.log_path: Path | None = None
        self._stream_thread: threading.Thread | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RichLog(id="stream", auto_scroll=True, wrap=True)
            with Horizontal(id="mid"):
                yield Input(placeholder="Enter command", id="command-input")
                yield Static("", id="command-output")
            with Horizontal(id="banner"):
                yield Static("Connected to: <none>", id="banner-left")
                yield Static(">msg port   |   help - list cmds", id="banner-middle")
                yield Static("OpenSerialComms 0.1.0", id="banner-right")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#command-input", Input).focus()
        if self.requested_port:
            self._open_port(self.requested_port)
            return

        ports = list_serial_ports()
        if not ports:
            self._set_output("No serial ports detected. Use 'open <port>' to connect.")
            return
        self.push_screen(PortSelectionScreen(ports), self._on_port_selected)

    def _on_port_selected(self, result: str | None) -> None:
        if result:
            self._open_port(result)

    def _open_port(self, port: str) -> None:
        try:
            self.serial_port = connect(port, baudrate=self.baud, timeout=self.timeout)
        except Exception as exc:
            self._set_output(f"Failed to open {port}: {exc}")
            return

        self._set_banner(port)
        self._set_output(f"Connected to {port}")
        self._start_stream_thread()

    def _start_stream_thread(self) -> None:
        if self.serial_port is None:
            return

        def worker(sp: SerialPort) -> None:
            try:
                for event in sp.iter_stream():
                    self.call_from_thread(self._handle_stream_event, event)
            except Exception as exc:
                self.call_from_thread(self._set_output, f"Stream closed: {exc}")

        self._stream_thread = threading.Thread(target=worker, args=(self.serial_port,), daemon=True)
        self._stream_thread.start()

    def _handle_stream_event(self, event: dict[str, Any]) -> None:
        stream = self.query_one("#stream", RichLog)
        event_type = str(event.get("type", ""))
        if event_type == "sys" and event.get("event") == "closed":
            self._append_history("[sys] connection closed")
            stream.write("[sys] connection closed")
            self.serial_port = None
            self._set_banner(None)
            return

        payload = str(event.get("payload", ""))
        if not payload:
            return

        self._append_history(payload)
        if payload.startswith("> "):
            stream.write(f"[green]{payload}[/green]")
        else:
            stream.write(payload)

    def _append_history(self, line: str) -> None:
        self.history.append(line)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _set_output(self, text: str) -> None:
        self.query_one("#command-output", Static).update(text)

    def _set_banner(self, port: str | None) -> None:
        current = port if port else "<none>"
        self.query_one("#banner-left", Static).update(
            f"Connected to: {current}"
        )

    @on(Input.Submitted, "#command-input")
    def on_command(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return

        if raw.startswith(">"):
            self._cmd_write(raw[1:].lstrip())
            return

        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            self._set_output(f"Parse error: {exc}")
            return

        if not parts:
            return

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "help":
            self.push_screen(HelpScreen(), self._on_help_selected)
            return
        if cmd == "clear":
            self.query_one("#stream", RichLog).clear()
            self._set_output("Cleared current stream display")
            return
        if cmd == "close":
            self._cmd_close()
            return
        if cmd == "exit":
            self._cmd_exit()
            return
        if cmd == "log":
            self._cmd_log(args)
            return
        if cmd == "open":
            self._cmd_open(args)
            return
        if cmd == "run":
            self._cmd_run(args)
            return

        self._set_output(f"Unknown command: {cmd}")

    def _on_help_selected(self, sample: str | None) -> None:
        prompt = self.query_one("#command-input", Input)
        prompt.value = sample or ""
        prompt.focus()

    def _cmd_write(self, message: str) -> None:
        if not self.serial_port:
            self._set_output("No active port")
            return
        self.serial_port.write(message)
        self._set_output("Message queued")

    def _cmd_close(self) -> None:
        if not self.serial_port:
            self._set_output("No port is open")
            return
        self.serial_port.close()
        self.serial_port = None
        self.query_one("#stream", RichLog).clear()
        self.history.clear()
        self.log_path = None
        self._set_banner(None)
        self._set_output("Port closed")

    def _cmd_exit(self) -> None:
        if self.serial_port:
            self.serial_port.close()
        self.exit()

    def _cmd_log(self, args: list[str]) -> None:
        if len(args) != 1:
            self._set_output('Usage: log "path/to/file"')
            return
        path = Path(args[0]).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for line in self.history:
                handle.write(line + "\n")
        self.log_path = path
        self._set_output(f"Logging to {path}")

    def _cmd_open(self, args: list[str]) -> None:
        if self.serial_port:
            self._set_output("Please close the current connection")
            return

        if not args:
            ports = list_serial_ports()
            if not ports:
                self._set_output("No serial ports detected")
                return
            self.push_screen(PortSelectionScreen(ports), self._on_port_selected)
            return

        self._open_port(args[0])

    def _cmd_run(self, args: list[str]) -> None:
        if not self.serial_port:
            self._set_output("No active port")
            return
        if len(args) != 1:
            self._set_output('Usage: run "path/to/file"')
            return

        path = Path(args[0]).expanduser()
        if not path.exists():
            self._set_output(f"File not found: {path}")
            return

        data = path.read_text(encoding="utf-8")
        self.serial_port.write(data)
        self._set_output(f"Sent {len(data)} bytes from {path}")


def run_osc_tui(port: str | None = None, baud: str | int = 115200, timeout: str | int | float = 1) -> None:
    OscApp(port=port, baud=baud, timeout=timeout).run()
