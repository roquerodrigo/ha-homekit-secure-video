# CLAUDE.md

Guidance for Claude Code (claude.ai/code) agents working in this repository.

## Always read `CODE_STYLE.md` first

Before creating, renaming or restructuring any file/class/function, **read [`CODE_STYLE.md`](./CODE_STYLE.md)**. It is the single source of truth for conventions: language, file organisation, naming, typing, properties vs `__init__`, imports, docstrings, comments, coordinator pattern, repairs/diagnostics layout, translations, lint workflow.

For user-facing topics (installation, roadmap, layout diagram, useful commands, CI list), see [`README.md`](./README.md).

This file adds only the verification workflow, the architectural reasoning that is not obvious from `CODE_STYLE.md`, and what is and is not implemented.

## Project status

Each config entry publishes one Home Assistant camera as a standalone HomeKit accessory: it pairs with the Home app, serves live video and audio over SRTP, answers snapshot requests and reports a motion trigger.

**Secure Video recording is implemented** end to end: the accessory publishes `CameraRecordingManagement`, `CameraOperatingMode` and `DataStreamTransportManagement`, negotiates a recording configuration, keeps a prebuffer of fragmented MP4, and delivers recordings over the `dataSend` protocol when the motion trigger fires.

Recording can only be exercised against a real Apple home hub (HomePod or Apple TV) with an iCloud+ plan that has a free camera slot; without one the Home app never offers "Stream & Allow Recording". Everything below the hub is covered by tests: `tests/test_data_stream_server.py` drives the transport from a simulated controller and `tests/test_recording_session.py` drives a full `dataSend` delivery.

Protocol references worth keeping at hand: `homebridge/HAP-NodeJS` (`src/lib/datastream/`, `src/lib/camera/RecordingManagement.ts`), `bauer-andreas/secure-video-specification`, and `koush/scrypted` (`plugins/homekit/src/types/camera/camera-recording.ts`).

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

### One accessory per entry, never a bridge

HomeKit does not accept cameras behind a bridge, so each entry runs its own `AccessoryDriver` in accessory mode, on its own port, with its own pairing code and mDNS advertisement. The core `homekit` integration reaches the same conclusion for cameras. `config_flow` reserves the lowest port in `FIRST_HAP_PORT..LAST_HAP_PORT` that no other entry holds and that binds cleanly, and stores it in `entry.data`.

### Nothing is polled

The accessory is local and pushes its own changes, so the coordinator runs with `update_interval=None`. `HomeKitSecureVideoAccessoryManager` keeps a list of status listeners; `HomeKitSecureVideoAccessoryDriver` fires them on pair/unpair and the camera accessory fires them when a stream starts or stops. The coordinator's listener calls `async_set_updated_data`. `_async_update_data` still exists so `async_config_entry_first_refresh` has something to read at setup — it returns the manager's current status.

### Pairing state on disk

`pyhap` persists the accessory's key material itself. The file lives at `.storage/homekit_secure_video.<entry_id>.state`, mirroring what the core `homekit` integration does. `async_remove_entry` deletes it, and the "Reset pairing" button stops the accessory, deletes the file and starts it again, which regenerates the pairing code.

### Nothing acquired before a failure survives it

`async_start` takes a listening socket for the data stream and then the reserved HAP port, and the step between them — probing the configured camera — raises `ConfigEntryNotReady` whenever the camera's own integration has not come up yet, which on a restart is routine. **Home Assistant does not call `async_unload_entry` for an entry that never reached `LOADED`**, so nothing releases what a failed attempt took: every retry leaked another listening socket, and the reserved port stayed held until a restart. Two things keep that from coming back — `async_start` stops the manager before re-raising, and `async_setup_entry` registers `entry.async_on_unload(accessory_manager.async_stop)` *before* starting, which is the hook Home Assistant runs in the failed-setup path.

The same shape applies inside the accessory. Recorder work runs on tasks the accessory keeps and cancels in `stop()`, and a stopped accessory starts no recorder: resolving the stream source and probing its audio are both long awaits that sit *before* ffmpeg is spawned, so a task suspended there would otherwise resume after the accessory was dropped and spawn a process nothing owns.

