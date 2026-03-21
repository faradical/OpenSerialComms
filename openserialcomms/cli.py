from __future__ import annotations

import argparse
import sys

from .tui import run_osc_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="osc", add_help=False)
    parser.add_argument("-port", type=str, default=None, help="Serial port to connect to")
    parser.add_argument("-baud", type=str, default="115200", help="Baud rate")
    parser.add_argument("-timeout", type=str, default="1", help="Serial read timeout")
    parser.add_argument("-newline", type=str, default="\\r", help="Default newline appended to writes")
    parser.add_argument("-help", action="store_true", help="Show help and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.help:
        parser.print_help(sys.stdout)
        return 0

    run_osc_tui(port=args.port, baud=args.baud, timeout=args.timeout, newline=args.newline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
