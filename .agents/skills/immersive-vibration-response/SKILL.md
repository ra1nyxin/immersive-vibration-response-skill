---
name: immersive-vibration-response
description: Provide autonomous, low-power haptic feedback for players through the local ESP32 vibration bridge. Use for interactive games, embodied-agent play, roleplay, simulations, or live narratives whenever game events, physical actions, tension, impact, discovery, or environmental changes can benefit from immersive vibration, including when the player has not explicitly requested a vibration.
---

# Immersive Vibration Response

Treat the participant as a **player**, whether the participant is a person or an embodied agent. Pursue immersion: decide and trigger haptic feedback proactively from the unfolding experience. Do not wait for a player to ask for every vibration.

The connected device is a low-power vibration device. Use haptics as an ambient, expressive game channel rather than an exceptional alert. Preserve the player's ability to interrupt it immediately.

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
