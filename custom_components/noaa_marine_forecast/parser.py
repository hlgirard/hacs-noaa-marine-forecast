"""Parser for NOAA coastal waters forecast text products.

The parser is pure Python (no Home Assistant imports) so that it can be unit
tested against captured NOAA products.

Layout of a typical product::

    Expires:202609260300;;034305
    FZUS51 KBOX 251404
    CWFBOX

    Coastal Waters Forecast for Massachusetts and Rhode Island
    National Weather Service Boston/Norton MA
    1003 AM EDT Fri Sep 25 2026

    Coastal waters from the Merrimack River MA to Watch Hill RI out
    to 60 NM


    ANZ230-260300-
    Boston Harbor-
    1003 AM EDT Fri Sep 25 2026

    ...STORM WARNING IN EFFECT FROM 2 PM EDT THIS AFTERNOON THROUGH
    SATURDAY EVENING...

    .THIS AFTERNOON...NE winds around 20 kt with gusts up to 30 kt.
    .TONIGHT...NE winds 20 to 25 kt with gusts up to 40 kt. Waves
    .SAT...NE winds 20 to 25 kt, increasing to 25 to 30 kt in the
    .SAT NIGHT...NE winds 25 to 30 kt with gusts up to 55 kt.

    Seas are reported as significant wave height, which is the
    average of the highest third of the waves.

    $$
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from .const import (
    AFTERNOON_PERIOD_START,
    DAY_PERIOD_START,
    FULL_DAY_END,
    FULL_DAY_START,
    MORNING_PERIOD_END,
    NIGHT_PERIOD_END,
    NIGHT_PERIOD_START,
    TZ_ABBREVIATIONS,
)

__all__ = [
    "ForecastPeriod",
    "ForecastProduct",
    "parse_forecast",
    "select_now_next",
]

UTC = timezone.utc

EXPIRES_RE = re.compile(r"^Expires:\s*(?P<stamp>\d{12})")
WMO_RE = re.compile(
    r"^(?P<wmo>[A-Z]{4}\d{2})\s+(?P<office>[A-Z]{4})\s+(?P<stamp>\d{6}Z?)\s*$"
)
AWIPS_RE = re.compile(r"^(?P<awips>(?:CW[A-Z]{2,5}|[A-Z]{2,3}W[A-Z]{2,4}))\d*$")
OFFICE_RE = re.compile(r"^National Weather Service\b", re.IGNORECASE)
ISSUE_TIME_RE = re.compile(
    r"^(?P<clock>\d{1,2}:\d{2}|\d{3,4})\s+(?P<ampm>[AP]M)\s+"
    r"(?P<tz>[A-Z]{1,5})\s+"
    r"(?P<dow>[A-Za-z]{3,9})\s+(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})\s+"
    r"(?P<year>\d{4})\s*$"
)
ZONE_GROUP_RE = re.compile(
    r"^(?P<ids>[A-Z]{3}\d{3}(?:-\d{3})*)-(?P<stamp>\d{6}Z?)-?$"
)
PERIOD_RE = re.compile(r"^\.(?P<label>[A-Z0-9][A-Z0-9 ,.'\-/]{0,60}?)\.\.\.\s?")
HAZARD_RE = re.compile(r"^\.\.\.")

WEEKDAYS: dict[str, int] = {
    "MON": 0,
    "MONDAY": 0,
    "TUE": 1,
    "TUES": 1,
    "TUESDAY": 1,
    "WED": 2,
    "WEDNESDAY": 2,
    "THU": 3,
    "THUR": 3,
    "THURS": 3,
    "THURSDAY": 3,
    "FRI": 4,
    "FRIDAY": 4,
    "SAT": 5,
    "SATURDAY": 5,
    "SUN": 6,
    "SUNDAY": 6,
}

MONTHS: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

PART_DAY = "day"
PART_NIGHT = "night"
PART_ALL = "all"


@dataclass(frozen=True)
class ForecastPeriod:
    """A single normalized forecast period."""

    source_label: str
    text: str
    order: int
    period_date: date | None = None
    part: str = PART_ALL
    start_time: time = FULL_DAY_START
    end_time: time = FULL_DAY_END
    end_next_day: bool = False

    def window(self, tz: tzinfo) -> tuple[datetime, datetime]:
        """Return the nominal (approximate) window for this period."""
        if self.period_date is None:
            raise ValueError("period has no date")
        start = datetime.combine(self.period_date, self.start_time, tzinfo=tz)
        end_day = self.period_date + (timedelta(days=1) if self.end_next_day else timedelta())
        end = datetime.combine(end_day, self.end_time, tzinfo=tz)
        return start, end

    def covers(self, moment: datetime, tz: tzinfo) -> bool:
        """Return True when moment falls inside the nominal period window."""
        try:
            start, end = self.window(tz)
        except ValueError:
            return False
        local = moment.astimezone(tz)
        return start <= local < end

    @property
    def is_day(self) -> bool:
        """Return True when the period is a daytime period."""
        return self.part == PART_DAY

    @property
    def is_night(self) -> bool:
        """Return True when the period is a nighttime period."""
        return self.part == PART_NIGHT


@dataclass(frozen=True)
class ForecastProduct:
    """A parsed NOAA marine forecast product."""

    raw_text: str
    zones: tuple[str, ...] = ()
    zone_names: tuple[str, ...] = ()
    periods: tuple[ForecastPeriod, ...] = ()
    wmo_id: str | None = None
    awips_id: str | None = None
    office: str | None = None
    office_name: str | None = None
    product_title: str | None = None
    raw_header: str | None = None
    issued: datetime | None = None
    expires: datetime | None = None
    tz_abbreviation: str | None = None
    area_description: str | None = None
    hazard_summary: str | None = None
    additional_text: str | None = None
    zone_id: str | None = None
    parse_errors: tuple[str, ...] = field(default=())

    @property
    def timezone(self) -> tzinfo | None:
        """Return the IANA timezone of the issuing office, when known."""
        if not self.tz_abbreviation:
            return None
        iana = TZ_ABBREVIATIONS.get(self.tz_abbreviation)
        if iana is None:
            return None
        try:
            return ZoneInfo(iana)
        except Exception:  # pragma: no cover - defensive
            return None

    def zone_name(self) -> str | None:
        """Return the human readable name for the configured zone."""
        if not self.zone_id or not self.zone_names:
            return None
        wanted = self.zone_id.upper()
        for index, zone in enumerate(self.zones):
            if zone == wanted and index < len(self.zone_names):
                return self.zone_names[index]
        return None

    def periods_by_part(self) -> dict[tuple[date, str], ForecastPeriod]:
        """Return a lookup of (date, part) -> first matching period."""
        lookup: dict[tuple[date, str], ForecastPeriod] = {}
        for period in self.periods:
            if period.period_date is None:
                continue
            key = (period.period_date, period.part)
            lookup.setdefault(key, period)
        return lookup


def _clean_lines(text: str) -> list[str]:
    """Return product lines with trailing whitespace removed."""
    return [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]


def _parse_wmo_stamp(stamp: str, now: datetime | None = None) -> datetime | None:
    """Parse a DDHHMM (UTC) product stamp.

    The stamp carries no month or year, so the year is chosen to keep the
    result as close to ``now`` as possible.
    """
    if len(stamp) < 6:
        return None
    try:
        day = int(stamp[0:2])
        hour = int(stamp[2:4])
        minute = int(stamp[4:6])
    except ValueError:
        return None
    reference = now or datetime.now(UTC)
    candidates: list[datetime] = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(
                datetime(year, 1, 1, tzinfo=UTC)
                + timedelta(days=day - 1, hours=hour, minutes=minute)
            )
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item - reference))


def _parse_expires_stamp(stamp: str) -> datetime | None:
    """Parse a YYYYMMDDHHMM expiration stamp (UTC)."""
    try:
        return datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_clock(clock: str) -> tuple[int, int] | None:
    """Parse an NWS clock token such as ``1003``, ``734``, ``7:03`` or ``7``."""
    if ":" in clock:
        hour_str, _, minute_str = clock.partition(":")
    elif len(clock) == 4:
        hour_str, minute_str = clock[:2], clock[2:]
    elif len(clock) == 3:
        hour_str, minute_str = clock[:1], clock[1:]
    else:
        hour_str, minute_str = clock, "0"
    try:
        return int(hour_str), int(minute_str)
    except ValueError:
        return None


def _parse_issue_line(line: str) -> tuple[datetime, str] | None:
    """Parse a ``1003 AM EDT Fri Sep 25 2026`` line."""
    match = ISSUE_TIME_RE.match(line.strip())
    if not match:
        return None
    parts = match.groupdict()
    month = MONTHS.get(parts["month"][:3].upper())
    if month is None:
        return None
    parsed_clock = _parse_clock(parts["clock"])
    if parsed_clock is None:
        return None
    hour, minute = parsed_clock
    hour %= 12
    if parts["ampm"].upper() == "PM":
        hour += 12
    if hour > 23 or minute > 59:
        return None
    try:
        naive = datetime(
            int(parts["year"]), month, int(parts["day"]), hour, minute
        )
    except ValueError:
        return None
    tz_abbrev = parts["tz"].upper()
    tzinfo = ZoneInfo(TZ_ABBREVIATIONS.get(tz_abbrev, "UTC"))
    return naive.replace(tzinfo=tzinfo), tz_abbrev


def _zone_id_list(raw: str) -> tuple[str, ...]:
    """Expand ``GMZ130-132-135`` into ``("GMZ130", "GMZ132", "GMZ135")``."""
    parts = raw.split("-")
    prefix = parts[0][:3]
    zones: list[str] = []
    for position, part in enumerate(parts):
        if position == 0 and len(part) == 6:
            zones.append(part)
        else:
            zones.append(f"{prefix}{part}")
    return tuple(zones)


def _split_combined(label: str) -> list[str]:
    """Split ``SUN AND SUN NIGHT`` into its two logical labels."""
    if " AND " not in label:
        return [label]
    return [piece.strip() for piece in label.split(" AND ") if piece.strip()]


def _label_date_offset(label: str, reference: date) -> tuple[int, str, str]:
    """Return (day offset, part, refinement) for a period label.

    ``part`` is ``"day"`` for daytime periods, ``"night"`` for nighttime
    periods and ``"all"`` only when a label cannot be classified.
    """
    normalized = " ".join(label.upper().split())
    part = PART_DAY
    if normalized.endswith("NIGHT") or normalized in {"TONIGHT", "OVERNIGHT"}:
        part = PART_NIGHT

    offset: int | None = None
    if "TOMORROW" in normalized:
        offset = 1
    elif "TODAY" in normalized:
        offset = 0
    else:
        for token in normalized.split():
            token = token.strip(".,")
            if token in WEEKDAYS:
                offset = (WEEKDAYS[token] - reference.weekday()) % 7
                break

    if offset is None:
        offset = 0

    refinement = "full"
    if "AFTERNOON" in normalized:
        refinement = "afternoon"
    elif "MORNING" in normalized:
        refinement = "morning"
    elif normalized == "OVERNIGHT":
        refinement = "overnight"
    elif part == PART_NIGHT:
        refinement = "night"

    if part == PART_ALL:
        refinement = "full"
    return offset, part, refinement


def _period_times(
    part: str, refinement: str
) -> tuple[time, time, bool]:
    """Return (start, end, end_next_day) for a period."""
    if part == PART_NIGHT and refinement == "overnight":
        return FULL_DAY_START, NIGHT_PERIOD_END, False
    if part == PART_NIGHT:
        return NIGHT_PERIOD_START, NIGHT_PERIOD_END, True
    if refinement == "afternoon":
        return AFTERNOON_PERIOD_START, NIGHT_PERIOD_START, False
    if refinement == "morning":
        return DAY_PERIOD_START, MORNING_PERIOD_END, False
    if part == PART_DAY:
        return DAY_PERIOD_START, NIGHT_PERIOD_START, False
    return FULL_DAY_START, FULL_DAY_END, False


def _make_period(
    label: str, text: str, order: int, reference: date
) -> ForecastPeriod:
    """Build a normalized period from a raw label."""
    offset, part, refinement = _label_date_offset(label, reference)
    start, end, end_next_day = _period_times(part, refinement)
    return ForecastPeriod(
        source_label=label,
        text=text,
        order=order,
        period_date=reference + timedelta(days=offset),
        part=part,
        start_time=start,
        end_time=end,
        end_next_day=end_next_day,
    )


def _clean_period_text(lines: list[str]) -> str:
    """Join wrapped period lines into normalized whitespace."""
    text = " ".join(piece.strip() for piece in lines if piece.strip())
    return re.sub(r"\s+", " ", text).strip()


def _clean_hazard_text(lines: list[str]) -> str:
    """Join wrapped hazard lines and drop the ``...`` markers.

    A line starting with ``...`` opens a new hazard statement; other lines are
    continuations of the statement in progress.
    """
    statements: list[str] = []
    current: list[str] = []
    for piece in lines:
        text = piece.strip()
        if not text:
            continue
        starts_statement = text.startswith("...")
        if starts_statement:
            text = text[3:].strip()
        text = text.rstrip(".").strip()
        if not text:
            continue
        if starts_statement and current:
            statements.append(" ".join(current))
            current = []
        current.append(text)
    if current:
        statements.append(" ".join(current))
    return " | ".join(statement for statement in statements if statement)


def parse_forecast(
    raw_text: str, zone_id: str | None = None
) -> ForecastProduct:
    """Parse NOAA coastal forecast text into a :class:`ForecastProduct`."""
    lines = _clean_lines(raw_text)
    errors: list[str] = []

    wmo_id: str | None = None
    awips_id: str | None = None
    office: str | None = None
    raw_header: str | None = None
    expires: datetime | None = None
    issued: datetime | None = None
    tz_abbreviation: str | None = None
    product_title: str | None = None
    office_name: str | None = None
    area_description: str | None = None
    zones: tuple[str, ...] = ()
    zone_names: tuple[str, ...] = ()
    hazard_lines: list[str] = []
    additional_lines: list[str] = []
    periods: list[ForecastPeriod] = []

    index = 0
    total = len(lines)

    # 1. Optional Expires stamp.
    if index < total and EXPIRES_RE.match(lines[index].strip()):
        match = EXPIRES_RE.match(lines[index].strip())
        assert match is not None
        expires = _parse_expires_stamp(match.group("stamp"))
        index += 1

    # 2. WMO heading and AWIPS identifier.
    while index < total:
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        wmo_match = WMO_RE.match(stripped)
        if wmo_match:
            wmo_id = wmo_match.group("wmo")
            office = wmo_match.group("office")
            raw_header = stripped
            if issued is None:
                issued = _parse_wmo_stamp(wmo_match.group("stamp"))
            index += 1
            continue
        awips_match = AWIPS_RE.match(stripped)
        if awips_match and wmo_id:
            awips_id = awips_match.group("awips")
            index += 1
            continue
        break

    # 3. Title / office / issue time block.
    seen_issue = False
    while index < total:
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            if product_title and office_name and seen_issue:
                break
            continue
        if stripped == "$$" or ZONE_GROUP_RE.match(stripped):
            break
        if OFFICE_RE.match(stripped):
            office_name = stripped
            index += 1
            continue
        issue = _parse_issue_line(stripped)
        if issue:
            issued_datetime, tz_abbreviation = issue
            # The explicit issue-time line is always more precise than the
            # DDHHMM WMO stamp, which carries neither month nor year.
            issued = issued_datetime
            seen_issue = True
            index += 1
            continue
        if not product_title:
            product_title = stripped
        else:
            area_description = (
                f"{area_description} {stripped}" if area_description else stripped
            )
        index += 1

    # 4. Area description lines, then the zone grouping block.
    while index < total:
        stripped = lines[index].strip()
        zone_match = ZONE_GROUP_RE.match(stripped)
        if zone_match:
            zones = _zone_id_list(zone_match.group("ids"))
            index += 1
            break
        if stripped:
            area_description = (
                f"{area_description} {stripped}" if area_description else stripped
            )
        index += 1

    # Zone names follow the group line. Each name is terminated by a dash and
    # may wrap across several lines.
    name_buffer: list[str] = []
    while index < total:
        stripped = lines[index].strip()
        if not stripped:
            if name_buffer:
                zone_names = zone_names + (
                    _clean_period_text(name_buffer),
                )
            break
        if _parse_issue_line(stripped) or PERIOD_RE.match(stripped):
            break
        if name_buffer and name_buffer[0] and not stripped[0].isupper():
            break
        if stripped.endswith("-"):
            name_buffer.append(stripped[:-1].strip())
            zone_names = zone_names + (_clean_period_text(name_buffer),)
            name_buffer = []
            index += 1
            continue
        name_buffer.append(stripped)
        index += 1
    if name_buffer and not zone_names:
        zone_names = zone_names + (_clean_period_text(name_buffer),)

    # 5. Hazard preamble lines. Each hazard statement starts with "..." and may
    # wrap, so continuation lines are collected until a period marker or other
    # content is reached. Issue time lines and blanks are skipped.
    in_hazard = False
    while index < total:
        stripped = lines[index].strip()
        if not stripped or _parse_issue_line(stripped):
            index += 1
            continue
        if HAZARD_RE.match(stripped):
            hazard_lines.append(stripped)
            in_hazard = True
            index += 1
            continue
        if in_hazard and not PERIOD_RE.match(stripped):
            hazard_lines.append(stripped)
            index += 1
            continue
        break

    # 6. Periods. A period marker is ".LABEL..." at the start of a line.
    current_label: str | None = None
    current_lines: list[str] = []
    order = 0
    in_periods = False

    def flush() -> None:
        nonlocal order, current_label, current_lines
        if current_label is None:
            return
        text = _clean_period_text(current_lines)
        if not text:
            order += 1
            current_label, current_lines = None, []
            return
        reference = issued.date() if issued else datetime.now(UTC).date()
        for piece in _split_combined(current_label):
            periods.append(_make_period(piece, text, order, reference))
            order += 1
        current_label, current_lines = None, []

    while index < total:
        stripped = lines[index].strip()
        if stripped in {"$$", ""}:
            if in_periods:
                flush()
            if not stripped:
                index += 1
                continue
            break
        match = PERIOD_RE.match(lines[index].strip())
        if match:
            in_periods = True
            flush()
            current_label = match.group("label").strip()
            current_lines = [lines[index].strip()[match.end():]]
            index += 1
            continue
        if in_periods and current_label is not None:
            current_lines.append(stripped)
        elif in_periods:
            additional_lines.append(stripped)
        index += 1
    flush()

    hazard_summary = _clean_hazard_text(hazard_lines) or None
    additional_text = _clean_period_text(additional_lines) or None

    if not zones:
        errors.append("No marine zone group found in product text")

    return ForecastProduct(
        raw_text=raw_text,
        zones=zones,
        zone_names=zone_names,
        periods=tuple(periods),
        wmo_id=wmo_id,
        awips_id=awips_id,
        office=office,
        office_name=office_name,
        product_title=product_title,
        raw_header=raw_header,
        issued=issued,
        expires=expires,
        tz_abbreviation=tz_abbreviation,
        area_description=(area_description or "").strip() or None,
        hazard_summary=hazard_summary,
        additional_text=additional_text,
        zone_id=zone_id.upper() if zone_id else None,
        parse_errors=tuple(errors),
    )


def select_now_next(
    product: ForecastProduct,
    moment: datetime,
    fallback_tz: tzinfo | None = None,
) -> tuple[ForecastPeriod | None, ForecastPeriod | None, str]:
    """Return ``(now_period, next_period, selection_method)``.

    The current period is the one whose nominal window contains ``moment``.
    When the moment falls outside every window (for example a stale or
    short product), the first period that has not started yet is used, and
    failing that the final period in the product.
    """
    if not product.periods:
        return None, None, "no_periods"

    tzinfo = product.timezone or fallback_tz or timezone.utc
    if not isinstance(tzinfo, ZoneInfo):
        moment = moment.replace(tzinfo=tzinfo)
    local = moment.astimezone(tzinfo)

    for index, period in enumerate(product.periods):
        if period.covers(local, tzinfo):
            nxt = (
                product.periods[index + 1]
                if index + 1 < len(product.periods)
                else None
            )
            return period, nxt, "current_window"

    try:
        for index, period in enumerate(product.periods):
            start, _ = period.window(tzinfo)
            if start > local:
                nxt = (
                    product.periods[index + 1]
                    if index + 1 < len(product.periods)
                    else None
                )
                return period, nxt, "upcoming"
    except ValueError:
        pass

    last = len(product.periods) - 1
    return product.periods[last], None, "last_available"