### What runs in the executor

`AccessoryDriver.__init__` builds a `pyhap` `Loader` that reads JSON off disk, and `add_accessory` reads or writes the persist file. Both go through `async_add_executor_job`; the rest of the lifecycle is async.

### Entry typing

The `data/` package holds one TypedDict/dataclass per file. `data/__init__.py` defines the `type` aliases — `HomeKitSecureVideoConfigEntry = ConfigEntry[HomeKitSecureVideoData]`, `JsonPrimitive`/`JsonValue`/`JsonObject` — and re-exports every symbol, so consumers still `from .data import …`. The `HomeKitSecureVideoData(accessory_manager, coordinator, integration)` dataclass lives in `data/runtime.py`. State lives on `entry.runtime_data` (auto-discarded on unload), never on `hass.data`.

`pyhap` hands us permissive dicts at two boundaries — the negotiated stream configuration and the stream session. Both are `cast` to TypedDicts (`HomeKitSecureVideoStreamRequest`, `HomeKitSecureVideoStreamSessionInfo`) where they arrive, never spread as `Any`.

### Config flow surface

- `async_step_user` — camera selection; rejects a camera without `CameraEntityFeature.STREAM`, sets unique_id from the camera entity id (which is what enforces one camera per entry), reserves the port.
- `async_step_reconfigure` — the only editor an entry has: camera, motion trigger and streaming options together. Changing the camera moves the entry's unique id with it and keeps the port and pairing, so the accessory does not have to be added to the Home app again; a camera another entry already publishes is rejected on the field. The motion sensor is offered as a `suggested_value`, never a `default` — a default is re-applied on submit, which makes the field impossible to clear.

### One editor, no options flow

**There is deliberately no options flow.** Two screens for one entry — "Configure" holding the streaming knobs and "Reconfigure" holding the camera — is what users actually trip over: they open one, do not find the field they came for, and conclude it does not exist. `async_get_options_flow` is therefore not implemented, `supports_options` is `False`, and the reconfigure step is the whole editor.

`streaming_options.py` owns the schema fields for `max_width`, `max_height`, `max_fps`, `reencode` and `stream_audio`, plus `as_numbers` (the dropdowns hand back strings) and `STREAMING_OPTION_KEYS`. The reconfigure step splits its submission on that set and writes those keys to `entry.options` and the rest to `entry.data` — the storage split survives, only the second screen is gone. The size caps filter `SUPPORTED_RESOLUTIONS` and `RECORDING_RESOLUTIONS` before either is advertised; the frame-rate cap clamps them instead (see below).

**No update listener either.** `async_update_reload_and_abort` already reloads the entry; an `add_update_listener(async_reload_entry)` on top of it republished the HAP accessory twice for every change, which a paired controller sees as the camera dropping out and coming back.

### Live streaming

`camera_accessory.start_stream` resolves the RTSP URL through `camera.async_get_stream_source` and hands it to `streaming/`. The live command follows the same `reencode` option as recording and re-encodes by default; copying is what the option turns on, and it only rewrites an over-spec H.264 level in the stream header. Video codec profiles and levels must be passed to `pyhap` as the `bytes` values from `pyhap.camera.VIDEO_CODEC_PARAM_*_TYPES`; plain ints blow up inside `pyhap.tlv.encode`.

**The frame-rate cap clamps what is advertised; it must never filter it.** Every entry in `SUPPORTED_RESOLUTIONS` but the Apple Watch one carries 30 fps, so dropping the ones above the cap leaves a single 320x240 entry — or an empty list, which pyhap encodes as a camera advertising no resolution at all, with no error anywhere.

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

