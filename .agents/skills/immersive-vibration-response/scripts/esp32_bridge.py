#!/usr/bin/env python3
"""Asynchronous localhost TCP-to-USB bridge for the supplied ESP32 firmware."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import logging
import math
import queue
import signal
import threading
import time
from typing import Optional


MAX_COMMAND_LENGTH = 64
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 25363


def validate_command(line: str) -> tuple[bool, str]:
    """Validate the firmware command grammar without changing its semantics."""
    if not line:
        return False, "ERR empty command"
    if len(line) > MAX_COMMAND_LENGTH:
        return False, "ERR command too long"
    if not line.isascii():
        return False, "ERR command must be ASCII"

    parts = line.split()
    verb = parts[0].upper()
    if verb in {"PING", "STATUS", "SCAN", "SERVICES", "STOP"}:
        if len(parts) != 1:
            return False, f"ERR {verb} takes no arguments"
        return True, verb
    if verb == "HIT":
        if len(parts) != 2:
            return False, "ERR HIT requires one damage value"
        try:
            damage = float(parts[1])
        except ValueError:
            return False, "ERR HIT damage must be numeric"
        if not math.isfinite(damage):
            return False, "ERR HIT damage must be finite"
        return True, f"HIT {parts[1]}"
    if verb == "SET":
        if len(parts) != 2:
            return False, "ERR SET requires one level value"
        try:
            int(parts[1], 10)
        except ValueError:
            return False, "ERR SET level must be an integer"
        return True, f"SET {parts[1]}"
    return False, f"ERR unknown command: {parts[0]}"


def select_protocol_reply(raw_reply: str, command: str) -> str:
    """Return the response line most relevant to a firmware command."""
    lines = [line.strip() for line in raw_reply.splitlines() if line.strip()]
    if not lines:
        return ""
    verb = command.split(maxsplit=1)[0]
    expected = {
        "PING": "PONG",
        "STATUS": "STATUS",
        "SCAN": "OK SCAN",
        "SERVICES": "OK SERVICES",
        "SET": "OK SET",
        "HIT": "OK HIT",
        "STOP": "OK STOP",
    }.get(verb, "")
    for line in reversed(lines):
        if line.startswith(expected) or line.startswith("ERR"):
            return line
    return lines[-1]


@dataclass
class CommandJob:
    command: str
    done: threading.Event = field(default_factory=threading.Event)
    reply: str = ""


class SerialTransport:
    def __init__(self, port: str, baud: int, reply_wait: float) -> None:
        self.port = port
        self.baud = baud
        self.reply_wait = reply_wait
        self.serial = None

    def _require_pyserial(self):
        try:
            import serial  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("pyserial is required; run: python3 -m pip install -r requirements.txt") from exc
        return serial

    def open(self) -> None:
        if self.serial is not None and self.serial.is_open:
            return
        serial = self._require_pyserial()
        self.serial = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            write_timeout=1.0,
            dsrdtr=False,
            rtscts=False,
        )
        self.serial.dtr = False
        self.serial.rts = False
        time.sleep(3)
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        logging.info("serial opened on %s at %d baud", self.port, self.baud)

    def close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            finally:
                self.serial = None

    def send(self, command: str) -> str:
        try:
            self.open()
            assert self.serial is not None
            self.serial.write((command + "\n").encode("ascii"))
            self.serial.flush()
        except Exception:
            self.close()
            raise

        deadline = time.monotonic() + self.reply_wait
        chunks: list[str] = []
        while time.monotonic() < deadline:
            assert self.serial is not None
            waiting = self.serial.in_waiting
            if waiting:
                chunks.append(self.serial.read(waiting).decode("ascii", errors="replace"))
                reply = select_protocol_reply("".join(chunks), command)
                if reply:
                    return reply
            time.sleep(0.02)
        return "OK SENT " + command


class VibrationBridge:
    def __init__(self, serial_port: str, baud: int, reply_wait: float, queue_size: int) -> None:
        self.transport = SerialTransport(serial_port, baud, reply_wait)
        self.jobs: queue.Queue[Optional[CommandJob]] = queue.Queue(maxsize=queue_size)
        self.worker = threading.Thread(target=self._run_worker, name="esp32-serial", daemon=True)
        self.closed = False

    def start(self) -> None:
        self.worker.start()

    def _run_worker(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            try:
                job.reply = self.transport.send(job.command)
                logging.info("serial <= %s | => %s", job.command, job.reply)
            except Exception as exc:
                job.reply = f"ERR serial: {exc}"
                logging.warning("serial command failed: %s", exc)
            finally:
                job.done.set()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    line = raw.decode("ascii").strip()
                except UnicodeDecodeError:
                    writer.write(b"ERR command must be ASCII\n")
                    await writer.drain()
                    continue
                valid, result = validate_command(line)
                if not valid:
                    writer.write((result + "\n").encode("ascii"))
                    await writer.drain()
                    continue
                job = CommandJob(result)
                try:
                    self.jobs.put_nowait(job)
                except queue.Full:
                    writer.write(b"ERR bridge queue full\n")
                    await writer.drain()
                    continue
                if result.startswith("HIT "):
                    writer.write(("QUEUED " + result + "\n").encode("ascii"))
                    await writer.drain()
                    continue
                await asyncio.to_thread(job.done.wait)
                writer.write((job.reply + "\n").encode("ascii", errors="replace"))
                await writer.drain()
        except ConnectionError:
            logging.debug("client disconnected: %s", peer)
        finally:
            writer.close()
            await writer.wait_closed()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.jobs.put(None)
        self.worker.join(timeout=2)
        self.transport.close()


async def serve(args: argparse.Namespace) -> None:
    bridge = VibrationBridge(args.serial_port, args.baud, args.reply_wait, args.queue_size)
    bridge.start()
    server = await asyncio.start_server(bridge.handle_client, args.listen_address, args.listen_port)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logging.info("ESP32 vibration bridge listening on %s", sockets)
    stop_event = asyncio.Event()

    def request_shutdown() -> None:
        logging.info("shutting down bridge")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown)
        except NotImplementedError:
            pass
    try:
        async with server:
            await stop_event.wait()
    finally:
        bridge.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-port", required=True, help="ESP32 USB serial port, such as /dev/ttyACM0 or COM3")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--listen-address", default=DEFAULT_HOST)
    parser.add_argument("--listen-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reply-wait", type=float, default=1.0, help="seconds to wait for an ESP32 reply")
    parser.add_argument("--queue-size", type=int, default=64)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
