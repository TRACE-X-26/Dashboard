from __future__ import annotations

import argparse
import json
from glob import glob
from typing import Callable

from .protocol import CommandName
from .stm32 import STM32SerialConnection


def discover_serial_port() -> str:
    """Return the most stable available STM32 serial path."""
    candidates = [
        *sorted(glob("/dev/serial/by-id/*STMicroelectronics*")),
        *sorted(glob("/dev/serial/by-id/*STLink*")),
        *sorted(glob("/dev/ttyACM*")),
        *sorted(glob("/dev/cu.usbmodem*")),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            return candidate
    raise FileNotFoundError(
        "No STM32 serial port found. Connect the Nucleo ST-LINK USB port and "
        "check /dev/ttyACM* or /dev/serial/by-id/."
    )


def verify_connection(
    port: str,
    baud: int = 115200,
    *,
    connection_factory: Callable[..., STM32SerialConnection] = STM32SerialConnection,
) -> dict:
    """Run communication-only checks without enabling physical outputs."""
    connection = connection_factory(
        port=port,
        baud=baud,
        command_timeout=3.0,
        allow_motor_control=False,
    )
    connection.connect()
    try:
        status = connection.status()
        capabilities = connection.capabilities()
        faults = connection.execute(CommandName.GET_FAULTS.value)
        heartbeat = connection.heartbeat()
    finally:
        connection.disconnect()

    if status.get("hardware_control") is not False:
        raise RuntimeError("STM32 did not report hardware control as disabled")
    if heartbeat.get("alive") is not True:
        raise RuntimeError("STM32 heartbeat did not report alive")

    return {
        "port": port,
        "baud": baud,
        "device_id": capabilities.device_id,
        "firmware_version": capabilities.firmware_version,
        "state": status.get("state"),
        "faults": faults.get("faults", status.get("faults", [])),
        "heartbeat_alive": heartbeat.get("alive"),
        "hardware_control": status.get("hardware_control"),
        "commands": list(capabilities.commands),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely verify Raspberry Pi USB serial communication with STM32."
    )
    parser.add_argument(
        "--port",
        help="Serial device path. If omitted, the tester searches by-id and ttyACM paths.",
    )
    parser.add_argument("--baud", type=int, default=115200)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        port = args.port or discover_serial_port()
        result = verify_connection(port, args.baud)
    except Exception as exc:
        print("STM32 CONNECTION TEST: FAILED")
        print(f"Reason: {exc}")
        print("Check the USB cable, serial port, plugdev/dialout membership, and close other serial programs.")
        return 1

    print("STM32 CONNECTION TEST: PASSED")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
