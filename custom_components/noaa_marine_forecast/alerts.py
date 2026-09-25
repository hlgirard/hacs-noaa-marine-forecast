"""Normalization of NWS API (CAP) marine alerts.

Pure Python so it can be unit tested without Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from .flags import (
    FLAG_NONE,
    FLAG_TITLES,
    flag_for_event,
    is_ignored_event,
    is_marine_event,
    normalize_event_name,
)

__all__ = [
    "NormalizedAlert",
    "AlertBundle",
    "normalize_alert",
    "build_alert_bundle",
    "parse_alert_payload",
    "format_alert_window",
    "format_alert_text",
    "select_top_alert",
    "top_alert_detail",
]

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_PENDING = "pending"


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp into an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime | None) -> str | None:
    """Return an ISO 8601 string for a datetime."""
    return value.isoformat() if value else None


@dataclass(frozen=True)
class NormalizedAlert:
    """A single marine alert."""

    event: str
    event_slug: str
    alert_id: str
    lifecycle: str
    flag: str | None
    headline: str | None
    status: str | None
    message_type: str | None
    severity: str | None
    certainty: str | None
    urgency: str | None
    category: str | None
    area: str | None
    sent: datetime | None
    onset: datetime | None
    effective: datetime | None
    expires: datetime | None
    ends: datetime | None
    sender_name: str | None

    @property
    def effective_end(self) -> datetime | None:
        """Return the best known end of the alert."""
        return self.ends or self.expires

    def as_attributes(self) -> dict[str, object]:
        """Return a compact representation for entity attributes."""
        return {
            "event": self.event,
            "event_slug": self.event_slug,
            "lifecycle": self.lifecycle,
            "flag": self.flag,
            "headline": self.headline,
            "severity": self.severity,
            "urgency": self.urgency,
            "certainty": self.certainty,
            "status": self.status,
            "area": self.area,
            "onset": _iso(self.onset),
            "effective": _iso(self.effective),
            "expires": _iso(self.expires),
            "ends": _iso(self.ends),
        }


@dataclass(frozen=True)
class AlertBundle:
    """Active and pending marine alerts for a zone."""

    active: tuple[NormalizedAlert, ...] = ()
    pending: tuple[NormalizedAlert, ...] = ()
    other: tuple[NormalizedAlert, ...] = ()
    active_flags: tuple[str, ...] = ()
    pending_flags: tuple[str, ...] = ()
    highest_flag: str = FLAG_NONE
    highest_lifecycle: str | None = None

    @property
    def all_marine(self) -> tuple[NormalizedAlert, ...]:
        """Return every recognized marine alert, active first."""
        return self.active + self.pending

    @property
    def combination(self) -> str:
        """Return the dashboard friendly flag combination string."""
        from .flags import format_flag_combination

        return format_flag_combination(self.active_flags, self.pending_flags)


def parse_alert_payload(payload: dict | None) -> list[dict]:
    """Return the feature properties from a GeoJSON alert collection."""
    if not isinstance(payload, dict):
        return []
    features = payload.get("features")
    if not isinstance(features, list):
        return []
    properties: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if isinstance(props, dict):
            properties.append(props)
    return properties


def normalize_alert(
    props: dict, lifecycle: str, now: datetime | None = None
) -> NormalizedAlert:
    """Normalize a CAP ``properties`` object into a :class:`NormalizedAlert`."""
    now = now or datetime.now(timezone.utc)
    event = normalize_event_name(props.get("event"))
    slug = "_".join(event.lower().split()) or "unknown"
    return NormalizedAlert(
        event=event or str(props.get("event") or "Unknown"),
        event_slug=slug,
        alert_id=str(props.get("id") or ""),
        lifecycle=lifecycle,
        flag=flag_for_event(event),
        headline=props.get("headline") or None,
        status=props.get("status") or None,
        message_type=props.get("messageType") or props.get("message_type") or None,
        severity=props.get("severity") or None,
        certainty=props.get("certainty") or None,
        urgency=props.get("urgency") or None,
        category=props.get("category") or None,
        area=props.get("areaDesc") or None,
        sent=_parse_timestamp(props.get("sent")),
        onset=_parse_timestamp(props.get("onset")),
        effective=_parse_timestamp(props.get("effective")),
        expires=_parse_timestamp(props.get("expires")),
        ends=_parse_timestamp(props.get("ends")),
        sender_name=props.get("senderName") or None,
    )


def _is_expired(alert: NormalizedAlert, now: datetime) -> bool:
    """Return True when the alert is past both its end and expiry times."""
    end = alert.effective_end
    if end is None:
        return False
    return end < now - timedelta(minutes=15)


def _identity(alert: NormalizedAlert) -> tuple[str, str, str]:
    """Return a stable identity for de-duplicating repeated alert instances."""
    return (
        alert.event_slug,
        _iso(alert.onset) or "",
        _iso(alert.effective_end) or "",
    )


def build_alert_bundle(
    active_props: list[dict],
    zone_props: list[dict] | None = None,
    now: datetime | None = None,
) -> AlertBundle:
    """Build an :class:`AlertBundle` from active and zone-query payloads.

    ``active_props`` comes from ``/alerts/active/zone/{ZoneID}`` and is
    authoritative. ``zone_props`` comes from the zone filtered query and is
    used to discover future (pending) alerts, since the NWS API has no pending
    status.
    """
    now = now or datetime.now(timezone.utc)

    active: list[NormalizedAlert] = []
    for props in active_props:
        alert = normalize_alert(props, LIFECYCLE_ACTIVE, now)
        if is_ignored_event(alert.event) or not is_marine_event(alert.event):
            continue
        active.append(alert)

    seen = {_identity(alert) for alert in active}
    pending: list[NormalizedAlert] = []
    for props in zone_props or []:
        alert = normalize_alert(props, LIFECYCLE_PENDING, now)
        if is_ignored_event(alert.event) or not is_marine_event(alert.event):
            continue
        if _is_expired(alert, now):
            continue
        if _identity(alert) in seen:
            continue
        # Without an onset the alert is treated as pending; otherwise it must
        # start in the future, since currently effective alerts are already
        # reported as active.
        if alert.onset is not None and alert.onset <= now:
            continue
        seen.add(_identity(alert))
        pending.append(alert)

    def _flag_set(alerts: list[NormalizedAlert]) -> tuple[str, ...]:
        flags: list[str] = []
        for alert in alerts:
            if alert.flag and alert.flag not in flags:
                flags.append(alert.flag)
        return tuple(flags)

    active_flags = _flag_set(active)
    pending_flags = _flag_set(pending)

    from .flags import highest_flag

    highest, lifecycle = highest_flag(active_flags, pending_flags)

    other = tuple(
        alert for alert in (*active, *pending) if alert.flag is None
    )

    return AlertBundle(
        active=tuple(active),
        pending=tuple(pending),
        other=other,
        active_flags=active_flags,
        pending_flags=pending_flags,
        highest_flag=highest,
        highest_lifecycle=lifecycle,
    )


def format_alert_window(end: datetime | None, tz: tzinfo | None = None) -> str:
    """Return a compact local-time end window such as ``Saturday 8pm``.

    Minutes are dropped on the hour and kept otherwise. Returns an empty
    string when the end time is unknown, so callers can fall back to a bare
    title rather than printing a dangling "until".

    ``tz`` is the Home Assistant configured timezone; when omitted the value
    is formatted in whatever timezone ``end`` already carries.
    """
    if end is None:
        return ""
    local = end.astimezone(tz) if tz is not None else end
    hour = local.strftime("%I").lstrip("0") or "12"
    minutes = "" if local.minute == 0 else f":{local.minute:02d}"
    suffix = "am" if local.hour < 12 else "pm"
    return f"{local:%A} {hour}{minutes}{suffix}"


def select_top_alert(bundle: AlertBundle) -> NormalizedAlert | None:
    """Return the alert that drives the highest flag, or None when clear.

    The window and detail text must come from the alert that actually drives
    the flag rather than the first alert in the bundle: a pending hurricane
    outranks an active gale warning, and pairing the hurricane title with the
    gale's end time would be wrong.
    """
    if bundle.highest_flag == FLAG_NONE:
        return None
    alerts = bundle.all_marine
    top = next((a for a in alerts if a.flag == bundle.highest_flag), None)
    return top if top is not None else (alerts[0] if alerts else None)


def top_alert_detail(bundle: AlertBundle) -> dict[str, object] | None:
    """Return a dashboard-ready detail dict for the flag-driving alert."""
    top = select_top_alert(bundle)
    if top is None:
        return None
    return {
        "flag": top.flag,
        "flag_title": FLAG_TITLES.get(top.flag or FLAG_NONE, top.flag),
        "lifecycle": top.lifecycle,
        "severity": top.severity,
        "headline": top.headline,
        "area": top.area,
        "onset": _iso(top.onset),
        "ends": _iso(top.effective_end),
    }


def format_alert_text(bundle: AlertBundle, tz: tzinfo | None = None) -> str | None:
    """Return a one line summary of the highest flag, or None when clear.

    The window is taken from the alert that actually drives the flag rather
    than the first alert in the bundle: a pending hurricane outranks an active
    gale warning, and pairing the hurricane title with the gale's end time
    would be wrong.
    """
    if bundle.highest_flag == FLAG_NONE:
        return None
    title = FLAG_TITLES.get(bundle.highest_flag)
    if title is None:
        return None
    top = select_top_alert(bundle)
    window = format_alert_window(top.effective_end if top else None, tz)
    return f"{title} until {window}" if window else title