**Nothing but this accessory can be relied on to end a recording.** Every path that marks a session closed — the acknowledgement, the hub's `close` — belongs to the home hub, while every way a delivery ends on its own (the last fragment of the motion event, the recording ceiling, a fragment timeout) does not. A session left in flight is not merely leaked: `_rejection_for` answers `BUSY` to every later `dataSend/open`, so one lost acknowledgement stops the camera recording until the entry is reloaded, with nothing above DEBUG in the log. Three things close that hole and all three are load-bearing: the delivery waits `recording/constants.py`'s `CLOSE_TIMEOUT_SECONDS` for the hub and then closes the stream itself, the delivery task releases the session in a done-callback whatever it ends on, and the data stream server notifies registered listeners from `connection_lost` so a recording whose connection died is released with it.

**A recorder that cannot keep up with real time delivers clips the hub throws away.** ffmpeg has to produce a fragment of negotiated footage in less than the wall-clock time that footage covers; below 1x, the media it emits falls further behind the hub's clock with every fragment, and the hub silently keeps none of them. Nothing about this looks wrong from here: the fragments are well formed, the keyframes land on the boundaries, the delivery completes, and no error is logged or shown in the Home app. Measure it before suspecting anything else — time the gap between `moof` boxes and compare it with `fragment_milliseconds`. The cause is normally an over-sized re-encode: one camera sending 640x480 at 10 fps, upscaled to the 1080p at 30 fps HomeKit had negotiated, ran at 0.70x and never produced a single stored recording, while two cameras re-encoding from larger sources on the same host ran at 0.92x and recorded fine. Capping that entry's resolution and frame rate is what fixes it — the caps in `streaming_options.py` narrow what is advertised, so HomeKit negotiates something the host can actually sustain.

**A clip must end on a fragment that carries footage.** The `endOfStream` marker is a flag on a `dataSend/data` event, so it needs a fragment to ride on — and the hub discards the whole recording, answering `UNEXPECTED_FAILURE` within milliseconds, when that flag arrives on a packet whose `dataTotalSize` is zero. Delivery therefore always holds one fragment back: the recording can only be ended on a fragment already in hand, never at the moment the next one fails to arrive. Getting this wrong fails every single recording while leaving the negotiation, the transport and the ffmpeg side looking perfectly healthy — the log shows fragments going out, the Home app shows no error, and the clip simply never appears.

**Nothing guarantees the trigger will ever clear.** `always_on_motion` never lowers `MotionDetected` at all, and a linked sensor can stay on longer than `MAX_RECORDING_SECONDS`, so the ceiling and the fragment timeout are ordinary endings, not failure paths. Both have to produce a well-formed end of clip, or continuous recording never delivers anything.

**Nothing may hold the recorder lock indefinitely.** `_async_sync_recorder` serialises every start and stop under one lock, and `async_stop` runs inside it, so a single await that never returns there stops the camera recording for good: `_rejection_for` then answers `INVALID_CONFIGURATION` to every `dataSend/open` at DEBUG, the hub retries thousands of times a minute, and each retry used to queue another task behind that lock until the process ran out of memory. Both halves are load-bearing — every wait in `async_stop` is bounded (including the one after `kill()`, since a lost exit notification is enough to hang it), and `_request_recorder_sync` coalesces the storm into one pending synchronisation. That same storm arrives as writes, not just as requests: the hub rewrites `SelectedCameraRecordingConfiguration` with the value it already chose hundreds of times a minute, so an identical write returns before it announces anything — announcing it republishes every entity of the entry behind the coordinator.

**A recorder that dies is invisible unless it says so.** `read_segments` simply stops yielding when ffmpeg exits — which `-shortest` guarantees for a camera that reboots — and a request arriving with no recorder running is rejected before a session exists, so nothing re-synchronises on its own. The recorder reports the end of its stream and the accessory starts it again with an exponential backoff, resetting after a run long enough to count as working — either when a run ends having lasted, or from `_async_confirm_recorder_health`, which counts a run that is *still going* after `HEALTHY_RECORDER_RUN_SECONDS`. For the same reason the recorder is restarted when the negotiated configuration or the audio setting it was spawned with stops matching: both are read once, when ffmpeg starts.

