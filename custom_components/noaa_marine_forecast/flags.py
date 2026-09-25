"""Marine warning flag model.

This module is intentionally free of Home Assistant imports so that flag
ranking and formatting can be unit tested standalone.
"""

from __future__ import annotations

from typing import Final, Iterable

FLAG_NONE: Final = "none"
FLAG_SMALL_CRAFT_ADVISORY: Final = "small_craft_advisory"
FLAG_GALE_WARNING: Final = "gale_warning"
FLAG_STORM_WARNING: Final = "storm_warning"
FLAG_HURRICANE_WARNING: Final = "hurricane_warning"

#: Ordered from least to most severe.
FLAG_SEVERITY: Final[dict[str, int]] = {
    FLAG_NONE: 0,
    FLAG_SMALL_CRAFT_ADVISORY: 1,
    FLAG_GALE_WARNING: 2,
    FLAG_STORM_WARNING: 3,
    FLAG_HURRICANE_WARNING: 4,
}

FLAG_TITLES: Final[dict[str, str]] = {
    FLAG_NONE: "No marine warnings",
    FLAG_SMALL_CRAFT_ADVISORY: "Small Craft Advisory",
    FLAG_GALE_WARNING: "Gale Warning",
    FLAG_STORM_WARNING: "Storm Warning",
    FLAG_HURRICANE_WARNING: "Hurricane Warning",
}

#: NWS event names mapped onto the flags above.
FLAG_EVENT_ALIASES: Final[dict[str, str]] = {
    "SMALL CRAFT ADVISORY": FLAG_SMALL_CRAFT_ADVISORY,
    "SMALL CRAFT ADVISORIES": FLAG_SMALL_CRAFT_ADVISORY,
    "GALE WARNING": FLAG_GALE_WARNING,
    "STORM WARNING": FLAG_STORM_WARNING,
    "HURRICANE WARNING": FLAG_HURRICANE_WARNING,
    "HURRICANE FORCE WIND WARNING": FLAG_HURRICANE_WARNING,
}

#: Marine alerts that are surfaced as alerts but do not drive a flag image.
OTHER_MARINE_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "MARINE WEATHER STATEMENT",
        "MARINE DENSE FOG ADVISORY",
        "DENSE FOG ADVISORY",
        "HEAVY FREEZING SPRAY WARNING",
        "FREEZING SPRAY WARNING",
        "HAZARDOUS SEAS WARNING",
        "HAZARDOUS SEAS",
        "TROPICAL STORM WARNING",
        "TROPICAL STORM WATCH",
        "TROPICAL STORM ADVISORY",
        "HURRICANE WATCH",
        "HURRICANE LOCAL STATEMENT",
        "TORNADO WARNING",
        "TORNADO WATCH",
        "SEVERE THUNDERSTORM WARNING",
        "SEVERE THUNDERSTORM WATCH",
        "SPECIAL MARINE WARNING",
        "LOW WATER ADVISORY",
        "LOW MARINE WARNING",
    }
)

#: Events intentionally not treated as marine alerts or flags.
IGNORED_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "BEACH HAZARDS STATEMENT",
        "RIP CURRENT STATEMENT",
    }
)


def normalize_event_name(event: str | None) -> str:
    """Return an upper case, whitespace collapsed event name."""
    if not event:
        return ""
    return " ".join(event.upper().split())


def flag_for_event(event: str | None) -> str | None:
    """Return the flag key for an NWS event name, or None."""
    return FLAG_EVENT_ALIASES.get(normalize_event_name(event))


def is_ignored_event(event: str | None) -> bool:
    """Return True for events deliberately excluded from the integration."""
    return normalize_event_name(event) in IGNORED_EVENTS


def is_marine_event(event: str | None) -> bool:
    """Return True when the event is a recognized marine alert or flag."""
    name = normalize_event_name(event)
    if not name or name in IGNORED_EVENTS:
        return False
    return flag_for_event(name) is not None or name in OTHER_MARINE_EVENTS


def severity_of(flag: str | None) -> int:
    """Return the numeric severity of a flag key."""
    return FLAG_SEVERITY.get(flag or FLAG_NONE, 0)


def highest_flag(
    active_flags: Iterable[str], pending_flags: Iterable[str]
) -> tuple[str, str | None]:
    """Return the highest severity flag across active and pending flags.

    Both lifecycles are considered: a pending hurricane warning outranks an
    active gale warning. The returned lifecycle is ``"active"``, ``"pending"``
    or ``None`` when no flag is present.
    """
    candidates: list[tuple[str, str]] = [
        (flag, "active") for flag in active_flags if flag in FLAG_SEVERITY
    ]
    candidates += [
        (flag, "pending") for flag in pending_flags if flag in FLAG_SEVERITY
    ]
    if not candidates:
        return FLAG_NONE, None
    flag, lifecycle = max(candidates, key=lambda item: severity_of(item[0]))
    return flag, lifecycle


def format_flag_combination(
    active_flags: Iterable[str], pending_flags: Iterable[str]
) -> str:
    """Return a dashboard friendly combination string.

    Example: ``gale_warning:active | storm_warning:pending``. A flag that is
    already active is not repeated as pending. Returns ``none`` when no flags
    are active or pending.
    """
    active_set = {flag for flag in active_flags if flag in FLAG_SEVERITY}
    active = sorted(active_set, key=severity_of)
    pending = sorted(
        {
            flag
            for flag in pending_flags
            if flag in FLAG_SEVERITY and flag not in active_set
        },
        key=severity_of,
    )
    parts = [f"{flag}:active" for flag in active]
    parts += [f"{flag}:pending" for flag in pending]
    return " | ".join(parts) if parts else FLAG_NONE
