"""Local push integration; browser sessions stay in the Home Assistant app."""
import asyncio
import json
import logging

from homeassistant.helpers.http import HomeAssistantView, KEY_HASS
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.unit_conversion import EnergyConverter

from .const import API_PATH, DOMAIN, MAX_BYTES, NAME
from .model import InvalidSnapshot, hourly_statistics, prepare

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})
    hass.http.register_view(ReadingsView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry):
    coordinator = DataUpdateCoordinator(hass, _LOGGER, name=NAME)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", private=True)
    saved = await store.async_load()
    state = {"entry": entry, "coordinator": coordinator, "store": store,
             "lock": asyncio.Lock(), "saved": saved, "active": True}
    hass.data[DOMAIN]["state"] = state
    if saved:
        coordinator.async_set_updated_data(saved["summary"])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    state = hass.data[DOMAIN].get("state")
    if state:
        async with state["lock"]:
            state["active"] = False
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop("state", None)
        return True
    if state:
        state["active"] = True
    return False


class ReadingsView(HomeAssistantView):
    url = API_PATH
    name = f"api:{DOMAIN}:readings"
    requires_auth = True

    async def post(self, request):
        # A regular HA long-lived access token authenticates this route.
        hass = request.app[KEY_HASS]
        state = hass.data.get(DOMAIN, {}).get("state")
        if not state:
            return self.json({"error": "integration_not_loaded"}, status_code=503)
        body = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                return self.json({"error": "snapshot_too_large"}, status_code=413)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return self.json({"error": "invalid_json"}, status_code=400)
        async with state["lock"]:
            if not state["active"]:
                return self.json({"error": "integration_not_loaded"}, status_code=503)
            entry = state["entry"]
            previous = state["saved"]["snapshot"] if state["saved"] else None
            try:
                data, summary = await hass.async_add_executor_job(
                    prepare, payload, entry.data["time_zone"], entry.data["timestamp_label"], previous)
                rows = []
                if entry.options.get("import_statistics", False):
                    rows = await hass.async_add_executor_job(
                        hourly_statistics, data, entry.data["time_zone"], entry.data["timestamp_label"])
            except InvalidSnapshot as err:
                return self.json({"error": "invalid_snapshot", "message": str(err)}, status_code=400)
            # Save before queueing stats. Replays always requeue, so a restart between
            # these operations is recoverable with the same upload.
            saved = {"snapshot": data, "summary": summary}
            try:
                await state["store"].async_save(saved)
                if rows:
                    async_add_external_statistics(hass, {
                        "statistic_id": f"{DOMAIN}:{entry.entry_id.lower()}_consumption",
                        "source": DOMAIN, "name": f"{NAME} electricity consumption",
                        "mean_type": StatisticMeanType.NONE, "has_sum": True,
                        "unit_class": EnergyConverter.UNIT_CLASS, "unit_of_measurement": "kWh",
                    }, rows)
            except Exception:
                # Never log payloads, access tokens or backend exception text.
                _LOGGER.error("Could not save or queue Empower readings; retry the upload")
                return self.json({"error": "storage_failed_retry_upload"}, status_code=503)
            state["saved"] = saved
            state["coordinator"].async_set_updated_data(summary)
            return self.json({"accepted": True, "readings": summary["count"],
                              "statistics_hours_queued": len(rows)})