**The end of the output is not the end of the process.** ffmpeg can stop producing fragments while it is still alive, so `_async_read_segments` ends the process itself and only then reads the exit code: read at the moment the pipe closes, `returncode` is still `None` nine times out of ten, and the log line that is supposed to explain why a camera stopped recording says nothing. Worse, a process that is never waited for keeps `is_running` answering `True`, and `_rejection_for` then accepts `dataSend/open` against a recorder that has nothing left to send — the hub gets a clip that runs out of fragments and is never acknowledged, once a minute, for as long as the camera stays down. ffmpeg's stderr is kept for the same reason: it is a `PIPE` drained into a small ring buffer, because the last thing it wrote is the only account of what went wrong.

**A camera that does not answer the probe must not be asked again on every start.** `_async_source_has_audio` re-probes only a profile whose probe failed, and each of those costs up to `PROBE_TIMEOUT_SECONDS` under the recorder lock, with the hub waiting. A failed answer is therefore kept for `SOURCE_PROBE_RETRY_SECONDS`, and a successful one replaces `_source_profile` for good — which also gives the level, the size and the frame rate to everything else that reads it.

**HAP-python does not give a standalone accessory everything HAP requires.** Two pieces have to be added by hand, and their absence is invisible in the logs — the controller simply treats the accessory as incomplete and refuses to configure it:

- **`ProtocolInformation` (service `A2`) with `Version` = `1.1.0`.** HAP-python has no definition for it at all; it only ever appears inside bridges. Built by hand in `_protocol_information_service`.
- **`Active` on every `CameraRTPStreamManagement`.** HAP-python's `Camera` omits it.

Both were found by diffing our accessory against a working one (see below). Note that a characteristic added to a service *after* HAP-python registered that service gets neither a broker nor an iid — `_add_active_to_stream_managements` wires both by hand, and forgetting that makes `to_HAP` raise.

**When stuck, diff against a working accessory instead of guessing.** `Controller` from `aiohomekit` (already in Home Assistant) pairs with any unpaired accessory and dumps its full description; comparing services and characteristics against ours turned a long guessing streak into three concrete findings in one pass. The accessory has to be unpaired first, and the dump script should remove its own pairing afterwards.

**Reading `SelectedCameraRecordingConfiguration` before one is negotiated must FAIL.** Answering an empty value with a success status tells the controller a configuration is already in place — an empty one — so it never writes the one it was about to select, and the Home app reports the generic settings error. The reference implementation throws `SERVICE_COMMUNICATION_FAILURE` there, which is also what HAP-python answers when a getter raises.

**The caps are a ceiling on the camera, not a target.** `max_width`, `max_height` and `max_fps` are worded as maxima and must behave as maxima: `source_limits.py` narrows the advertised offer to what the camera actually sends before the caps are applied, because anything advertised above that can only be honoured by upscaling or by duplicating frames — an encode proportional to pixels and frames that carry nothing new. One camera sending 640x480 at 10 fps, advertised at 1080p30, cost a whole core doing exactly that.

**HomeKit only negotiates a frame size it already knows.** The narrowing stops at the catalogue: offered its own 896x512, a camera left `SelectedCameraRecordingConfiguration` unwritten and never recorded again, while the 1920x1080 camera beside it carried on — no error anywhere, `selected_configuration` simply stayed `null`. A camera smaller than every entry is therefore offered the smallest entry *alone*, so the upscale is the least the catalogue allows rather than whatever HomeKit would have picked. The frame rate has no such constraint: a camera advertising 15 fps records normally.

**The advertised frame rate has a floor.** A camera advertising its own 10 fps left `SelectedCameraRecordingConfiguration` unwritten and recorded nothing; the same camera at 15 fps recorded normally, so `MIN_ADVERTISED_FPS` raises anything slower — the one place duplicated frames cannot be avoided.

**HomeKit takes 16:9 and nothing else, so a 4:3 camera is pillarboxed and that is the end of it.** This was tried and reverted, and the attempt is worth knowing about: `RECORDING_RESOLUTIONS` grew a 4:3 pair and the offer was narrowed to the shape matching the camera, so a 640x480 camera was offered 640x480 alone — one entry, 4:3, at a frame rate already known to work. The hub left `SelectedCameraRecordingConfiguration` unwritten and the camera recorded nothing, while the 16:9 cameras beside it carried on. Removing and re-adding the camera in the Home app did not help; only the still image came back. **The live side fails worse.** `SUPPORTED_RESOLUTIONS` has exactly one 4:3 entry — the 320x240 the Apple Watch asks for — so narrowing by shape leaves a camera advertising nothing but a thumbnail, which is the same trap the frame-rate cap is warned about above. Both offers must stay 16:9; the black bars are the price.

