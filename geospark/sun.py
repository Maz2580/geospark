"""Sun position, sunrise and sunset, shadows, and hours of direct sun.

The position follows NOAA's solar calculator (after Meeus, *Astronomical Algorithms*): declination,
equation of time and hour angle from the Julian century, with NOAA's atmospheric refraction
correction for the apparent elevation. Sunrise and sunset are when the Sun's upper limb meets a flat
horizon (zenith 90.833°: refraction 34' plus the solar radius 16'). Checked against NREL's Solar
Position Algorithm (Reda and Andreas, 2004): see ``docs/benchmarks/2026-10/sun_horizon.md``.

With ``terrain=True``, hours of direct sun compare the Sun's elevation with the terrain horizon from
``geospark.visibility.horizon``: a valley floor gets less sun than the flat-horizon times suggest.

    sun_position(-37.818, 144.969, "2026-12-21T12:00:00+11:00")
    sun_times(-37.818, 144.969, "2026-12-21", tz="Australia/Melbourne")
    shadow(-37.818, 144.969, "2026-06-21T12:00:00+10:00", object_height_m=10)
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

METHOD = "NOAA solar position (Meeus)"
SUNRISE_ZENITH = 90.833  # degrees: refraction at the horizon (34') plus the solar semi-diameter (16')
SEMI_DIAMETER = 0.2667  # degrees: the upper limb shows when the apparent centre is this far below a skyline


class SunError(ValueError):
    pass


def _check(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise SunError("Latitude must be -90..90 and longitude -180..180.")


def _when(when: str | datetime, tz: str | None) -> datetime:
    """An aware datetime: an ISO string or datetime with an offset, or a local one with tz=."""
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            raise SunError(f"Give the time as ISO 8601, e.g. 2026-12-21T12:00:00+11:00; got {when!r}.") from None
    if when.tzinfo is None:
        if tz is None:
            raise SunError("The time has no UTC offset: add one (e.g. +11:00) or pass tz (e.g. Australia/Melbourne).")
        when = when.replace(tzinfo=_zone(tz))
    return when


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise SunError(f"Unknown time zone {tz!r}; use an IANA name such as Australia/Melbourne.") from None


def _julian_century(t: datetime) -> float:
    t = t.astimezone(timezone.utc)
    jd = (t - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400 + 2451545.0
    return (jd - 2451545.0) / 36525.0


def _declination_eot(jc: float) -> tuple[float, float]:
    """Solar declination (degrees) and the equation of time (minutes) at a Julian century."""
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * jc) + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * jc)
    apparent = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.degrees(math.asin(math.sin(eps) * math.sin(apparent)))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eot = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eot


def _refraction(elevation: float) -> float:
    """NOAA's refraction correction (degrees) for a true elevation in degrees."""
    if elevation > 85:
        return 0.0
    te = math.tan(math.radians(elevation))
    if elevation > 5:
        arcsec = 58.1 / te - 0.07 / te**3 + 0.000086 / te**5
    elif elevation > -0.575:
        arcsec = 1735 + elevation * (-518.2 + elevation * (103.4 + elevation * (-12.79 + elevation * 0.711)))
    else:
        arcsec = -20.774 / te
    return arcsec / 3600


def _bennett(skyline_deg: float) -> float:
    """Refraction (degrees) of light arriving at an apparent elevation, Bennett's formula: 34.5' at 0°."""
    h = max(skyline_deg, -1.0)
    return 1 / math.tan(math.radians(h + 7.31 / (h + 4.4))) / 60


def _visible(true_elevation: float, skyline_deg: float) -> bool:
    """Whether the Sun's upper limb shows above a skyline (an apparent angle): on a flat horizon this is
    true elevation > -0.833°, the sunrise definition."""
    return true_elevation + _bennett(skyline_deg) + SEMI_DIAMETER > skyline_deg


def _true_elevation(lat: float, lon: float, t: datetime) -> tuple[float, float]:
    """(true elevation, azimuth) without refraction, for horizon tests."""
    apparent, azimuth, _d, _e = _position(lat, lon, t)
    # Undo NOAA's correction: iterate true = apparent - R(true)
    true = apparent
    for _ in range(3):
        true = apparent - _refraction(true)
    return true, azimuth


