# Brand assets

Apple HomeKit artwork, derived from the
[HomeKit logo on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Apple_HomeKit_logo.svg).
Apple, HomeKit and the HomeKit logo are trademarks of Apple Inc.; this project
is not affiliated with, endorsed by, or sponsored by Apple Inc.

| File          | Shape                          | Size    |
| ------------- | ------------------------------ | ------- |
| `icon.png`    | square symbol                  | 256×256 |
| `icon@2x.png` | square symbol                  | 512×512 |
| `icon.svg`    | square vector of `icon`        | 1024×1024 |
| `logo.png`    | landscape mark, symbol centred | 256×128 |
| `logo@2x.png` | landscape mark, symbol centred | 512×256 |

The PNGs are rendered from `icon.svg`; the landscape pair pads the same square
symbol onto a 2:1 canvas.

Nothing has to be submitted anywhere. Since Home Assistant 2026.3 a custom
integration ships its own brand images: the core `brands` integration serves
whatever it finds in this `brand/` directory through
`/api/brands/integration/homekit_secure_video/{image}`, and a local image wins
over the brands CDN. The directory existing is the whole opt-in —
`Integration.has_branding` is `"brand" in self._top_level_files`, and no
`manifest.json` key is involved.

`home-assistant/brands` still holds a legacy `custom_integrations/` folder, but
it **no longer accepts pull requests for custom integrations**.

Only these filenames are served (`ALLOWED_IMAGES` in
`homeassistant/components/brands/const.py`), and missing ones fall back down a
chain that ends at `icon.png`:

`icon.png`, `logo.png`, `icon@2x.png`, `logo@2x.png`, `dark_icon.png`,
`dark_logo.png`, `dark_icon@2x.png`, `dark_logo@2x.png`

`icon.svg` is kept here as the source the PNGs are rendered from; Home
Assistant ignores it.

See the [announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).
