from __future__ import annotations

import atexit
import json
import queue
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generator

import serial
from serial import SerialException
from serial.tools import list_ports

REGISTRY_HOST = "127.0.0.1"
REGISTRY_PORT = 14563
SOCKET_BACKLOG = 16

_CLOSE_MARKER = "__OSC_CLOSE__"


def _to_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _to_float(value: Any, default: float | None) -> float | None:
    if value is None:
        return default
    return float(value)


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((REGISTRY_HOST, 0))
        return int(s.getsockname()[1])


def _recv_line(sock: socket.socket) -> str:
    data = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break
    if not data:
        return ""
    return bytes(data).split(b"\n", 1)[0].decode("utf-8", errors="replace")


def _send_json(sock: socket.socket, payload: dict[str, Any]) -> None:
    blob = json.dumps(payload, separators=(",", ":")) + "\n"
    sock.sendall(blob.encode("utf-8"))


def _registry_request(message: dict[str, Any], timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        with socket.create_connection((REGISTRY_HOST, REGISTRY_PORT), timeout=timeout) as sock:
            _send_json(sock, message)
            reply = _recv_line(sock)
    except OSError:
        return None
    if not reply:
        return None
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        return None


class _RegistryService:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_thread: threading.Thread | None = None
        self._server_socket: socket.socket | None = None

    def start(self) -> bool:
        if self._server_thread and self._server_thread.is_alive():
            return True
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((REGISTRY_HOST, REGISTRY_PORT))
            server.listen(SOCKET_BACKLOG)
            server.settimeout(0.5)
        except OSError:
            return False

        self._server_socket = server
        self._server_thread = threading.Thread(target=self._serve, name="osc-registry", daemon=True)
        self._server_thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def _serve(self) -> None:
        assert self._server_socket is not None
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        with conn:
            line = _recv_line(conn)
            if not line:
                return
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                _send_json(conn, {"ok": False, "error": "invalid-json"})
                return

            cmd = req.get("cmd")
            if cmd == "lookup":
                port_name = str(req.get("port", ""))
                with self._lock:
                    record = self._records.get(port_name)
                _send_json(conn, {"ok": True, "record": record})
                return

            if cmd == "list":
                with self._lock:
                    records = dict(self._records)
                _send_json(conn, {"ok": True, "records": records})
                return

            if cmd == "register":
                port_name = str(req.get("port", ""))
                record = req.get("record")
                if not isinstance(record, dict) or not port_name:
                    _send_json(conn, {"ok": False, "error": "bad-register"})
                    return
                with self._lock:
                    self._records[port_name] = record
                _send_json(conn, {"ok": True})
                return

            if cmd == "unregister":
                port_name = str(req.get("port", ""))
                with self._lock:
                    self._records.pop(port_name, None)
                _send_json(conn, {"ok": True})
                return

            _send_json(conn, {"ok": False, "error": "unknown-cmd"})


_REGISTRY = _RegistryService()


@dataclass
class _PortRecord:
    port: str
    write_port: int
    stream_port: int
    owner_pid: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "_PortRecord":
        return cls(
            port=str(payload["port"]),
            write_port=int(payload["write_port"]),
            stream_port=int(payload["stream_port"]),
            owner_pid=int(payload.get("owner_pid", -1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "write_port": self.write_port,
            "stream_port": self.stream_port,
            "owner_pid": self.owner_pid,
        }


class _OwnedEndpoint:
    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout: float | None,
        bytesize: int,
        parity: str,
        stopbits: float,
        xonxoff: bool,
        rtscts: bool,
        dsrdtr: bool,
    ) -> None:
        self.port = port
        self.serial = serial.serial_for_url(
            port,
            baudrate=baudrate,
            timeout=timeout,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            xonxoff=xonxoff,
            rtscts=rtscts,
            dsrdtr=dsrdtr,
        )
        self.write_port = _get_free_port()
        self.stream_port = _get_free_port()

        self._closed = threading.Event()
        self._write_queue: queue.Queue[str] = queue.Queue()
        self._stream_clients: list[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._server_sockets: list[socket.socket] = []
        self._threads: list[threading.Thread] = []

        self._start_servers()

    def _start_servers(self) -> None:
        write_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        write_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        write_server.bind((REGISTRY_HOST, self.write_port))
        write_server.listen(SOCKET_BACKLOG)
        write_server.settimeout(0.5)

        stream_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stream_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        stream_server.bind((REGISTRY_HOST, self.stream_port))
        stream_server.listen(SOCKET_BACKLOG)
        stream_server.settimeout(0.5)

        self._server_sockets.extend([write_server, stream_server])

        self._threads.extend(
            [
                threading.Thread(target=self._write_server_loop, args=(write_server,), daemon=True),
                threading.Thread(target=self._stream_server_loop, args=(stream_server,), daemon=True),
                threading.Thread(target=self._io_loop, daemon=True),
            ]
        )

        for thread in self._threads:
            thread.start()

    def _write_server_loop(self, server: socket.socket) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_writer_conn, args=(conn,), daemon=True).start()

    def _handle_writer_conn(self, conn: socket.socket) -> None:
        with conn:
            line = _recv_line(conn)
            if not line:
                return
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                return
            cmd = req.get("cmd")
            if cmd == "write":
                message = str(req.get("message", ""))
                self._write_queue.put(message)
                return
            if cmd == "close":
                self._write_queue.put(_CLOSE_MARKER)

    def _stream_server_loop(self, server: socket.socket) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setblocking(True)
            with self._clients_lock:
                self._stream_clients.append(conn)

    def _broadcast(self, event: dict[str, Any]) -> None:
        encoded = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
        dead: list[socket.socket] = []
        with self._clients_lock:
            for client in self._stream_clients:
                try:
                    client.sendall(encoded)
                except OSError:
                    dead.append(client)
            for client in dead:
                try:
                    client.close()
                except OSError:
                    pass
                if client in self._stream_clients:
                    self._stream_clients.remove(client)

    def _io_loop(self) -> None:
        while not self._closed.is_set():
            # Drain queued outbound writes first.
            while not self._write_queue.empty():
                message = self._write_queue.get_nowait()
                if message == _CLOSE_MARKER:
                    self._broadcast({"type": "sys", "event": "closed", "port": self.port})
                    self.shutdown()
                    return
                data = message.encode("utf-8")
                self.serial.write(data)
                self._broadcast({"type": "data", "direction": "out", "payload": f"> {message}"})

            incoming = self.serial.readline()
            if incoming:
                decoded = incoming.decode("utf-8", errors="replace").rstrip("\r\n")
                self._broadcast({"type": "data", "direction": "in", "payload": decoded})
            else:
                time.sleep(0.02)

    def send_write(self, message: str) -> None:
        self._write_queue.put(message)

    def send_close(self) -> None:
        self._write_queue.put(_CLOSE_MARKER)

    def shutdown(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.serial.close()
        except OSError:
            pass

        for server in self._server_sockets:
            try:
                server.close()
            except OSError:
                pass

        with self._clients_lock:
            for client in self._stream_clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._stream_clients.clear()


_OWNED_ENDPOINTS: dict[str, _OwnedEndpoint] = {}
_OWNERSHIP_LOCK = threading.Lock()


def _ensure_registry() -> None:
    if _registry_request({"cmd": "list"}) is None:
        _REGISTRY.start()


def _lookup_port(port: str) -> _PortRecord | None:
    response = _registry_request({"cmd": "lookup", "port": port})
    if not response or not response.get("ok"):
        return None
    record = response.get("record")
    if not record:
        return None
    try:
        return _PortRecord.from_dict(record)
    except Exception:
        return None


def _register_port(record: _PortRecord) -> bool:
    response = _registry_request({"cmd": "register", "port": record.port, "record": record.to_dict()})
    return bool(response and response.get("ok"))


def _unregister_port(port: str) -> None:
    _registry_request({"cmd": "unregister", "port": port})


class SerialPort:
    """Serial port handle that may own a physical serial device or proxy through sockets."""

    known_ports: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        port: str,
        write_port: int,
        stream_port: int,
        owns_serial: bool,
        endpoint: _OwnedEndpoint | None,
    ) -> None:
        self.port = port
        self.write_port = write_port
        self.stream_port = stream_port
        self.owns_serial = owns_serial
        self._endpoint = endpoint

        SerialPort.known_ports[port] = {
            "write_port": write_port,
            "stream_port": stream_port,
            "owns_serial": owns_serial,
        }

    def write(self, message: str = "") -> None:
        if message == "":
            return
        if self.owns_serial and self._endpoint is not None:
            self._endpoint.send_write(message)
            return

        with socket.create_connection((REGISTRY_HOST, self.write_port), timeout=1.0) as sock:
            _send_json(sock, {"cmd": "write", "message": message})

    def iter_stream(self) -> Generator[dict[str, Any], None, None]:
        with socket.create_connection((REGISTRY_HOST, self.stream_port), timeout=1.0) as sock:
            sock.settimeout(0.5)
            carry = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                carry += chunk
                while b"\n" in carry:
                    line, carry = carry.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    yield event
                    if event.get("type") == "sys" and event.get("event") == "closed":
                        return

    def stream(self, printer: Callable[[str], None] = print) -> None:
        for event in self.iter_stream():
            payload = str(event.get("payload", ""))
            if payload:
                printer(payload)
            elif event.get("type") == "sys":
                printer(f"[sys] {event.get('event')}")

    def close(self) -> None:
        if self.owns_serial and self._endpoint is not None:
            self._endpoint.send_close()
            return

        with socket.create_connection((REGISTRY_HOST, self.write_port), timeout=1.0) as sock:
            _send_json(sock, {"cmd": "close"})


def connect(
    port: str,
    baudrate: int | str = 115200,
    timeout: float | int | str | None = 1,
    bytesize: int = serial.EIGHTBITS,
    parity: str = serial.PARITY_NONE,
    stopbits: float = serial.STOPBITS_ONE,
    xonxoff: bool = False,
    rtscts: bool = False,
    dsrdtr: bool = False,
) -> SerialPort:
    """Connect to a serial port; if already owned, return a proxy to its sockets."""

    port = str(port)
    _ensure_registry()

    existing = _lookup_port(port)
    if existing is not None:
        return SerialPort(
            port=existing.port,
            write_port=existing.write_port,
            stream_port=existing.stream_port,
            owns_serial=False,
            endpoint=None,
        )

    baud = _to_int(baudrate, 115200)
    tout = _to_float(timeout, 1.0)

    try:
        endpoint = _OwnedEndpoint(
            port=port,
            baudrate=baud,
            timeout=tout,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            xonxoff=xonxoff,
            rtscts=rtscts,
            dsrdtr=dsrdtr,
        )
    except SerialException:
        # Another process may have won the race; re-check registry.
        existing_after = _lookup_port(port)
        if existing_after is not None:
            return SerialPort(
                port=existing_after.port,
                write_port=existing_after.write_port,
                stream_port=existing_after.stream_port,
                owns_serial=False,
                endpoint=None,
            )
        raise

    record = _PortRecord(
        port=port,
        write_port=endpoint.write_port,
        stream_port=endpoint.stream_port,
        owner_pid=-1,
    )

    if not _register_port(record):
        endpoint.shutdown()
        # Registry changed while opening; attach as proxy if now available.
        existing_after = _lookup_port(port)
        if existing_after is not None:
            return SerialPort(
                port=existing_after.port,
                write_port=existing_after.write_port,
                stream_port=existing_after.stream_port,
                owns_serial=False,
                endpoint=None,
            )
        raise RuntimeError("Failed to register opened serial port")

    with _OWNERSHIP_LOCK:
        _OWNED_ENDPOINTS[port] = endpoint

    return SerialPort(
        port=port,
        write_port=endpoint.write_port,
        stream_port=endpoint.stream_port,
        owns_serial=True,
        endpoint=endpoint,
    )


def list_serial_ports() -> list[str]:
    return [entry.device for entry in list_ports.comports()]


def list_open_ports() -> dict[str, dict[str, Any]]:
    response = _registry_request({"cmd": "list"})
    if not response or not response.get("ok"):
        return {}
    records = response.get("records")
    return records if isinstance(records, dict) else {}


def _cleanup() -> None:
    with _OWNERSHIP_LOCK:
        ports = list(_OWNED_ENDPOINTS.keys())
    for port in ports:
        endpoint = _OWNED_ENDPOINTS.pop(port, None)
        if endpoint is None:
            continue
        endpoint.shutdown()
        _unregister_port(port)


atexit.register(_cleanup)
