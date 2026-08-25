#!/usr/bin/env python3
"""Asynchronous localhost TCP-to-USB bridge for the supplied ESP32 firmware."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import logging
import math
import queue
import random
import re
import signal
import threading
import time
from typing import Any, Optional


MAX_COMMAND_LENGTH = 64
MAX_BRIDGE_COMMAND_LENGTH = 16_384
MAX_PATTERN_STEPS = 128
MAX_PATTERN_PERIOD_MS = 86_400_000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 25363
PATTERN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PatternValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PatternStep:
    at_ms: int
    command: str
    chance: float
    jitter_ms: int


@dataclass(frozen=True)
class PatternSpec:
    pattern_id: str
    repeat: Optional[int]
    period_ms: int
    start_delay_ms: int
    steps: tuple[PatternStep, ...]
    replace: bool


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


def _require_integer(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PatternValidationError(f"{field_name} must be an integer from {minimum} to {maximum}")
    return value


def parse_pattern_spec(payload: str) -> PatternSpec:
    """Parse a bridge-local JSON timeline into safe firmware command steps."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PatternValidationError(f"invalid pattern JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise PatternValidationError("pattern must be a JSON object")

    pattern_id = data.get("id")
    if not isinstance(pattern_id, str) or not PATTERN_ID.fullmatch(pattern_id):
        raise PatternValidationError("id must use 1-64 letters, digits, dots, underscores, or hyphens")
    period_ms = _require_integer(data.get("period_ms"), "period_ms", 1, MAX_PATTERN_PERIOD_MS)
    start_delay_ms = _require_integer(data.get("start_delay_ms", 0), "start_delay_ms", 0, MAX_PATTERN_PERIOD_MS)
    repeat_value = data.get("repeat", 1)
    if repeat_value == "forever":
        repeat: Optional[int] = None
    else:
        repeat = _require_integer(repeat_value, "repeat", 1, 100_000)
    replace = data.get("replace", True)
    if not isinstance(replace, bool):
        raise PatternValidationError("replace must be true or false")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_PATTERN_STEPS:
        raise PatternValidationError(f"steps must contain 1-{MAX_PATTERN_STEPS} entries")
    steps: list[PatternStep] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise PatternValidationError(f"steps[{index}] must be an object")
        at_ms = _require_integer(raw_step.get("at_ms"), f"steps[{index}].at_ms", 0, period_ms - 1)
        jitter_ms = _require_integer(raw_step.get("jitter_ms", 0), f"steps[{index}].jitter_ms", 0, period_ms)
        chance = raw_step.get("chance", 1.0)
        if isinstance(chance, bool) or not isinstance(chance, (int, float)) or not 0 <= chance <= 1:
            raise PatternValidationError(f"steps[{index}].chance must be a number from 0 to 1")
        command = raw_step.get("command")
        if not isinstance(command, str):
            raise PatternValidationError(f"steps[{index}].command must be a firmware command string")
        valid, canonical_command = validate_command(command)
        if not valid:
            raise PatternValidationError(f"steps[{index}].command: {canonical_command}")
        if canonical_command.split(maxsplit=1)[0] not in {"HIT", "SET", "STOP"}:
            raise PatternValidationError(f"steps[{index}].command must be HIT, SET, or STOP")
        steps.append(PatternStep(at_ms, canonical_command, float(chance), jitter_ms))

    return PatternSpec(pattern_id, repeat, period_ms, start_delay_ms, tuple(steps), replace)


