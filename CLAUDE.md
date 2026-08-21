# CLAUDE.md

Guidance for Claude Code (claude.ai/code) agents working in this repository.

## Always read `CODE_STYLE.md` first

Before creating, renaming or restructuring any file/class/function, **read [`CODE_STYLE.md`](./CODE_STYLE.md)**. It is the single source of truth for conventions: language, file organisation, naming, typing, properties vs `__init__`, imports, docstrings, comments, coordinator pattern, repairs/diagnostics layout, translations, lint workflow.

For user-facing topics (installation, roadmap, layout diagram, useful commands, CI list), see [`README.md`](./README.md).

This file deliberately avoids restating those rules — it only adds:

1. The verification workflow agents must run after every change.
2. The architectural reasoning that is not obvious from `CODE_STYLE.md` alone.
3. What is implemented here and what is still missing.

## Project status

Each config entry publishes one Home Assistant camera as a standalone HomeKit accessory: it pairs with the Home app, serves live video and audio over SRTP, answers snapshot requests and reports a motion trigger.

**Secure Video recording is implemented** end to end: the accessory publishes `CameraRecordingManagement`, `CameraOperatingMode` and `DataStreamTransportManagement`, negotiates a recording configuration, keeps a prebuffer of fragmented MP4, and delivers recordings over the `dataSend` protocol when the motion trigger fires.

Recording can only be exercised against a real Apple home hub (HomePod or Apple TV) with an iCloud+ plan that has a free camera slot; without one the Home app never offers "Stream & Allow Recording". Everything below the hub is covered by tests: `tests/test_data_stream_server.py` drives the transport from a simulated controller and `tests/test_recording_session.py` drives a full `dataSend` delivery.

Protocol references worth keeping at hand: `homebridge/HAP-NodeJS` (`src/lib/datastream/`, `src/lib/camera/RecordingManagement.ts`), `bauer-andreas/secure-video-specification`, and `koush/scrypted` (`plugins/homekit/src/types/camera/camera-recording.ts`).

Testing recording end to end needs an Apple home hub (HomePod or Apple TV) and an iCloud+ plan with a free camera slot — without them the Home app never offers "Stream & Allow Recording".

## Verification workflow