def _position(lat: float, lon: float, t: datetime) -> tuple[float, float, float, float]:
    """(apparent elevation, azimuth from north, declination, equation of time) for an aware time."""
    decl, eot = _declination_eot(_julian_century(t))
    u = t.astimezone(timezone.utc)
    minutes = u.hour * 60 + u.minute + u.second / 60 + u.microsecond / 6e7
    true_solar = (minutes + eot + 4 * lon) % 1440
    hour_angle = true_solar / 4 - 180
    la, de, ha = math.radians(lat), math.radians(decl), math.radians(hour_angle)
    cos_zen = max(-1.0, min(1.0, math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha)))
    zenith = math.degrees(math.acos(cos_zen))
    elevation = 90 - zenith
    zr = math.radians(zenith)
    denom = math.cos(la) * math.sin(zr)
    if abs(denom) < 1e-12:  # at a pole, or the Sun at the zenith
        azimuth = 180.0 if lat > 0 else 0.0
    else:
        cos_az = max(-1.0, min(1.0, (math.sin(la) * math.cos(zr) - math.sin(de)) / denom))
        azimuth = (math.degrees(math.acos(cos_az)) + 180) % 360 if hour_angle > 0 else (540 - math.degrees(math.acos(cos_az))) % 360
    return elevation + _refraction(elevation), azimuth, decl, eot


def _provenance() -> dict[str, Any]:
    return {"source": METHOD, "method": "NOAA Solar Calculator equations (Meeus, Astronomical Algorithms)",
            "licence": "computed locally"}


def sun_position(latitude: float, longitude: float, when: str | datetime, tz: str | None = None) -> dict[str, Any]:
    """The Sun's apparent elevation and azimuth (degrees clockwise from true north) at a time."""
    _check(latitude, longitude)
    t = _when(when, tz)
    elevation, azimuth, decl, eot = _position(latitude, longitude, t)
    return {
        "time": t.isoformat(), "elevation_deg": round(elevation, 4), "azimuth_deg": round(azimuth, 4),
        "declination_deg": round(decl, 4), "equation_of_time_min": round(eot, 3),
        "above_horizon": _visible(_true_elevation(latitude, longitude, t)[0], 0.0),
        "method": METHOD, "provenance": [_provenance()],
        "warnings": ["Elevation includes atmospheric refraction (standard atmosphere); azimuth is from true north, "
                     "not magnetic north."],
    }


