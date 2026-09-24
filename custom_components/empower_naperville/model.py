"""Pure validation and hourly statistics, with no Home Assistant dependencies."""
from datetime import datetime, timedelta, timezone
from math import fsum, isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .const import MAX_READINGS

UTC = timezone.utc
STEP = timedelta(minutes=15)


class InvalidSnapshot(ValueError):
    """Only fixed, non-sensitive messages may be raised here."""


def normalize(payload):
    if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload.get("version") != 1:
        raise InvalidSnapshot("Unsupported snapshot format.")
    start = payload.get("readsStartDate")
    values = payload.get("deliveredReads")
    if not isinstance(start, str) or len(start) > 64 or "T" not in start:
        raise InvalidSnapshot("Missing or invalid start timestamp.")
    try:
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidSnapshot("Invalid start timestamp.") from None
    if parsed.minute % 15 or parsed.second or parsed.microsecond:
        raise InvalidSnapshot("Timestamp must align to a 15-minute boundary.")
    if isinstance(values, str):
        if len(values) > MAX_READINGS * 24:
            raise InvalidSnapshot("Snapshot is too large.")
        try:
            values = [float(v.strip()) for v in values.split(",")]
        except ValueError:
            raise InvalidSnapshot("Invalid or empty reading interval.") from None
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_READINGS:
        raise InvalidSnapshot("Missing readings or snapshot too large.")
    clean = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidSnapshot("Readings must be numeric.")
        try:
            value = float(value)
        except OverflowError:
            raise InvalidSnapshot("Invalid reading magnitude.") from None
        if not isfinite(value) or value < 0 or value > 1_000_000:
            raise InvalidSnapshot("Readings must be finite non-negative kWh values.")
        clean.append(value)
    # Drop every unrecognized field, including identifiers.
    return {"version": 1, "readsStartDate": parsed.isoformat(), "deliveredReads": clean}


def first_utc(start, zone):
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidSnapshot("Invalid IANA time zone.") from None
    first = datetime.fromisoformat(start)
    if first.tzinfo is not None:
        return first.astimezone(UTC)
    candidates = set()
    for fold in (0, 1):
        candidate = first.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        if candidate.astimezone(tz).replace(tzinfo=None) == first:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise InvalidSnapshot("Start falls in an ambiguous or nonexistent DST hour; an explicit UTC offset is required.")
    return candidates.pop()


def prepare(payload, zone, label, previous=None, now=None):
    """Interpret labels as elapsed 15-minute intervals from the first instant."""
    data = normalize(payload)
    if label not in ("start", "end"):
        raise InvalidSnapshot("Select whether meter timestamps label interval starts or ends.")
    if previous:
        if data["readsStartDate"] != previous["readsStartDate"]:
            raise InvalidSnapshot("History start changed. Rolling or different-meter history requires reconciliation; nothing was imported.")
        if len(data["deliveredReads"]) < len(previous["deliveredReads"]):
            raise InvalidSnapshot("History is shorter than the accepted snapshot; nothing was imported.")
    try:
        first = first_utc(data["readsStartDate"], zone)
        latest = first + (len(data["deliveredReads"]) - 1) * STEP
    except (ValueError, OverflowError) as err:
        if isinstance(err, InvalidSnapshot):
            raise
        raise InvalidSnapshot("Timestamp is outside the supported range.") from None
    now = now or datetime.now(UTC)
    if latest > now + STEP:
        raise InvalidSnapshot("History extends into the future; check timestamp settings.")
    summary = {
        "count": len(data["deliveredReads"]),
        "first": first.isoformat(), "latest": latest.isoformat(),
        "latest_kwh": data["deliveredReads"][-1],
        "total_kwh": fsum(data["deliveredReads"]),
        "received": now.isoformat(),
    }
    return data, summary


def hourly_statistics(data, zone, label):
    """Recompute deterministic sums; repeated uploads replace the same hour rows."""
    first = first_utc(data["readsStartDate"], zone)
    if label == "end":
        first -= STEP
    buckets = {}
    for index, value in enumerate(data["deliveredReads"]):
        instant = first + index * STEP
        hour = instant.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(value)
    rows = []
    cumulative = 0.0
    for hour, values in sorted(buckets.items()):
        if len(values) != 4:
            continue  # Never turn a partial hour into a complete hour.
        energy = fsum(values)
        cumulative = fsum((cumulative, energy))
        rows.append({"start": hour, "state": energy, "sum": cumulative})
    return rows
