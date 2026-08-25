# ESP32 Vibration Protocol

The ESP32 firmware accepts ASCII lines over USB serial. The local TCP bridge accepts the same command lines and forwards them to the ESP32.

## Commands

| Command | Firmware behavior | Use |
| --- | --- | --- |
| `PING` | Replies `PONG`. | Confirm the serial path. |
| `STATUS` | Reports BLE, scan, connection, service, target, and current level state. | Diagnose availability. |
| `SCAN` | Starts or resumes searching for the `GK36` BLE device. | Recover a disconnected device. |
| `SERVICES` | Lists BLE services when connected. | Firmware and BLE diagnosis. |
| `HIT <damage>` | Rounds damage to at least 1, adds `damage * 10` to the current level, clamps to 100, and resets the hold timer. | Normal asynchronous game feedback. |
| `SET <0-100>` | Sets the current level directly, clamps it to 0 through 100, and resets the hold timer. | Rare, deliberate baseline control. |
| `STOP` | Sets level to 0 immediately. | Explicit player request or immediate system halt. |

## Decay Model

`HIT` and `SET` preserve the current level for approximately 7 seconds. The firmware then decreases it by 1 every 50 ms until it reaches 0. Do not append `SET 0` or `STOP` to ordinary feedback actions.

`HIT` is additive. Examples from a resting level of 0:

| Command | Resulting level before the decay |
| --- | --- |
| `HIT 1` | 10 |
| `HIT 3` | 30 |
| `HIT 5` | 50 |
| `HIT 10` | 100 |
| `HIT 50` | 100, due to clamping |

The physical output remains device-dependent. A numerical level is not a promise of a particular perceived intensity.

## TCP Bridge Behavior

The bridge listens on `127.0.0.1:25363` by default and accepts one newline-terminated command per line. It keeps serial I/O on a background worker.

- `HIT` receives `QUEUED HIT <damage>` as soon as it enters the bridge queue. The ESP32 write happens later, so clients can continue without waiting for the hold or fade cycle.
- Other commands wait for the serial reply so health and diagnostic commands remain useful.
- A command must be at most 64 ASCII characters. The bridge does not expose its control port outside the local machine by default.
