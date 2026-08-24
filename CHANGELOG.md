# Changelog

## [0.1.1](https://github.com/roquerodrigo/ha-homekit-secure-video/compare/v0.1.0...v0.1.1) (2026-08-24)


### Features

* **hacs:** ship the install zip with every release ([dba9ecd](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/dba9ecdaeed18c9365eb4b9bc07a3a3f0c856008))


### Development Dependencies

* **deps-dev:** bump ruff in the python-deps group ([ae7c1d3](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/ae7c1d3304fa2730e38fe6100016c939d6ec87ea))

## 0.1.0 (2026-08-22)


### Features

* offer the streaming options in the reconfigure step ([b70918d](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/b70918defa162799b556bcb0e14ba526f85cc407))
* publish Home Assistant cameras to HomeKit with Secure Video ([bfc330b](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/bfc330b66b8835941ab1b9d1f60d536fbb139d72))


### Bug Fixes

* apply a recording setting HomeKit changes while the recorder runs ([25af0e5](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/25af0e5b30b4bef738697858228b21e808271127))
* bound OPACK nesting depth so a deep payload stays a codec error ([d56cc79](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/d56cc7921e204a18bdc118bf049345f4ca118822))
* cancel pending recorder work when the accessory stops ([ffd8167](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/ffd8167587023baa6a79db45471878c10f4bff66))
* cap the advertised frame rate instead of dropping resolutions ([22ef818](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/22ef8180f714915250ee0fb3fb59d3ebda81d319))
* count a decoded OPACK date towards the back-reference index ([905f3f2](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/905f3f2651814cd6e07846c42e62e5da978e1c9b))
* drain the stderr of the live stream ffmpeg ([79c7eec](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/79c7eec4ced50f92652a2ee937e337fd38607040))
* find ffprobe beside any configured ffmpeg build ([500d1c9](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/500d1c957c161c82538b3d785efc8dc74d3be6dd))
* free the stream slot of a live session whose ffmpeg exits ([b810c1b](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/b810c1b445f9150b74327b171ff2004ff24cb94e))
* keep the accessory key salt out of a readable characteristic ([33da25f](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/33da25ffd56e8e0ae4a43183b9d19eb7454a1fc8))
* point the re-encoding hints at the reconfigure step ([3468e3e](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/3468e3e098eaba239b8a43d8990e98cd8648189b))
* re-encode a recording the camera cannot deliver as negotiated ([00dc18f](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/00dc18ffbc8b19d0387ca965e661f9e192317352))
* **recording:** bound the wait for a killed ffmpeg to exit ([b0c2562](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/b0c25621ec89476a4794b43a41e60194e4f6e8b0))
* **recording:** end a clip on a fragment that carries footage ([803be07](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/803be074e09ae26b8f8461e9015b09fc07b4c5ff))
* **recording:** raise the advertised frame rate to the floor hubs accept ([b26f2d6](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/b26f2d6b6266341d5f1963b796e4b979a4ac9e4f))
* **recording:** size the delivery waits for a slow recorder ([8217d9a](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/8217d9a9b63643308fea63f239bb8875b507e7b5))
* redact credentials carried in a stream URL query string ([c8a0edb](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/c8a0edb233d033f24eaed934168015b19f221ea9))
* release a recording session the hub never acknowledges ([1434e80](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/1434e802001f9e23b83738be50a88603d8198a67))
* release the ports a failed setup acquired ([1e4114a](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/1e4114a53076ad7b0a16ce569769542fb7cea736))
* report a short numeric field in the selected recording configuration ([fb360f4](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/fb360f47add50db2af4e42b3deae5f89cc256c3c))
* stamp the last recording only when footage was delivered ([9da5d2a](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/9da5d2a93bde37348a11ac506c3148141e9afbfa))
* start one recorder per camera, not one per HomeKit write ([18bb895](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/18bb895544539bbba3dc95176cc37d8920744f84))
* start the recorder again after ffmpeg stops on its own ([a9382be](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/a9382be34dad7036bfedad82f379dda911db8319))
* stop restamping the pairing QR code on unrelated status changes ([fd744a9](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/fd744a92e21cd93af59caa05f3932c032bc63dc2))
* **streaming:** treat the size and frame-rate caps as ceilings ([7d5ece3](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/7d5ece305759db1b7e1c9310d011561554d9344b))
* tear down the recording in flight when the accessory stops ([eece42c](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/eece42c654ea8d08ad073b76739c421020d7508c))


### Performance Improvements

* **recording:** coalesce recorder synchronisations ([153c1e5](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/153c1e5986623d43db46d44a66818324cb9f6c09))
* reuse the probed source profile for the recording audio track ([d2d9db9](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/d2d9db99dbd4c82b395d61d4ee0eebbb39d96360))


### Code Refactoring

* edit an entry in one screen instead of two ([aa10447](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/aa10447e1ea8dd6fd5d40688ac8fdce27dd18d34))


### Development Dependencies

* **deps-dev:** bump the python-deps group with 4 updates ([d23eaa9](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/d23eaa9659810eda7237cdde562bd88ce8d76e9c))


### Documentation

* brand assets are shipped, not submitted upstream ([e1528f4](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/e1528f47dcff734ce347c54edcd1bb90b7bccc18))
* bring the README back in line with the integration ([4f3b277](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/4f3b277776128ac169b0ba748acde7281e3f67e3))
* describe what the source probe is actually for ([c5289b9](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/c5289b9bd6ef2c282f6bd2e6aa8123e59cf88cda))
* record how a recorder slower than real time fails ([b3c3373](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/b3c3373eaec7036954943e7581078acc54435cdb))
* record the integration type the manifest actually declares ([e6d5c78](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/e6d5c78489bf5c600f28d335a90208a5f2f9492f))
* record the lifecycle invariants the review turned up ([cea2b3c](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/cea2b3c80db5445aecff2f06b2fdffc55eb664a8))
* record the recording invariants behind these fixes ([afb7189](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/afb71896de32e36670036cc1b6d9017b8ea36c49))


### Tests

* assert the recorder actually hands fragments to its subscribers ([f663fa8](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/f663fa860d089a026b2ac7f345fd3212318b0bf9))
* exercise the camera mode on the real accessory ([a725f7b](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/a725f7b7a41478b18b87557a5c8c42a807806acc))
* prove a connection survives a message it could not use ([403385e](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/403385e0ad6b8b8d472bf239a641cc0f6d1a9822))


### Miscellaneous Chores

* release 0.1.0 ([7c83fff](https://github.com/roquerodrigo/ha-homekit-secure-video/commit/7c83fff7a269bbf9f0ff1b1b57bb574f60479cf3))

## Changelog
