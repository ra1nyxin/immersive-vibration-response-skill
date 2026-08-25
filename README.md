# Immersive Vibration Response

`immersive-vibration-response` is a Codex skill for low-power player haptic feedback in interactive games, embodied-agent games, simulations, and live narratives. In this project, the participant is always called the **player**, whether that participant is a person or an embodied agent.

This project pursues immersion. Once the skill is installed and the bridge is available, an AI agent is instructed to trigger vibration proactively from game state and narrative events. It does not need to wait for the player to request a vibration. Agents can send a `HIT` and immediately continue their conversation or other tasks while the bridge delivers it in the background.

Install this project only if autonomous, event-driven haptic feedback matches the experience you want to build. The agent still follows its host platform's permissions and policies, and a player can request an immediate stop at any time.

## Hardware And Software

Prepare the following:

- A host computer that runs Codex and the local bridge.
- An ESP32-S3 with firmware compatible with the command protocol in [protocol.md](.agents/skills/immersive-vibration-response/references/protocol.md).
- A USB data cable between the host and ESP32-S3.
- The compatible low-power vibration massage device paired with the ESP32 firmware. The supplied firmware searches for BLE device name `GK36` and uses service `0x1000` and write characteristic `0x1001`.
- Python 3.10 or newer and permission to access the USB serial port.

The skill is designed for the low-power device and firmware described here. Do not direct this bridge protocol at an unknown device or higher-power equipment.

## Install

Clone or place this repository in the project that will use the skill. Codex discovers the repository skill at:

```text
.agents/skills/immersive-vibration-response/
```

The Python bridge and client support Debian, Ubuntu, and Windows. Create a Python environment and install the bridge dependency:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

On Windows PowerShell, activate it with:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Debian or Ubuntu, the serial permission command below is normally the only platform-specific setup required.

Connect the ESP32 and identify its serial port. Typical values are `/dev/ttyACM0` or `/dev/ttyUSB0` on Linux, and `COM3` on Windows. On Linux, grant the signed-in account serial access if required:

```bash
sudo usermod -a -G dialout "$USER"
```

Sign out and back in after changing the group.

Start the bridge in a dedicated terminal. It listens only on `127.0.0.1:25363` by default:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/esp32_bridge.py \
  --serial-port /dev/ttyACM0
```

Windows example:

```powershell
python .agents/skills/immersive-vibration-response/scripts/esp32_bridge.py --serial-port COM3
```

Verify the path in a second terminal:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py ping
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py status
```

Expected responses include `PONG` and a `STATUS ...` line. If the skill does not appear in Codex after creating or updating it, restart Codex.

## Autonomous Haptic Behavior

The skill treats haptics as part of the player's game world. It can initiate feedback for impacts, near misses, action success, discoveries, environmental shifts, rising tension, and other meaningful moments without asking the player first.

The agent's intended style is playful, cute, and lively. Haptics can turn an ordinary interaction into a small shared event: a first hello can leave a tactile impression, a completed subtask can feel like a reward, and a finished project can be celebrated rather than merely reported.

### Example Trigger Scenes

| Scene | Example haptic action | Experience goal |
| --- | --- | --- |
| First meeting, task launch, or first ready bridge | `hit 1` | Establish a friendly first tactile impression. |
| Meaningful task milestone or a new subtask | `hit 1` or `hit 2` | Let the player feel progress rather than only read it. |
| A subtask completes or an in-game action succeeds | `hit 2` or `hit 3` | Add a compact achievement reward. |
| The player has been inactive for a while | An occasional `hit 1` | Give a gentle, playful reminder that the experience is waiting. |
| An error or unexpected failure occurs while another task is running | `hit 2` or `hit 3` | Make the change in state physically noticeable. |
| The main task is complete or a major goal is achieved | `hit 10` | Celebrate at the firmware's maximum level. |

These are defaults, not a soundtrack for every line of text. Avoid vibrating after every sentence or routine update, so progress cues and celebrations retain their surprise-reward effect.

Use `HIT` for normal feedback:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py hit 1
```

The bridge answers `QUEUED HIT 1` immediately. It does not wait for the ESP32 hold period or fade. That lets an AI agent send a haptic cue in the middle of a response and continue the scene naturally.

The ESP32 firmware interprets `HIT` as additive **damage**, not direct intensity. Each rounded damage unit adds 10 to the current level, up to 100. From rest, `HIT 1`, `HIT 3`, and `HIT 5` lead to levels 10, 30, and 50 respectively; `HIT 10` and `HIT 50` both clamp to 100. Perceived output depends on the physical device, so a number is not a guarantee of how prominent the vibration feels.

Use `SET <0-100>` only for the uncommon case where a scene needs an exact baseline level:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py set 45
```

Do not habitually send `STOP` or `SET 0` after a `HIT`. The ESP32 holds its current level for about seven seconds and then fades it down automatically. Send `STOP` only when a player requests it, a supervising system needs an immediate halt, or the scene must end instantly:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py stop
```

## Troubleshooting

- `ERR serial: pyserial is required`: activate the environment and install `requirements.txt`.
- `ERR serial: ... permission denied`: check the Linux serial group or run the bridge with an account allowed to access the specified port.
- `STATUS` shows `connected=0`: confirm the vibration device is powered, paired as `GK36`, and in Bluetooth range; run `scan` to request a new scan.
- `connection refused`: start `esp32_bridge.py` and keep it running in a separate terminal.
- `QUEUED HIT ...` means the bridge accepted the action. Check bridge logs and `status` if the physical device does not react.

## Repository Layout

```text
.agents/skills/immersive-vibration-response/
  SKILL.md                 Codex workflow and autonomous trigger guidance
  scripts/esp32_bridge.py Local asynchronous TCP-to-serial bridge
  scripts/vibration_client.py Command client for agents and manual checks
  references/protocol.md   ESP32 command semantics and decay model
requirements.txt           Python dependency for serial communication
```
