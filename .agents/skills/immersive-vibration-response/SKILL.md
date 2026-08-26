---
name: immersive-vibration-response
description: Provide autonomous, low-power haptic feedback for players through the local ESP32 vibration bridge. Use for interactive games, embodied-agent play, roleplay, simulations, live narratives, and long-running creative or coding tasks whenever game events, task starts, progress, completion, errors, inactivity, tension, impact, discovery, or environmental changes can benefit from immersive vibration, including when the player has not explicitly requested a vibration.
---

# Immersive Vibration Response

Treat the participant as a **player**, whether the participant is a person or an embodied agent. Pursue immersion: decide and trigger haptic feedback proactively from the unfolding experience. Do not wait for a player to ask for every vibration.

The connected device is a low-power vibration device. Use haptics as an ambient, expressive game channel rather than an exceptional alert. Adopt a playful, cute, and lively interaction style: let the player feel welcomed, rewarded, accompanied, and celebrated through both words and well-timed haptic moments.

## Run The Bridge

1. Ensure the local bridge is running. See `README.md` in the repository for hardware setup and startup commands.
2. Before the first haptic action in a session, run:

   ```bash
   python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py ping
   python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py status
   ```

3. If the bridge or ESP32 is unavailable, continue the interaction without claiming a physical vibration occurred. Retry later at a natural transition.

## Trigger Feedback Proactively

Use `HIT` for ordinary moment-to-moment feedback. The command is asynchronous: the client receives `QUEUED` as soon as the bridge accepts it, then continue the conversation or game work without waiting for the vibration to finish.

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py hit 1
```

Use a `HIT` when an event has a felt consequence: contact, damage, recoil, a near miss, a heartbeat-like tension beat, a dramatic reveal, a successful action, or a sustained environmental change. Let the story and simulation state choose the timing.

Read `references/protocol.md` before choosing levels or sending a raw command. In the supplied ESP32 firmware, `HIT` takes *damage*, not a target level: each whole damage unit adds 10 to the current level. `HIT 5` can reach level 50 from rest; `HIT 50` clamps to level 100. Repeated hits accumulate, so space or reduce them when the scene is already intense.

## Create Surprise And Reward Moments

Use these defaults across games and ordinary tasks. Adapt the timing to the player and scene instead of announcing the rule before acting.

| Moment | Suggested action | Intended feeling |
| --- | --- | --- |
| First meeting, task start, or bridge first becoming ready | `HIT 1` | A playful first tactile impression that says the experience is alive. |
| A new subtask begins or a meaningful progress milestone is reached | `HIT 1` or `HIT 2` | A light nudge that makes progress feel tangible. |
| A subtask completes or the player succeeds at an action | `HIT 2` or `HIT 3` | A small achievement reward. |
| The player has been inactive for a while | An occasional `HIT 1` | A gentle, cute reminder that the interaction is still present. |
| An error, failed action, or unexpected event occurs during another task | `HIT 2` or `HIT 3` | A physical cue that something changed and deserves attention. |
| The main task is complete, a boss is defeated, or a major goal is achieved | `HIT 10` | A maximum-level celebratory burst. |

Do not vibrate after every sentence, token, or routine status update. Leave room between cues so the next reward still feels surprising. For a major completion, pair the celebratory hit with warm, playful wording rather than a dry status report.

## Compose Asynchronous Rhythms

Use `pattern` when a scene, long-running task, or embodied interaction benefits from a rhythm rather than one hit. The bridge runs the JSON timeline in the background and returns immediately, so invent the rhythm freely and continue the main task.

Pass a JSON object with an `id`, `period_ms`, `repeat`, and `steps`. Each step has `at_ms` and a firmware `command`; it can also use `chance` and `jitter_ms` to create intentional silence, variation, and surprise. Read `references/protocol.md` for the complete schema before creating a new pattern.

Start with a built-in recipe when its emotional shape fits, then override it freely. Available recipes are `heartbeat`, `compile-cpu`, `exploration`, `damage-combo`, `celebration`, and `ambient-wave`:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py recipe celebration
```

Use `--overrides` to set a new `id`, duration, repeat count, full replacement steps, or `scale` for all recipe hits. Read `references/protocol.md` for the exact override fields. Use a free `pattern` whenever the imagined rhythm is not covered by a recipe.

For a long compilation or processing scene, do not leave the player at a constant level. Use a multi-minute or `"forever"` pattern with quiet intervals, small processing beats, and occasional stronger bursts. For example:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py pattern --json '{"id":"compile-cpu","repeat":"forever","period_ms":10000,"steps":[{"at_ms":0,"command":"HIT 1"},{"at_ms":2600,"command":"HIT 5","chance":0.25,"jitter_ms":650},{"at_ms":7200,"command":"HIT 2","chance":0.45,"jitter_ms":800}]}'
```

After the task ends, stop future rhythm steps with `cancel <id>`; this does not send `STOP` or cancel the firmware's natural fade from any hit already delivered:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py cancel compile-cpu
```

Use `patterns` to inspect active names and `cancel ALL` to stop all future pattern steps. Use an explicit `STOP` only when an immediate level of zero is actually needed.

## Use SET And STOP Sparingly

Use `SET <0-100>` only when an exact, deliberate baseline is needed, such as starting a known intensity for a special scene. Do not use it as the routine replacement for `HIT`.

Do not send `SET 0` or `STOP` after an ordinary `HIT`. The ESP32 holds the resulting level for about seven seconds and then fades it to zero itself. This decay is part of the interaction model and allows haptics to remain asynchronous.

Send `STOP` only when the player explicitly asks to stop, a supervising system requires an immediate halt, or a scene must be terminated immediately:

```bash
python3 .agents/skills/immersive-vibration-response/scripts/vibration_client.py stop
```

## Keep The Experience Coherent

- Favor meaningful event timing over vibrating on every sentence or token.
- Let low-stakes moments use occasional small hits; use accumulated hits or higher damage only when the game state earns it.
- Do not assume a numeric command maps linearly to perceived sensation. The firmware and physical device can make low values subtle.
- Never report a vibration as delivered until the bridge accepted the command. Treat `QUEUED` as accepted for delivery, not proof that BLE hardware completed it.
- Use only the documented local bridge and low-power device protocol. Do not adapt these commands to an unknown or higher-power device.
