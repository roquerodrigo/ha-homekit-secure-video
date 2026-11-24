# HomeKit Secure Video

<!-- ha-marketplace:exclude-start -->
[![CI](https://github.com/roquerodrigo/ha-homekit-secure-video/actions/workflows/ci.yml/badge.svg)](https://github.com/roquerodrigo/ha-homekit-secure-video/actions/workflows/ci.yml)
[![GitHub release](https://img.shields.io/github/v/release/roquerodrigo/ha-homekit-secure-video)](https://github.com/roquerodrigo/ha-homekit-secure-video/releases/latest)
[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-db61a2?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/roquerodrigo)

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=roquerodrigo&repository=ha-homekit-secure-video&category=integration)
<!-- ha-marketplace:exclude-end -->

Put your Home Assistant cameras in the Apple Home app with HomeKit Secure Video: watch them live, and let your Apple home hub record clips when motion is detected and store them in iCloud. Each camera pairs with the Home app like any HomeKit camera, directly with Home Assistant on your local network. The HomeKit Bridge that comes with Home Assistant shows cameras in the Home app but cannot record them.

## Features

- Watch any Home Assistant camera that serves a video stream live in the Home app, with its audio.
- Record a clip to iCloud each time a Home Assistant motion sensor detects motion, including the few seconds before it. You can also record continuously.
- See the camera's snapshot in the Home app.
- Choose between re-encoding the video, which works with most cameras, and passing the camera's stream through, which uses almost no CPU.
- Follow from Home Assistant the mode chosen in the Home app, whether a clip is being recorded and when the last one finished.
- Pair by scanning a QR code, and get a repair in Home Assistant when a camera's stream cannot be served to HomeKit.

## Requirements

- Home Assistant 2026.8.2 or newer.
- A camera in Home Assistant that can serve a video stream, sending H.264 video.
- To record: an Apple home hub (HomePod or Apple TV) and an iCloud+ plan with a free camera slot. Without them the Home app offers live view only.
- To record on motion: a motion sensor in Home Assistant (a binary sensor of the motion type). Without one, the camera can only record continuously.
- Your iPhone and your home hub must reach Home Assistant on the local network, with mDNS (Bonjour) working between them. Each camera uses its own TCP port, starting at 21064.
- Spare CPU if you re-encode: about one CPU core for each 1080p camera.

<!-- ha-marketplace:exclude-start -->
## Installation

### Home Assistant Marketplace (recommended)

1. Select the **Open your Home Assistant instance** button above, or go to **Settings → Marketplace**, select **Add from link** in the upper right corner, enter `roquerodrigo/ha-homekit-secure-video` and select **Add**.
2. Select **Install**.
3. Restart Home Assistant.

The Marketplace comes with Home Assistant 2026.11 and later. On older versions, add this repository to HACS as a custom repository of type **Integration** and install it from there.

### Manual

1. Download `homekit_secure_video.zip` from the [latest release](https://github.com/roquerodrigo/ha-homekit-secure-video/releases/latest).
2. Extract it into `config/custom_components/homekit_secure_video/`.
3. Restart Home Assistant.
<!-- ha-marketplace:exclude-end -->

## Configuration

Go to **Settings → Devices & services → Add integration**, search for **HomeKit Secure Video** and fill in the form. Each entry publishes one camera, so repeat this for every camera you want in the Home app.

| Field                | What to enter                                                                 | Default |
|----------------------|-------------------------------------------------------------------------------|---------|
| Camera               | The camera to publish. Only cameras that can serve a stream are accepted      |         |
| Motion sensor        | The motion sensor whose detections start a recording                          |         |
| Re-encode video      | Whether to re-encode the video for HomeKit. See Re-encoding below             | On      |
| Always report motion | Record continuously. The motion sensor is ignored and iCloud fills up faster  | Off     |

Without a motion sensor and with **Always report motion** off, the camera streams in the Home app but never records.

### Pairing with the Home app

1. While the camera is not paired, Home Assistant shows a notification with its pairing code. The device page of the camera also shows a **Pairing QR code**.
2. In the Home app, select **Add Accessory** and scan the QR code, or enter the code from the notification.
3. To record, open the camera's settings in the Home app and choose **Stream & Allow Recording**.

The notification goes away once the camera is paired. The code stays the same after restarts and reconfiguration.

### Changing a camera later

Open the integration, select the three-dot menu of the camera and select **Reconfigure**. The camera stays paired, so you do not have to add it to the Home app again.

| Field                | What it does                                                                                 | Default |
|----------------------|----------------------------------------------------------------------------------------------|---------|
| Camera               | The camera to publish. You can point the entry at another camera, or another stream of it   |         |
| Motion sensor        | The motion sensor whose detections start a recording. Clear it to stop recording on motion  |         |
| Always report motion | Record continuously                                                                          | Off     |
| Maximum width        | The widest picture offered to HomeKit, a choice from 320 to 3840 pixels                      | 1920    |
| Maximum height       | The tallest picture offered to HomeKit, a choice from 240 to 2160 pixels                     | 1080    |
| Maximum frame rate   | The highest frame rate offered to HomeKit, from 10 to 60 in steps of 5                       | 30      |
| Re-encode video      | Whether to re-encode the video for HomeKit                                                   | On      |
| Include audio        | Send the camera's audio to the Home app in live view. No effect on a camera without audio   | On      |

The three maximums apply to live view and to recordings. Home Assistant also avoids offering HomeKit a larger picture or a higher frame rate than the camera sends.

### Re-encoding

With **Re-encode video** on, Home Assistant converts the camera's video to exactly the picture size, frame rate and H.264 settings HomeKit asks for. This makes cameras work whose own stream HomeKit refuses, and costs about one CPU core for each 1080p camera.

With it off, the camera's stream is passed through as it is, apart from a header fix that costs nothing. Two cameras use about a tenth of a CPU core this way. It needs a camera that already sends H.264 at a size HomeKit accepts, 1080p or less. A camera's secondary stream often does, and pointing the entry at it is the cheapest way to run. If a recording does not match what HomeKit asked for, that recording is re-encoded anyway, so it is not lost.

## Entities

Each camera appears as one device, named after the camera, with these entities:

| Entity              | Type          | Shows                                                                            |
|---------------------|---------------|----------------------------------------------------------------------------------|
| HomeKit camera mode | Sensor        | The mode chosen in the Home app: Off, Detect activity, Stream or Stream and allow recording |
| Recording           | Binary sensor | Running while a clip is being sent to the home hub                               |
| Last recording      | Sensor        | When the last clip finished being sent                                           |
| Paired              | Binary sensor | Diagnostic. Whether the camera is paired with the Home app                       |
| Pairing QR code     | Image         | Diagnostic. The code to scan with the Home app                                   |
| Reset pairing       | Button        | Configuration. Removes every pairing, so you can add the camera to a Home again  |

## How it works

Home Assistant publishes each camera on your local network as a HomeKit camera of its own. The Home app and the home hub talk to Home Assistant directly. Clips leave your network only when the home hub stores them in iCloud.

When you open the live view, Home Assistant reads the camera's stream and sends it to the Home app. While the camera is set to **Stream & Allow Recording**, Home Assistant keeps reading the camera so that it always holds the last few seconds. When the motion sensor turns on, the home hub starts a recording, receives those seconds and then the live footage until the motion ends. A clip lasts at most 3 minutes. With **Always report motion**, the hub starts one clip after another.

HomeKit picks the recording quality: 1280x720 or 1920x1080, at 15 or 30 frames per second, within the maximums you set and, as far as these sizes allow, no larger than what the camera sends. HomeKit only takes 16:9 pictures, so a re-encoded camera with another shape gets black bars.

The pairing and the recording settings HomeKit chose are kept across restarts, so the camera comes back in the Home app on its own. If the camera drops out, Home Assistant reconnects to it automatically.

## Troubleshooting

**The Home app does not offer Stream & Allow Recording.** Recording needs an Apple home hub and an iCloud+ plan with a free camera slot. Check both in the Home app settings.

**The camera never records.** Link a motion sensor, or turn on **Always report motion**, with **Reconfigure**. The **Recording** entity turns on while a clip is being sent.

**Recording turns on, but no clip appears in the Home app.** The home hub silently drops clips that arrive slower than real time, which happens when re-encoding is too heavy for your hardware. Lower **Maximum width**, **Maximum height** or **Maximum frame rate**, or turn off re-encoding with a stream that already matches what HomeKit accepts.

**Settings → Repairs shows a problem with a camera.** Home Assistant checks the camera's stream each time the entry starts, including after **Reconfigure**, and each repair goes away once its cause is fixed.

- The camera does not provide a stream: point the entry at a camera that serves RTSP.
- The camera sends a video codec HomeKit cannot play: switch the camera to H.264, often available on its secondary stream.
- The camera sends a larger picture than HomeKit negotiated: point the entry at a smaller stream, or turn on re-encoding.
- The camera keeps dropping out of recording: make sure the camera is reachable and serves its stream continuously. The Home Assistant log shows what went wrong each time.

**You want to add the camera to another Home, or start over.** Press **Reset pairing**, then pair again with the QR code or the code in the notification.

**Something else is wrong.** Download the diagnostics from the camera's device page and attach them to an [issue](https://github.com/roquerodrigo/ha-homekit-secure-video/issues), along with the debug log. The pairing code is removed from the diagnostics, and camera passwords are removed from the log.

## Known limitations

- Each camera is a separate accessory in the Home app, with its own pairing code. HomeKit does not accept cameras behind a bridge.
- Only H.264 video is supported.
- Recordings start on motion only. Doorbell presses do not start a recording.
- When you lower the maximums, the home hub can keep the recording quality it chose earlier until it negotiates again on its own.

## Support

This integration is built and maintained on personal time, on hardware bought for the purpose. If it is useful to you, consider [sponsoring the work](https://github.com/sponsors/roquerodrigo). It keeps the devices, the testing and the releases coming.

Report bugs and ask for features in the [issue tracker](https://github.com/roquerodrigo/ha-homekit-secure-video/issues).

<!-- ha-marketplace:exclude-start -->
## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and workflow, and [CODE_STYLE.md](CODE_STYLE.md) for the code conventions.

## Trademark

Apple, HomeKit and the HomeKit logo are trademarks of Apple Inc. This project is not affiliated with, endorsed by, or sponsored by Apple Inc.

## License

[MIT](LICENSE)
<!-- ha-marketplace:exclude-end -->
