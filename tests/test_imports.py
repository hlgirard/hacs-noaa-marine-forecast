"""Import every integration module with a stubbed Home Assistant.

``compileall`` only checks syntax. An integration can be syntactically
perfect and still fail to load because a name imported from a sibling module
does not exist -- the failure mode that produced "cannot import name
'CONF_SCAN_INTERVAL' from ...const" in the Home Assistant log.

Home Assistant is not installed in the test environment, so the modules that
import it are exercised here against minimal stubs. That verifies every
``from .x import y`` resolves, which is the part that breaks in practice; it
does not verify behaviour against real Home Assistant.
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
import types
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "noaa_marine_forecast"

#: Import order, so stubs are installed before anything is imported.
MODULES = (
    "const",
    "flags",
    "assets",
    "parser",
    "alerts",
    "api",
    "coordinator",
    "config_flow",
    "sensor",
    "image",
)


def _stub(name: str, **attrs: object) -> types.ModuleType:
    """Register a stub module in ``sys.modules``."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_stubs() -> None:
    """Install minimal stand-ins for the third party modules HA provides."""
    for name in (
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.config_validation",
        "homeassistant.util",
        "homeassistant.util.dt",
        "homeassistant.const",
        "homeassistant.components",
        "homeassistant.components.sensor",
        "homeassistant.components.image",
    ):
        if name not in sys.modules:
            _stub(name)

    # voluptuous ships with Home Assistant.
    class _Schema:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __call__(self, *args: object, **kwargs: object) -> "_Schema":
            return self

    _stub(
        "voluptuous",
        Schema=_Schema,
        Required=lambda *a, **k: None,
        Optional=lambda *a, **k: None,
        All=lambda *a, **k: None,
        Coerce=lambda *a, **k: None,
        PLATFORM_SCHEMA=_Schema(),
    )

    # aiohttp ships with Home Assistant.
    class ClientError(Exception):
        pass

    class ClientTimeout:
        def __init__(self, total: float | None = None) -> None:
            self.total = total

    _stub("aiohttp", ClientError=ClientError, ClientTimeout=ClientTimeout)

    _generic = type("_G", (), {"__class_getitem__": classmethod(lambda c, i: c)})

    class DataUpdateCoordinator(_generic):  # type: ignore[misc, valid-type]
        def __init__(
            self, hass, logger, *, name=None, update_interval=None, config_entry=None
        ) -> None:
            self.hass = hass
            self.config_entry = config_entry

    class CoordinatorEntity(_generic):  # type: ignore[misc, valid-type]
        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

    class ImageEntity(_generic):  # type: ignore[misc, valid-type]
        def __init__(self, hass, verify_ssl: bool = False) -> None:
            self.hass = hass

        def async_write_ha_state(self) -> None:
            pass

    sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (  # type: ignore[attr-defined]
        DataUpdateCoordinator
    )
    sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = (  # type: ignore[attr-defined]
        CoordinatorEntity
    )
    sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = (  # type: ignore[attr-defined]
        type("UpdateFailed", (Exception,), {})
    )
    sys.modules["homeassistant.components.image"].ImageEntity = ImageEntity  # type: ignore[attr-defined]

    # ConfigFlow accepts `class X(ConfigFlow, domain=...)`, which needs a
    # __init_subclass__ that tolerates keyword arguments.
    class ConfigFlow:
        VERSION = 1

        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__()

    class OptionsFlow:
        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__()

    config_entries = sys.modules["homeassistant.config_entries"]
    config_entries.ConfigEntry = object  # type: ignore[attr-defined]
    config_entries.ConfigFlow = ConfigFlow  # type: ignore[attr-defined]
    config_entries.OptionsFlow = OptionsFlow  # type: ignore[attr-defined]
    config_entries.ConfigFlowResult = dict  # type: ignore[attr-defined]
    sys.modules["homeassistant.core"].HomeAssistant = object  # type: ignore[attr-defined]

    dt_util = types.ModuleType("homeassistant.util.dt")
    dt_util.get_time_zone = lambda name: ZoneInfo(name)  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_util
    sys.modules["homeassistant.util"].dt = dt_util  # type: ignore[attr-defined]

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        translation_key: str | None = None
        entity_category: object = None
        device_class: object = None
        state_class: object = None
        entity_registry_enabled_default: bool = True

    sensor = sys.modules["homeassistant.components.sensor"]
    sensor.SensorEntityDescription = SensorEntityDescription  # type: ignore[attr-defined]
    sensor.SensorEntity = type("SensorEntity", (), {})  # type: ignore[attr-defined]
    sensor.SensorDeviceClass = types.SimpleNamespace(TIMESTAMP="timestamp")  # type: ignore[attr-defined]
    sensor.SensorStateClass = types.SimpleNamespace(  # type: ignore[attr-defined]
        MEASUREMENT="measurement"
    )
    sys.modules["homeassistant.const"].EntityCategory = types.SimpleNamespace(  # type: ignore[attr-defined]
        DIAGNOSTIC="diagnostic"
    )
    sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = (  # type: ignore[attr-defined]
        object
    )

    validation = types.ModuleType("homeassistant.helpers.config_validation")
    validation.string = str  # type: ignore[attr-defined]
    validation.positive_int = int  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.config_validation"] = validation

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client


def _register_package() -> None:
    """Expose the component under a stable name for relative imports."""
    pkg = types.ModuleType("hacs_nmf")
    pkg.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
    sys.modules["hacs_nmf"] = pkg


class TestModulesImport(unittest.TestCase):
    """Every module must import; a bad name breaks the whole integration."""

    @classmethod
    def setUpClass(cls) -> None:
        _install_stubs()
        _register_package()

    def test_every_module_imports(self) -> None:
        failures: list[str] = []
        for name in MODULES:
            try:
                importlib.import_module(f"hacs_nmf.{name}")
            except Exception as err:  # noqa: BLE001 - report any import error
                failures.append(f"{name}: {type(err).__name__}: {err}")
        self.assertEqual(
            failures,
            [],
            "integration modules failed to import:\n  " + "\n  ".join(failures),
        )

    def test_const_defines_shared_keys(self) -> None:
        const = importlib.import_module("hacs_nmf.const")
        for key in ("CONF_ZONE_ID", "CONF_NAME", "CONF_SCAN_INTERVAL", "DOMAIN"):
            self.assertTrue(
                hasattr(const, key), f"const.py is missing {key}"
            )

    def test_config_flow_class_shape(self) -> None:
        """The flow classes must exist with the names HA looks for."""
        config_flow = importlib.import_module("hacs_nmf.config_flow")
        self.assertTrue(
            hasattr(config_flow, "MarineForecastConfigFlow")
        )
        self.assertTrue(
            hasattr(config_flow, "MarineForecastOptionsFlow")
        )


if __name__ == "__main__":
    unittest.main()