def _event(lat: float, lon: float, day: date, zenith: float, rising: bool) -> datetime | None:
    """UTC time the Sun crosses ``zenith`` on a UTC day, iterated on the declination at that time."""
    t = datetime.combine(day, time(12), tzinfo=timezone.utc)
    for _ in range(3):
        decl, eot = _declination_eot(_julian_century(t))
        la, de = math.radians(lat), math.radians(decl)
        cos_ha = (math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(de))) - math.tan(la) * math.tan(de)
        if not -1 <= cos_ha <= 1:
            return None
        ha = math.degrees(math.acos(cos_ha))
        minutes = 720 - 4 * (lon + (ha if rising else -ha)) - eot
        t = datetime.combine(day, time(0), tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return t


def sun_times(latitude: float, longitude: float, day: str | date, tz: str | None = None) -> dict[str, Any]:
    """Sunrise, solar noon and sunset on a local date, for a flat horizon."""
    _check(latitude, longitude)
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            raise SunError(f"Give the date as YYYY-MM-DD; got {day!r}.") from None
    zone = _zone(tz) if tz else timezone.utc
    local_noon = datetime.combine(day, time(12), tzinfo=zone)
    # The UTC day containing local noon; events are then found near it
    utc_day = local_noon.astimezone(timezone.utc).date()
    _decl, eot = _declination_eot(_julian_century(local_noon))
    noon = datetime.combine(utc_day, time(0), tzinfo=timezone.utc) + timedelta(minutes=720 - 4 * longitude - eot)
    rise = _event(latitude, longitude, utc_day, SUNRISE_ZENITH, True)
    sets = _event(latitude, longitude, utc_day, SUNRISE_ZENITH, False)
    noon_elev = _position(latitude, longitude, noon)[0]
    out: dict[str, Any] = {"date": day.isoformat(), "time_zone": tz or "UTC",
                           "solar_noon": noon.astimezone(zone).isoformat(timespec="seconds"),
                           "solar_noon_elevation_deg": round(noon_elev, 3)}
    if rise is None or sets is None:
        polar = "polar day: the Sun does not set" if noon_elev > 0 else "polar night: the Sun does not rise"
        out.update(sunrise=None, sunset=None, day_length_h=24.0 if noon_elev > 0 else 0.0, note=polar)
    else:
        out.update(sunrise=rise.astimezone(zone).isoformat(timespec="seconds"),
                   sunset=sets.astimezone(zone).isoformat(timespec="seconds"),
                   day_length_h=round((sets - rise).total_seconds() / 3600, 3))
    out.update(method=METHOD, provenance=[_provenance()],
               warnings=["Sunrise and sunset are for a flat, sea-level horizon (zenith 90.833°); hills and buildings "
                         "delay sunrise and advance sunset. Use sunlight_hours with terrain for the local horizon."])
    return out


def shadow(latitude: float, longitude: float, when: str | datetime, object_height_m: float,
           tz: str | None = None) -> dict[str, Any]:
    """Length and direction of the shadow a vertical object casts on level ground."""
    if object_height_m <= 0:
        raise SunError("The object height must be positive.")
    pos = sun_position(latitude, longitude, when, tz)
    elev = pos["elevation_deg"]
    out = {**pos, "object_height_m": object_height_m}
    if elev <= 0:
        out.update(shadow_length_m=None, shadow_direction_deg=None,
                   note="The Sun is below the horizon: there is no direct shadow.")
    else:
        out.update(shadow_length_m=round(object_height_m / math.tan(math.radians(elev)), 3),
                   shadow_direction_deg=round((pos["azimuth_deg"] + 180) % 360, 4))
    out["warnings"] = pos["warnings"] + ["The shadow is on level ground; slopes lengthen or shorten it."]
    return out


def sunlight_hours(latitude: float, longitude: float, day: str | date, tz: str | None = None,
                   terrain: bool = True, observer_height_m: float = 1.5, step_min: int = 2) -> dict[str, Any]:
    """Hours of direct sun on a date: above a flat horizon, and (terrain=True) above the terrain horizon."""
    _check(latitude, longitude)
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            raise SunError(f"Give the date as YYYY-MM-DD; got {day!r}.") from None
    zone = _zone(tz) if tz else timezone.utc
    start = datetime.combine(day, time(0), tzinfo=zone)
    times = [start + timedelta(minutes=m) for m in range(0, 24 * 60, step_min)]
    path = [(t, *_true_elevation(latitude, longitude, t)) for t in times]
    flat = [p for p in path if _visible(p[1], 0.0)]
    out: dict[str, Any] = {"date": day.isoformat(), "time_zone": tz or "UTC",
                           "flat_horizon_hours": round(len(flat) * step_min / 60, 2)}
    provenance = [_provenance()]
    warnings = [f"Sampled every {step_min} minutes."]
    if terrain:
        from geospark import visibility

        hz = visibility.horizon(latitude, longitude, observer_height_m=observer_height_m)
        az = hz["azimuths_deg"]
        angles = hz["horizon_elevation_deg"]
        step = az[1] - az[0]

        def blocked(azimuth: float) -> float:
            i = azimuth / step
            j, f = int(i) % len(az), i - int(i)
            return float(angles[j] * (1 - f) + angles[(j + 1) % len(az)] * f)

        lit = [p for p in path if _visible(p[1], max(blocked(p[2]), 0.0))]
        out.update(terrain_hours=round(len(lit) * step_min / 60, 2),
                   first_direct_sun=lit[0][0].isoformat(timespec="minutes") if lit else None,
                   last_direct_sun=lit[-1][0].isoformat(timespec="minutes") if lit else None,
                   ground_elevation_m=hz["ground_elevation_m"])
        provenance += hz["provenance"]
        warnings += hz["warnings"]
    out.update(method=METHOD, provenance=provenance, warnings=warnings)
    return out
