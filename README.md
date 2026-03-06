# OpenSerialComms (OSC)

Repository: https://github.com/faradical/OpenSerialComms

OpenSerialComms is a Python package for serial communications with two interfaces:

- API (`openserialcomms.connect`) for scripted use.
- TUI (`osc`) for interactive terminal use.

The API uses a fixed registry socket (`127.0.0.1:14563`) plus per-port write/stream sockets so multiple Python processes can coordinate access to one serial port.

## Installation

From GitHub:

```bash
pip install git+https://github.com/faradical/OpenSerialComms.git
```

From a local clone:

```bash
git clone https://github.com/faradical/OpenSerialComms.git
cd OpenSerialComms
pip install .
```

## CLI Usage

```bash
osc -port "COM5" -baud "9600" -timeout 1
```

Arguments:

- `-port <serial-port>`: Serial port (if omitted, a selection screen is shown).
- `-baud <baud-rate>`: Baud rate (default: `115200`).
- `-timeout <seconds>`: Serial read timeout (default: `1`).
- `-help`: Show help.

## API Usage

```python
import openserialcomms as osc

port = osc.connect("COM5", baudrate=115200, timeout=1)
port.write("hello\n")
port.stream()
```

### Core API

- `connect(port, baudrate=115200, timeout=1, ...) -> SerialPort`
- `SerialPort.write(message="")`
- `SerialPort.stream()`
- `SerialPort.close()`
- `SerialPort.iter_stream()` (event iterator)
- `list_serial_ports()`
- `list_open_ports()`

## TUI Commands

- `>message`: Write to current port.
- `help`: Open help screen.
- `clear`: Clear visible stream.
- `close`: Close current connection.
- `exit`: Close and quit.
- `log "path/to/file"`: Start file logging and backfill existing history.
- `open [<port>] [-baud <rate>] [-timeout <seconds>]`: Open a port when disconnected. If `<port>` is omitted, open the port selection screen using the provided or current settings.
- `run "path/to/file"`: Send file contents to the current port.

## Notes

- Serial URLs supported by `pyserial` (for example `loop://`) can be used.
- Message stream history is retained in-memory until connection close, then purged.
- Remote instances can stream/write through socket endpoints owned by the first process that opened a given port.

## Contributing and Issues

- Issues: https://github.com/faradical/OpenSerialComms/issues
- Repository: https://github.com/faradical/OpenSerialComms

## License

GNU General Public License v3.0. See `LICENSE`.