**A hub reuses the configuration it has cached.** It may write back a configuration that is no longer in the offer — one camera kept 15 fps after the accessory narrowed its advertisement to the source's 10 — so a changed offer does not take effect until the hub renegotiates on its own.

**Offer HomeKit little, not much.** The controller picks one configuration out of what the accessory advertises, and it fails to pick at all when offered too many: recording advertises exactly two resolutions (`RECORDING_RESOLUTIONS`) and a single audio sample rate, matching what Scrypted narrowed its own offer to. A too-wide offer surfaces in the Home app as a generic "error updating this setting" on **any** mode change — not just recording — with every HAP write answered `204 No Content`, so the log gives no hint.

**Whatever follows `HomeKitCameraActive` must follow it in both directions.** The linked motion sensor's `StatusActive` mirrors it; updating that only when the camera is switched *off* leaves the sensor inactive forever, and HomeKit then refuses to switch the camera back on — it writes the new mode, waits about 13 seconds for the accessory to look usable, and reverts. Same generic Home app error, same silent HAP log.

**`FirmwareRevision` must be set and shaped like `x[.y[.z]]`.** HAP-python leaves it empty unless `set_info_service` is given one, and a controller then re-reads it in a loop and refuses to apply settings to the accessory — same symptom, same silent log.

**The video is re-encoded, not copied — unless the `reencode` option says otherwise.** Copying is far cheaper, and it was the original design, but it hands HomeKit whatever the camera happens to send: the cameras this was built against ship H.264 level 4.1 and 5.1 at 20 fps, and one of them at 2880x1616 — none of which HomeKit accepts, and all of which it had just negotiated something else for. `libx264 -preset ultrafast` re-encodes 1080p in real time at roughly one core on a Raspberry Pi 5, against a tenth of a core for two cameras in copy mode; `RECORDING_RESOLUTIONS` and the negotiated frame rate keep that bounded. Rewriting only the level in the SPS (`-bsf:v h264_metadata=level=4`) works and costs nothing, but it fixes just one of the three mismatches.

Four things that will bite whoever touches the ffmpeg side:

- **Recording keyframes must land on fragment boundaries.** Every fragment has to open on one, so `-g` and `-force_key_frames` are both set from the negotiated fragment length. Leaving it to `frag_keyframe` alone means fragments as long as the camera's own GOP.
- **The movflag is `default_base_moof`**, not `default_base_is_moof`. The wrong spelling is in a lot of prior art; ffmpeg rejects it outright and nothing records.
- **`-shortest` is not optional.** The silent audio track is generated by `anullsrc`, which never ends: without it a dead camera leaves ffmpeg alive forever, emitting fragments that carry nothing but silence.
- **HomeKit will not play a recording without an audio track.** `source_probe.py` asks ffprobe whether the camera has one, because mapping a track that is not there makes ffmpeg refuse to start. The answer comes from the profile probed when the accessory was published — probing again would hold the recorder lock for up to fifteen seconds while the hub waits, on every start.

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

`issues.py` re-evaluates three issues on every start, from what the source probe found, and withdraws each one as soon as it stops applying: `no_stream_source`, `unsupported_codec` (anything other than H.264) and `oversized_source` (a picture larger than the largest offered resolution, raised **only while copying** — re-encoding scales it down). A fourth, `recorder_unavailable`, is not decided by the probe but by the accessory: `UNHEALTHY_RECORDER_RESTARTS` restarts in a row without a healthy run is a camera recording nothing, and nothing else says so — every rejection the hub collects is logged at DEBUG. They are informational, so nothing implements `RepairsFlow`; the module is deliberately not named `repairs.py`, which is the platform Home Assistant loads for fixable issues.
