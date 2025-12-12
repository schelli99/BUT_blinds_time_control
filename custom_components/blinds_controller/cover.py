
# TODO add-ons weather date of the time or sunset and sundown automations
# TODO clean up code

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverEntityFeature,
    CoverEntity,
)
from homeassistant.const import (
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_STOP_COVER,
)
from homeassistant.helpers import entity_platform
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import (
    async_track_time_interval,
    async_track_state_change_event,
)

import logging
from datetime import datetime, timedelta
import urllib.request
import json

from .calculator import TravelCalculator, TravelStatus
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_KNOWN_POSITION = "set_known_position"
SERVICE_SET_KNOWN_TILT_POSITION = "set_known_tilt_position"


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
        SERVICE_SET_KNOWN_POSITION, "set_known_position"
    )
    platform.async_register_entity_service(
        SERVICE_SET_KNOWN_TILT_POSITION, "set_known_tilt_position"
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    async_add_entities([BlindsCover(hass, entry, entry.title, entry.entry_id)])


class BlindsCover(CoverEntity, RestoreEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name, device_id):
        self.hass = hass
        self.entry = entry
        self._name = name or device_id
        self._unique_id = device_id
        self._available = True

        self._travel_time_down = entry.data["time_down"]
        self._travel_time_up = entry.data["time_up"]
        self._travel_tilt_closed = entry.data["tilt_closed"]
        self._travel_tilt_open = entry.data["tilt_open"]
        self._up_switch_entity_id = entry.data["entity_up"]
        self._down_switch_entity_id = entry.data["entity_down"]

        self.travel_calc = TravelCalculator(
            self._travel_time_down,
            self._travel_time_up,
        )

        self.tilt_calc = (
            TravelCalculator(self._travel_tilt_closed, self._travel_tilt_open)
            if self.has_tilt_support()
            else None
        )

        self._unsubscribe_auto_updater = None

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return "cover_timebased_synced_uuid_" + self._unique_id

    @property
    def supported_features(self):
        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )
        return features

    @property
    def current_cover_position(self):
        return self.travel_calc.current_position()

    async def async_open_cover(self, **kwargs):
        self.travel_calc.start_travel_up()
        self.start_auto_updater()
        await self._async_handle_command(SERVICE_OPEN_COVER)

    async def async_close_cover(self, **kwargs):
        self.travel_calc.start_travel_down()
        self.start_auto_updater()
        await self._async_handle_command(SERVICE_CLOSE_COVER)

    async def async_stop_cover(self, **kwargs):
        await self._async_handle_command(SERVICE_STOP_COVER)

    def start_auto_updater(self):
        if self._unsubscribe_auto_updater is None:
            self._unsubscribe_auto_updater = async_track_time_interval(
                self.hass, self.auto_updater_hook, timedelta(seconds=0.1)
            )

    def stop_auto_updater(self):
        if self._unsubscribe_auto_updater:
            self._unsubscribe_auto_updater()
            self._unsubscribe_auto_updater = None

    @callback
    def auto_updater_hook(self, now):
        self.async_write_ha_state()
        if self.travel_calc.position_reached():
            self.stop_auto_updater()

    async def async_added_to_hass(self):
        self._unsub_interval = async_track_time_interval(
            self.hass, self.add_ons, timedelta(minutes=1)
        )

        old_state = await self.async_get_last_state()
        if old_state and ATTR_CURRENT_POSITION in old_state.attributes:
            self.travel_calc.set_position(
                int(old_state.attributes[ATTR_CURRENT_POSITION])
            )

    async def async_will_remove_from_hass(self):
        if self._unsub_interval:
            self._unsub_interval()
        if self._unsubscribe_auto_updater:
            self._unsubscribe_auto_updater()

    async def add_ons(self, now):
        pass

    async def _async_handle_command(self, command):
        if command == SERVICE_OPEN_COVER:
            await self.hass.services.async_call(
                "homeassistant", "turn_on", {"entity_id": self._up_switch_entity_id}
            )
        elif command == SERVICE_CLOSE_COVER:
            await self.hass.services.async_call(
                "homeassistant", "turn_on", {"entity_id": self._down_switch_entity_id}
            )
        elif command == SERVICE_STOP_COVER:
            await self.hass.services.async_call(
                "homeassistant", "turn_off",
                {"entity_id": [self._up_switch_entity_id, self._down_switch_entity_id]}
            )