def parse_bridge_command(line: str) -> tuple[str, Any]:
    """Parse firmware commands plus bridge-local pattern commands."""
    if not line:
        raise PatternValidationError("empty command")
    if len(line) > MAX_BRIDGE_COMMAND_LENGTH:
        raise PatternValidationError(f"bridge command exceeds {MAX_BRIDGE_COMMAND_LENGTH} characters")
    if not line.isascii():
        raise PatternValidationError("bridge command must be ASCII")
    if line == "PATTERNS":
        return "patterns", None
    if line == "CANCEL ALL":
        return "cancel-all", None
    if line.startswith("CANCEL "):
        pattern_id = line[7:].strip()
        if not PATTERN_ID.fullmatch(pattern_id):
            raise PatternValidationError("cancel id must use 1-64 letters, digits, dots, underscores, or hyphens")
        return "cancel", pattern_id
    if line.startswith("PATTERN "):
        return "pattern", parse_pattern_spec(line[8:].strip())
    valid, command = validate_command(line)
    if not valid:
        raise PatternValidationError(command)
    return "firmware", command


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
        time.sleep(3)
        self._prepare_open_port()
        logging.info("serial opened on %s at %d baud", self.port, self.baud)

    def _prepare_open_port(self) -> None:
        """Apply optional serial setup without rejecting USB drivers that lack modem control."""
        assert self.serial is not None
        for attribute in ("dtr", "rts"):
            try:
                setattr(self.serial, attribute, False)
            except (OSError, ValueError) as exc:
                logging.debug("serial port does not support setting %s: %s", attribute.upper(), exc)
        for method_name in ("reset_input_buffer", "reset_output_buffer"):
            try:
                getattr(self.serial, method_name)()
            except (OSError, ValueError) as exc:
                logging.debug("serial port does not support %s: %s", method_name, exc)

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
        self.patterns: dict[str, asyncio.Task[None]] = {}
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

    def enqueue_firmware_command(self, command: str) -> bool:
        try:
            self.jobs.put_nowait(CommandJob(command))
        except queue.Full:
            return False
        return True

    def start_pattern(self, pattern: PatternSpec) -> None:
        existing = self.patterns.get(pattern.pattern_id)
        if existing is not None and not existing.done():
            if not pattern.replace:
                raise PatternValidationError(f"pattern already active: {pattern.pattern_id}")
            existing.cancel()
        task = asyncio.create_task(self._run_pattern(pattern), name=f"vibration-pattern:{pattern.pattern_id}")
        self.patterns[pattern.pattern_id] = task
        task.add_done_callback(lambda completed: self._finish_pattern(pattern.pattern_id, completed))

    def _finish_pattern(self, pattern_id: str, task: asyncio.Task[None]) -> None:
        if self.patterns.get(pattern_id) is task:
            self.patterns.pop(pattern_id, None)
        if task.cancelled():
            logging.info("pattern cancelled: %s", pattern_id)
            return
        error = task.exception()
        if error is not None:
            logging.warning("pattern failed: %s: %s", pattern_id, error)
        else:
            logging.info("pattern complete: %s", pattern_id)

    async def _run_pattern(self, pattern: PatternSpec) -> None:
        if pattern.start_delay_ms:
            await asyncio.sleep(pattern.start_delay_ms / 1000)
        iteration = 0
        while pattern.repeat is None or iteration < pattern.repeat:
            started_at = time.monotonic()
            timeline: list[tuple[int, PatternStep]] = []
            for step in pattern.steps:
                offset = step.at_ms + random.randint(-step.jitter_ms, step.jitter_ms)
                timeline.append((max(0, min(pattern.period_ms - 1, offset)), step))
            for offset_ms, step in sorted(timeline, key=lambda item: item[0]):
                remaining = started_at + offset_ms / 1000 - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                if random.random() <= step.chance and not self.enqueue_firmware_command(step.command):
                    logging.warning("pattern step dropped because the serial queue is full: %s", pattern.pattern_id)
            iteration += 1
            remaining = started_at + pattern.period_ms / 1000 - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)

    def cancel_pattern(self, pattern_id: str) -> bool:
        task = self.patterns.get(pattern_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def cancel_all_patterns(self) -> int:
        active = [pattern_id for pattern_id in self.patterns if self.cancel_pattern(pattern_id)]
        return len(active)

    def active_pattern_ids(self) -> list[str]:
        return sorted(pattern_id for pattern_id, task in self.patterns.items() if not task.done())

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    line = raw.decode("ascii").strip()
                    kind, payload = parse_bridge_command(line)
                except (UnicodeDecodeError, PatternValidationError) as exc:
                    writer.write((f"ERR {exc}\n").encode("ascii", errors="replace"))
                    await writer.drain()
                    continue
                if kind == "pattern":
                    try:
                        self.start_pattern(payload)
                    except PatternValidationError as exc:
                        writer.write((f"ERR {exc}\n").encode("ascii"))
                    else:
                        writer.write((f"QUEUED PATTERN {payload.pattern_id}\n").encode("ascii"))
                    await writer.drain()
                    continue
                if kind == "patterns":
                    response = json.dumps({"active": self.active_pattern_ids()}, separators=(",", ":"))
                    writer.write((f"PATTERNS {response}\n").encode("ascii"))
                    await writer.drain()
                    continue
                if kind == "cancel-all":
                    writer.write((f"OK CANCEL ALL {self.cancel_all_patterns()}\n").encode("ascii"))
                    await writer.drain()
                    continue
                if kind == "cancel":
                    state = "OK" if self.cancel_pattern(payload) else "OK INACTIVE"
                    writer.write((f"{state} CANCEL {payload}\n").encode("ascii"))
                    await writer.drain()
                    continue
                command = payload
                job = CommandJob(command)
                try:
                    self.jobs.put_nowait(job)
                except queue.Full:
                    writer.write(b"ERR bridge queue full\n")
                    await writer.drain()
                    continue
                if command.startswith("HIT "):
                    writer.write(("QUEUED " + command + "\n").encode("ascii"))
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
        self.cancel_all_patterns()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            logging.warning("serial queue remained full while closing the bridge")
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
    parser.add_argument(
        "--serial-port",
        required=True,
        help="ESP32 USB serial port, such as /dev/ttyACM0, /dev/cu.usbmodem1101, or COM3",
    )
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
