import asyncio
import importlib.util
from pathlib import Path
import sys
import time
import unittest


BRIDGE_PATH = Path(__file__).parents[1] / ".agents/skills/immersive-vibration-response/scripts/esp32_bridge.py"
SPEC = importlib.util.spec_from_file_location("esp32_bridge", BRIDGE_PATH)
assert SPEC and SPEC.loader
BRIDGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BRIDGE
SPEC.loader.exec_module(BRIDGE)


class BridgeProtocolTests(unittest.TestCase):
    def test_hit_accepts_firmware_damage_as_float(self):
        self.assertEqual(BRIDGE.validate_command("HIT 2.5"), (True, "HIT 2.5"))
        self.assertEqual(BRIDGE.validate_command("HIT NaN"), (False, "ERR HIT damage must be finite"))

    def test_set_requires_one_integer_level(self):
        self.assertEqual(BRIDGE.validate_command("SET 45"), (True, "SET 45"))
        self.assertEqual(BRIDGE.validate_command("SET 4.5"), (False, "ERR SET level must be an integer"))

    def test_rejects_invalid_commands(self):
        self.assertEqual(BRIDGE.validate_command("HIT"), (False, "ERR HIT requires one damage value"))
        self.assertEqual(BRIDGE.validate_command("UNKNOWN"), (False, "ERR unknown command: UNKNOWN"))

    def test_selects_matching_firmware_reply(self):
        raw = "GALAKU connected\nOK HIT damage=1.00 level=10\n"
        self.assertEqual(BRIDGE.select_protocol_reply(raw, "HIT 1"), "OK HIT damage=1.00 level=10")

    def test_tolerates_serial_drivers_without_modem_or_buffer_controls(self):
        class LimitedSerialPort:
            def __setattr__(self, name, value):
                if name in {"dtr", "rts"}:
                    raise OSError("unsupported")
                super().__setattr__(name, value)

            def reset_input_buffer(self):
                raise OSError("unsupported")

            def reset_output_buffer(self):
                raise OSError("unsupported")

        transport = BRIDGE.SerialTransport("unused", 115200, 0.1)
        transport.serial = LimitedSerialPort()
        transport._prepare_open_port()


class FakeTransport:
    def send(self, command):
        time.sleep(0.05)
        return "PONG" if command == "PING" else f"OK SENT {command}"

    def close(self):
        pass


class AsyncBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = BRIDGE.VibrationBridge("unused", 115200, 0.1, 4)
        self.bridge.transport = FakeTransport()
        self.bridge.start()
        self.server = await asyncio.start_server(self.bridge.handle_client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.bridge.close()

    async def test_hit_is_accepted_without_waiting_for_serial_worker(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"HIT 1\n")
        await writer.drain()
        self.assertEqual((await reader.readline()).decode().strip(), "QUEUED HIT 1")
        writer.close()
        await writer.wait_closed()

    async def test_ping_waits_for_a_protocol_reply(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"PING\n")
        await writer.drain()
        self.assertEqual((await reader.readline()).decode().strip(), "PONG")
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
