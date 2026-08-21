from __future__ import annotations

from homeassistant import data_entry_flow


async def test_options_flow_shows_the_form(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_stores_the_limits_as_numbers(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"max_width": "1280", "max_height": "720", "max_fps": 15},
    )
    await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    # Stored as numbers: everything downstream compares them against the
    # resolutions offered to HomeKit.
    assert setup_integration.options["max_width"] == 1280
    assert setup_integration.options["max_height"] == 720
    assert setup_integration.options["max_fps"] == 15


async def test_the_form_offers_the_current_limits_as_text(hass, setup_integration):
    hass.config_entries.async_update_entry(
        setup_integration, options={"max_width": 1280, "max_height": 720}
    )

    result = await hass.config_entries.options.async_init(setup_integration.entry_id)

    schema = result["data_schema"].schema
    defaults = {str(key): key.default() for key in schema}
    # The dropdowns are built from strings, so their defaults have to be too.
    assert defaults["max_width"] == "1280"
    assert defaults["max_height"] == "720"


async def test_the_form_opens_with_no_options_saved(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)

    schema = result["data_schema"].schema
    defaults = {str(key): key.default() for key in schema}
    assert defaults["max_width"] == "1920"
    assert defaults["max_height"] == "1080"


async def test_options_flow_reloads_the_entry(
    hass, setup_integration, mock_accessory_driver
):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"max_width": "640", "max_height": "360", "max_fps": 30},
    )
    await hass.async_block_till_done()

    assert mock_accessory_driver.async_stop.await_count == 1
    assert mock_accessory_driver.async_start.await_count == 2


async def test_reencoding_is_on_by_default(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)

    schema = result["data_schema"].schema
    reencode = next(key for key in schema if str(key) == "reencode")
    assert reencode.default() is True


async def test_reencoding_can_be_turned_off(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "max_width": "1920",
            "max_height": "1080",
            "max_fps": 30,
            "reencode": False,
        },
    )
    await hass.async_block_till_done()

    assert setup_integration.options["reencode"] is False
