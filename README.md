# HomeKit Secure Video

[![CI](https://github.com/roquerodrigo/ha-homekit-secure-video/actions/workflows/ci.yml/badge.svg)](https://github.com/roquerodrigo/ha-homekit-secure-video/actions/workflows/ci.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

[![Open your Home Assistant instance and open the repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=roquerodrigo&repository=ha-homekit-secure-video&category=integration)

---

Custom [Home Assistant](https://www.home-assistant.io/) integration that publishes Home Assistant cameras to Apple HomeKit as accessories supporting **Secure Video** — motion-triggered recording processed on a HomeKit home hub and stored in iCloud, which the built-in `homekit` bridge does not offer.

> **Status: recording implemented, pending validation against a real home hub.** Each config entry publishes a HomeKit camera accessory that pairs with the Home app, serves live video and audio, and delivers motion-triggered Secure Video recordings. See [Roadmap](#roadmap).

Each entry publishes **one camera** as its own HomeKit accessory, with its own port and pairing code — cameras cannot be published behind a HomeKit bridge, which is why the built-in `homekit` integration also falls back to accessory mode for them.

## Installation

### HACS

1. In HACS, add this repository as a **custom repository** with category **Integration**.
2. Install **HomeKit Secure Video** and restart Home Assistant.

### Manual

Copy `custom_components/homekit_secure_video/` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Add the integration through **Settings → Devices & Services → Add Integration → HomeKit Secure Video**. Configuration is done entirely in the UI; there is no YAML.

Pick the camera to publish, the motion sensor to report to HomeKit, and whether to re-encode the video (see below). Only cameras that can serve a stream can be published. Repeat for each camera you want in the Home app.

**Link a motion sensor to get recordings.** Motion is the event Secure Video records on, so an entry without one publishes a camera the Home app will only stream, never record.

**Always report motion** records continuously instead: HomeKit is told the motion never stops, so it opens one recording after another. It ignores the motion sensor and uses considerably more iCloud storage.

Everything about an entry is edited in one place: **Reconfigure**, in the entry's three-dot menu. The camera, the motion trigger and the streaming limits all live there, and the pairing survives the change, so the accessory does not have to be added to the Home app again.

Every entry creates these entities:

| Entity | Purpose |
| --- | --- |
| `sensor` — Pairing code | The code to type into the Home app; empty once paired |
| `image` — Pairing QR code | Scan it with the Home app to pair |
| `binary_sensor` — Paired | Whether a HomeKit controller is paired |
| `button` — Reset pairing | Drops every pairing and regenerates the code |
| `sensor` — HomeKit camera mode | Off / Detect activity / Stream / Stream and allow recording |
| `binary_sensor` — Recording | Whether a clip is being delivered to the home hub right now |
| `sensor` — Last recording | When the last clip finished being delivered |

**Re-encode video** is offered when adding a camera and can be changed later under **Streaming options**; it is stored as an option either way, and defaults to on.

With it on, the video is re-encoded to exactly what HomeKit negotiates — profile, level, resolution and frame rate. This is what makes cameras work whose own stream HomeKit will not take, and it costs about one CPU core per 1080p camera.

With it off, the camera's stream is passed through untouched apart from rewriting an over-spec H.264 level in the stream header, which needs no re-encoding. Two cameras cost about a tenth of a core this way. It requires a camera that already sends a resolution HomeKit was offered — a camera's secondary stream usually does, and pointing the entry at one is the cheapest way to run.

The **maximum width, height and frame rate** cap what the accessory offers to HomeKit, for the live stream and for recordings alike.

**Include audio** sends the camera's own audio to HomeKit as Opus alongside the video. Opus is the only codec offered: AAC-ELD needs an ffmpeg built with `libfdk_aac`, which Home Assistant's is not. Cameras that send no audio are unaffected.

Repairs are raised under **Settings → Repairs** when the probed camera cannot be served as configured — no stream source, a codec other than H.264, or a picture larger than HomeKit was offered while re-encoding is off. Each one clears itself once the cause is gone.

## Roadmap

- [x] Camera selection in the config flow, one camera per entry.
- [x] A HomeKit accessory per entry, with Camera RTP Stream Management, live video over SRTP, snapshots and a linked motion sensor.
- [x] Pairing code and QR code exposed as entities.
- [x] HomeKit Data Stream transport (the encrypted channel Secure Video records over).
- [x] Camera Recording Management and Camera Operating Mode services, with the negotiated recording configuration.
- [x] Fragmented MP4 pipeline: prebuffer, motion-triggered clips, delivery to the home hub.
- [x] Live audio (Opus over SRTP).
- [x] Recording entities, repair issues and recording diagnostics.
- [ ] Register the brand assets in [home-assistant/brands](https://github.com/home-assistant/brands).

Recording requires an Apple home hub (HomePod or Apple TV) and an iCloud+ plan with a free camera slot; without them the Home app never offers "Stream & Allow Recording".

## Development

```bash
scripts/setup                                              # create .venv and install deps (uv sync)
scripts/develop                                            # start Home Assistant in debug mode with the integration loaded
scripts/lint                                               # ruff format + ruff check + mypy + pytest
uv run ruff format --check .                               # check formatting
uv run ruff check .                                        # lint
uv run mypy custom_components/homekit_secure_video         # type-check
uv run pytest                                              # run tests with the 90 % coverage gate
```

Both scripts run through `uv`, which manages `./.venv` automatically — no `source .venv/bin/activate` needed. For ad-hoc commands, prefix with `uv run`.

Home Assistant runs with config in `config/` and `PYTHONPATH` pointing at `custom_components/` — no symlinks. To recreate entity/device IDs during development:

```bash
rm config/.storage/core.entity_registry config/.storage/core.device_registry
```

Conventions for contributors live in [`CODE_STYLE.md`](./CODE_STYLE.md); architectural notes for AI agents in [`CLAUDE.md`](./CLAUDE.md).

### Pre-commit hooks

Install once per clone (after `scripts/setup`):

```bash
pre-commit install
```

This wires ruff + basic file hygiene checks (`.pre-commit-config.yaml`) into every commit, mirroring the CI lint job.

## Layout

```
custom_components/homekit_secure_video/
├── __init__.py        # async_setup_entry / unload / reload / remove
├── accessory/         # the HomeKit accessory layer
│   ├── __init__.py
│   ├── camera_accessory.py  # pyhap Camera: streams, snapshots, motion
│   ├── camera_operating_mode.py  # CameraOperatingMode service
│   ├── data_stream_transport.py  # DataStreamTransportManagement service
│   ├── driver.py            # AccessoryDriver reporting pairing changes
│   ├── hap_server.py        # HAP server retaining each session's shared key
│   ├── manager.py           # publishes, stops and re-publishes the accessory
│   ├── recording_management.py   # CameraRecordingManagement service
│   └── setup_data_stream_transport_characteristic.py
├── binary_sensor.py   # "Paired" and "Recording"
├── brand/             # brand assets (icon, logo, svg)
├── button.py          # "Reset pairing"
├── config_flow.py     # camera selection + port reservation; reconfigure step
├── const.py           # DOMAIN, LOGGER, config keys, port range, resolutions
├── coordinator.py     # push-only coordinator fed by the accessory
├── data/              # one TypedDict/dataclass per file; type aliases in __init__.py
│   ├── __init__.py    # type aliases (ConfigEntry, Json*) + re-exports
│   ├── accessory_status.py
│   ├── camera_options.py
│   ├── config_data.py
│   ├── diagnostics_entry.py
│   ├── diagnostics_payload.py
│   ├── options_data.py
│   ├── recording_diagnostics.py
│   ├── recording_statistics.py
│   ├── runtime.py     # HomeKitSecureVideoData dataclass
│   ├── stream_request.py
│   └── stream_session_info.py
├── datastream/        # HomeKit Data Stream transport
│   ├── __init__.py
│   ├── connection.py        # one TCP connection and its handshake
│   ├── constants.py         # wire constants of the protocol
│   ├── frame.py             # framing
│   ├── frame_codec.py       # ChaCha20-Poly1305 per direction
│   ├── message.py           # header + body of one message
│   ├── opack.py             # Apple's binary format
│   ├── prepared_session.py
│   ├── server.py            # accepts the controller's connection
│   └── session_keys.py      # HKDF-SHA512 session keys
├── diagnostics.py     # downloadable diagnostics with pairing-secret redaction
├── entity.py          # base CoordinatorEntity
├── exceptions/        # one file per exception class
│   ├── __init__.py
│   ├── data_stream_error.py
│   └── opack_error.py
├── icons.json         # entity icons keyed by translation_key
├── image.py           # pairing QR code
├── issues.py          # repair issues raised from the camera source probe
├── manifest.json
├── recording/         # HomeKit Secure Video recording
│   ├── __init__.py
│   ├── audio_probe.py            # does the camera carry audio?
│   ├── constants.py              # wire constants of the recording services
│   ├── ffmpeg_recording_command.py
│   ├── fragmented_mp4.py         # ftyp/moov and moof/mdat
│   ├── prebuffer.py              # the seconds before the trigger
│   ├── recorder.py               # the persistent ffmpeg
│   ├── recording_session.py      # the dataSend delivery
│   ├── selected_configuration.py
│   └── supported_configuration.py
├── sensor/            # one class per sensor
│   ├── __init__.py
│   ├── camera_mode.py
│   ├── last_recording.py
│   └── pairing_code.py
├── streaming_options.py  # the streaming fields of the config flow
├── streaming/         # live SRTP streaming
│   ├── __init__.py
│   ├── live_stream_command.py   # ffmpeg arguments, video and Opus audio
│   └── live_stream_session.py   # the running ffmpeg process
└── translations/
    ├── en.json
    └── pt-BR.json
```

Layout convention (one top-level class per file; related classes grouped under a directory) is documented in [`CODE_STYLE.md`](./CODE_STYLE.md).

## CI

All workflows call the reusable workflows in [`roquerodrigo/workflows`](https://github.com/roquerodrigo/workflows):

- **`ci.yml`** — ruff (check + format) + mypy, pytest with the coverage gate, and `hassfest` + HACS validation; push/PR to `main`
- **`codeql.yml`** — GitHub CodeQL security scan; push/PR to `main` and a weekly cron
- **`release.yml`** — release-please, gated on a green CI run on `main`
- **`auto-assign.yml`** — assigns new issues/PRs to the code owner

## Trademark

Apple, HomeKit and the HomeKit logo are trademarks of Apple Inc. This project is not affiliated with, endorsed by, or sponsored by Apple Inc.

## License

[MIT](LICENSE)
