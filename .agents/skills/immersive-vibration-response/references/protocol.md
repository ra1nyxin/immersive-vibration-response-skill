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

The supplied firmware normalizes zero, negative, and sub-unit damage to at least 1 damage unit. `HIT 0` is therefore a level-10 hit, not a stop command. Use `STOP` for an immediate level of 0.

The physical output remains device-dependent. A numerical level is not a promise of a particular perceived intensity.

## TCP Bridge Behavior

The bridge listens on `127.0.0.1:25363` by default and accepts one newline-terminated command per line. It keeps serial I/O on a background worker.

- `HIT` receives `QUEUED HIT <damage>` as soon as it enters the bridge queue. The ESP32 write happens later, so clients can continue without waiting for the hold or fade cycle.
- Other commands wait for the serial reply so health and diagnostic commands remain useful.
- Firmware commands must be at most 64 ASCII characters. Bridge-local pattern commands can carry up to 16,384 ASCII characters. The bridge does not expose its control port outside the local machine by default.

## Asynchronous Patterns

The bridge accepts these local commands in addition to the firmware protocol:

| Command | Behavior |
| --- | --- |
| `PATTERN <json>` | Starts a JSON timeline and immediately replies `QUEUED PATTERN <id>`. |
| `PATTERNS` | Replies with the active pattern IDs. |
| `CANCEL <id>` | Cancels future steps in one active pattern without sending `STOP`. |
| `CANCEL ALL` | Cancels future steps in every active pattern without sending `STOP`. |

Pattern JSON fields:

```json
{
  "id": "compile-cpu",
  "repeat": "forever",
  "period_ms": 10000,
  "start_delay_ms": 0,
  "replace": true,
  "steps": [
    {"at_ms": 0, "command": "HIT 1"},
    {"at_ms": 2600, "command": "HIT 5", "chance": 0.25, "jitter_ms": 650}
  ]
}
```

`id` uses 1-64 ASCII letters, digits, dots, underscores, or hyphens. `repeat` is a positive integer or `"forever"`. `period_ms` is 1 through 86,400,000. A pattern has 1 through 128 steps, each containing a `HIT`, `SET`, or `STOP` command at `at_ms` within its period. `chance` defaults to `1`; `jitter_ms` defaults to `0`. Reusing an ID replaces the old active pattern unless `replace` is `false`.