**After every code change, always run lint then tests, in that order, before declaring the task done. Either run `scripts/lint` (a thin wrapper that only chains the four commands) or run them directly:**

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy custom_components/homekit_secure_video
uv run pytest
```

- Lint runs `ruff format`, `ruff check` and `mypy` — all configured in `pyproject.toml`. Fix any failure and re-run before moving on.
- `pytest` enforces a **90 % coverage gate** (`--cov-fail-under` in `pyproject.toml`).

Both gates mirror CI (`.github/workflows/ci.yml`). Skip this only when the change literally cannot affect lint or tests (e.g., README-only edits).

## Bumping the Home Assistant version

The Home Assistant version is pinned in two places and **must be updated together**, otherwise CI, HACS and the test harness drift apart:

1. `pyproject.toml` `[dependency-groups] dev` — `homeassistant==<X.Y.Z>` (runtime/CI lint + mypy) **and** `pytest-homeassistant-custom-component==<matching release>` (the test harness ships its own pinned `homeassistant`; the two pins must come from the same HA release, otherwise lint and tests resolve different cores).
2. `hacs.json` — `"homeassistant": "<X.Y.Z>"` (minimum HA core enforced by HACS).

Verify the pairing on PyPI before committing: the `requires_dist` of `pytest-homeassistant-custom-component` must list the same `homeassistant==<X.Y.Z>` you pinned in `pyproject.toml`.

## Architecture

```
config_flow.py        → picks the camera, reserves a HAP port, creates the ConfigEntry
__init__.py           → builds the accessory manager + coordinator, starts the accessory
accessory/manager.py  → owns the pyhap driver/accessory lifecycle; reports status changes
accessory/camera_accessory.py → the HAP camera: streams, snapshots, motion
coordinator.py        → holds the accessory status; entities read it
```

### One accessory per entry, never a bridge

HomeKit does not accept cameras behind a bridge, so each entry runs its own `AccessoryDriver` in accessory mode, on its own port, with its own pairing code and mDNS advertisement. The core `homekit` integration reaches the same conclusion for cameras. `config_flow` reserves the lowest port in `FIRST_HAP_PORT..LAST_HAP_PORT` that no other entry holds and that binds cleanly, and stores it in `entry.data`.

### Nothing is polled

The accessory is local and pushes its own changes, so the coordinator runs with `update_interval=None`. `HomeKitSecureVideoAccessoryManager` keeps a list of status listeners; `HomeKitSecureVideoAccessoryDriver` fires them on pair/unpair and the camera accessory fires them when a stream starts or stops. The coordinator's listener calls `async_set_updated_data`. `_async_update_data` still exists so `async_config_entry_first_refresh` has something to read at setup — it returns the manager's current status.

### Pairing state on disk

`pyhap` persists the accessory's key material itself. The file lives at `.storage/homekit_secure_video.<entry_id>.state`, mirroring what the core `homekit` integration does. `async_remove_entry` deletes it, and the "Reset pairing" button stops the accessory, deletes the file and starts it again, which regenerates the pairing code.

### What runs in the executor

`AccessoryDriver.__init__` builds a `pyhap` `Loader` that reads JSON off disk, and `add_accessory` reads or writes the persist file. Both go through `async_add_executor_job`; the rest of the lifecycle is async.

### Entry typing

The `data/` package holds one TypedDict/dataclass per file. `data/__init__.py` defines the `type` aliases — `HomeKitSecureVideoConfigEntry = ConfigEntry[HomeKitSecureVideoData]`, `JsonPrimitive`/`JsonValue`/`JsonObject` — and re-exports every symbol, so consumers still `from .data import …`. The `HomeKitSecureVideoData(accessory_manager, coordinator, integration)` dataclass lives in `data/runtime.py`. State lives on `entry.runtime_data` (auto-discarded on unload), never on `hass.data`.

`pyhap` hands us permissive dicts at two boundaries — the negotiated stream configuration and the stream session. Both are `cast` to TypedDicts (`HomeKitSecureVideoStreamRequest`, `HomeKitSecureVideoStreamSessionInfo`) where they arrive, never spread as `Any`.

### Config flow surface

- `async_step_user` — camera selection; rejects a camera without `CameraEntityFeature.STREAM`, sets unique_id from the camera entity id (which is what enforces one camera per entry), reserves the port.
- `async_step_reconfigure` — change the camera, the motion trigger **and the streaming options** without deleting the entry. Changing the camera moves the entry's unique id with it and keeps the port and pairing, so the accessory does not have to be added to the Home app again; a camera another entry already publishes is rejected on the field. The motion sensor is offered as a `suggested_value`, never a `default` — a default is re-applied on submit, which makes the field impossible to clear.
- `async_get_options_flow` — returns `HomeKitSecureVideoOptionsFlow` from `options_flow.py` (one class per file).

### Options flow

`streaming_options.py` owns the schema fields for `max_width`, `max_height`, `max_fps`, `reencode` and `stream_audio`, plus `as_numbers` (the dropdowns hand back strings) and `STREAMING_OPTION_KEYS`. Both `options_flow.py` and the reconfigure step build from it, so the two screens never drift apart; the reconfigure step splits its submission on `STREAMING_OPTION_KEYS` and writes those to `entry.options` and the rest to `entry.data`. The caps filter `SUPPORTED_RESOLUTIONS` before it is advertised to HomeKit. Changing any of them triggers `async_reload_entry`, which republishes the accessory.

### Live streaming

`camera_accessory.start_stream` resolves the RTSP URL through `camera.async_get_stream_source` and hands it to `streaming/`. The ffmpeg command **copies** the source H.264 rather than transcoding — a Raspberry Pi cannot re-encode a 2K stream in real time, and HomeKit accepts every profile we advertise. Video codec profiles and levels must be passed to `pyhap` as the `bytes` values from `pyhap.camera.VIDEO_CODEC_PARAM_*_TYPES`; plain ints blow up inside `pyhap.tlv.encode`.

Live audio is a **second output of the same ffmpeg process**, on the port and SRTP key HomeKit negotiates separately from video, encoded with `libopus` at the negotiated sample rate, bitrate, channel count and packet time. It is emitted only when the probed source actually has an audio track and HomeKit picked Opus — mapping a track that is not there makes ffmpeg refuse to start.

**Only Opus is advertised.** The Home Assistant ffmpeg build has no `libfdk_aac`, and the native `aac` encoder cannot produce AAC-ELD, so offering AAC-ELD would let HomeKit negotiate a codec this integration cannot encode.

### HomeKit Data Stream

`datastream/` is a from-scratch implementation of the transport HAP-python does not have. The pieces, in the order a session goes through them:

- `accessory/data_stream_transport.py` handles the `SetupDataStreamTransport` write: it validates the request, derives the session keys and answers with the listening port plus the accessory's key salt. A later *read* of that characteristic deliberately omits the salt.
- `session_keys.py` derives both directions with HKDF-SHA512 over the HAP session secret, salted with `controller_salt + accessory_salt` and separated by the info strings `HDS-Read-Encryption-Key` / `HDS-Write-Encryption-Key`.
- `frame.py` / `frame_codec.py` frame the wire: `type(1) || length(3, big-endian)` as the AAD, ChaCha20-Poly1305, 16-byte tag, and a per-direction little-endian nonce counter. **A failed decryption must not advance the nonce** — that is what lets an unidentified connection try the same frame against every prepared session.
- `opack.py` is Apple's binary format. Its decoder resolves back-references (tags 0xA0-0xCF) by index into every scalar seen so far; the encoder never emits them, because HAP-NodeJS's writer and reader disagree on whether booleans count toward that index.
- `connection.py` / `server.py` accept the TCP connection, identify which prepared session it belongs to, require `control`/`hello` as the first message and route the rest to handlers registered per protocol and topic.

Two things that will bite whoever touches this:

- **Bind the data stream server to one address.** Left to itself `create_server(port=0)` opens one socket per address family, each on a *different* ephemeral port, and the port handed to the controller matches only one of them.
- **`prepare_session` is synchronous.** HAP-python calls characteristic setters synchronously and expects the write response from the same call, so the listening socket has to already exist.

### Recording

`recording/` holds everything below the HomeKit services:

- `supported_configuration.py` builds the three "supported" TLVs; `selected_configuration.py` parses the one HomeKit writes back. That parser is fed straight from the wire, so it turns pyhap's unchecked `IndexError` into a reportable error.
- `recorder.py` runs one persistent ffmpeg while recording is enabled, feeding `prebuffer.py` — the seconds *before* a trigger, which is the whole point of Secure Video. The window keeps 2.5× what HomeKit negotiated, because fragments keep arriving while an earlier recording is still being delivered.
- `fragmented_mp4.py` splits ffmpeg's output into the `ftyp`+`moov` initialization segment and the `moof`+`mdat` fragments. A trailing `mfra` box only exists when the input was a file; live sources never produce one.
- `recording_session.py` implements `dataSend`: it answers `open`, streams the initialization segment, the prebuffer and then live fragments in ≤262144-byte chunks, and marks the last one with `endOfStream`. The **end of the motion** is what ends a clip — the hub holds the stream open until a fragment says it is the last.

**HAP-python does not give a standalone accessory everything HAP requires.** Two pieces have to be added by hand, and their absence is invisible in the logs — the controller simply treats the accessory as incomplete and refuses to configure it:

- **`ProtocolInformation` (service `A2`) with `Version` = `1.1.0`.** HAP-python has no definition for it at all; it only ever appears inside bridges. Built by hand in `_protocol_information_service`.
- **`Active` on every `CameraRTPStreamManagement`.** HAP-python's `Camera` omits it.

Both were found by diffing our accessory against a working one (see below). Note that a characteristic added to a service *after* HAP-python registered that service gets neither a broker nor an iid — `_add_active_to_stream_managements` wires both by hand, and forgetting that makes `to_HAP` raise.

**When stuck, diff against a working accessory instead of guessing.** `Controller` from `aiohomekit` (already in Home Assistant) pairs with any unpaired accessory and dumps its full description; comparing services and characteristics against ours turned a long guessing streak into three concrete findings in one pass. The accessory has to be unpaired first, and the dump script should remove its own pairing afterwards.

**Reading `SelectedCameraRecordingConfiguration` before one is negotiated must FAIL.** Answering an empty value with a success status tells the controller a configuration is already in place — an empty one — so it never writes the one it was about to select, and the Home app reports the generic settings error. The reference implementation throws `SERVICE_COMMUNICATION_FAILURE` there, which is also what HAP-python answers when a getter raises.

**Offer HomeKit little, not much.** The controller picks one configuration out of what the accessory advertises, and it fails to pick at all when offered too many: recording advertises exactly two resolutions (`RECORDING_RESOLUTIONS`) and a single audio sample rate, matching what Scrypted narrowed its own offer to. A too-wide offer surfaces in the Home app as a generic "error updating this setting" on **any** mode change — not just recording — with every HAP write answered `204 No Content`, so the log gives no hint.

**Whatever follows `HomeKitCameraActive` must follow it in both directions.** The linked motion sensor's `StatusActive` mirrors it; updating that only when the camera is switched *off* leaves the sensor inactive forever, and HomeKit then refuses to switch the camera back on — it writes the new mode, waits about 13 seconds for the accessory to look usable, and reverts. Same generic Home app error, same silent HAP log.

**`FirmwareRevision` must be set and shaped like `x[.y[.z]]`.** HAP-python leaves it empty unless `set_info_service` is given one, and a controller then re-reads it in a loop and refuses to apply settings to the accessory — same symptom, same silent log.

**The video is re-encoded, not copied — unless the `reencode` option says otherwise.** Copying is far cheaper, and it was the original design, but it hands HomeKit whatever the camera happens to send: the cameras this was built against ship H.264 level 4.1 and 5.1 at 20 fps, and one of them at 2880x1616 — none of which HomeKit accepts, and all of which it had just negotiated something else for. `libx264 -preset ultrafast` re-encodes 1080p in real time at roughly one core on a Raspberry Pi 5, against a tenth of a core for two cameras in copy mode; `RECORDING_RESOLUTIONS` and the negotiated frame rate keep that bounded. Rewriting only the level in the SPS (`-bsf:v h264_metadata=level=4`) works and costs nothing, but it fixes just one of the three mismatches.

Three things that will bite whoever touches the ffmpeg side:

- **Recording keyframes must land on fragment boundaries.** Every fragment has to open on one, so `-g` and `-force_key_frames` are both set from the negotiated fragment length. Leaving it to `frag_keyframe` alone means fragments as long as the camera's own GOP.
- **The movflag is `default_base_moof`**, not `default_base_is_moof`. The wrong spelling is in a lot of prior art; ffmpeg rejects it outright and nothing records.
- **`-shortest` is not optional.** The silent audio track is generated by `anullsrc`, which never ends: without it a dead camera leaves ffmpeg alive forever, emitting fragments that carry nothing but silence.
- **HomeKit will not play a recording without an audio track.** `audio_probe.py` asks ffprobe whether the camera has one, because mapping a track that is not there makes ffmpeg refuse to start.

### The `/pairings` guard

`accessory/hap_server.py` also replaces HAP-python's request handler for one
method. `HAPServerHandler.handle_pairings` asserts that the connection has been
verified *one line above* the check written to reject it, so a controller
asking to add a pairing on an unverified connection gets a `500` instead of the
authentication error the spec calls for. iOS then abandons adding the **home
hub** — and Secure Video recording only ever runs through a hub, so the Home
app reports the camera as unconfigurable with no failing HAP write in sight.
Worth reporting upstream; the override is faithful to what the pyhap code
plainly intends.

### Pairing identity is ours, not HAP-python's

`pyhap` regenerates `pincode` and `setup_id` on every start — it persists the key material and the paired clients, but not those two. Since this integration publishes the code and the QR code as *entities*, they are generated once in the config flow, stored on the config entry and fed back into the driver on every start. `async_migrate_entry` backfills entries created before this existed.

### Diagnostics

`diagnostics.py` returns `HomeKitSecureVideoDiagnosticsPayload`. `pairing_code`/`setup_uri` are redacted via `async_redact_data` (driven by `TO_REDACT: frozenset[str]`) — both are enough to pair with the accessory. `.github/ISSUE_TEMPLATE/bug.yml` asks users to attach the dump.

Besides the entry and the accessory status, the dump carries the `recording` block: what HomeKit negotiated (`selected_configuration`, rendered field by field), how many recordings have been started, what the last session delivered (`fragments_sent`/`bytes_sent`) and the recorder's own state, prebuffer included. **Never let a `MagicMock` reach it in tests** — the diagnostics view serialises the payload as JSON and a mock hangs there rather than failing.

### Repair issues

`issues.py` re-evaluates three issues on every start, from what the source probe found, and withdraws each one as soon as it stops applying: `no_stream_source`, `unsupported_codec` (anything other than H.264) and `oversized_source` (a picture larger than the largest offered resolution, raised **only while copying** — re-encoding scales it down). They are informational, so nothing implements `RepairsFlow`; the module is deliberately not named `repairs.py`, which is the platform Home Assistant loads for fixable issues.
