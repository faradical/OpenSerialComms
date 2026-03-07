"""OpenSerialComms public API."""

from .api import SerialPort, connect, list_open_ports, list_serial_ports

__all__ = ["SerialPort", "connect", "list_open_ports", "list_serial_ports"]
__version__ = "0.1.2"
