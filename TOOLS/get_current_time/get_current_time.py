from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, reset_tzpath


def _iso_text(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _load_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        bundled_tz_path = Path(__file__).resolve().parents[2] / "env" / "share" / "zoneinfo"
        if bundled_tz_path.exists():
            reset_tzpath([str(bundled_tz_path)])
            return ZoneInfo(timezone_name)
        raise


def run(args: dict, context: dict) -> dict:
    timezone_name = str((args or {}).get("timezone", "")).strip()
    if not timezone_name:
        raise ValueError("get_current_time 需要提供 timezone，且必须是 IANA 时区名。")

    try:
        tz = _load_timezone(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"无效时区：{timezone_name}。请使用 IANA 时区名，例如 Asia/Shanghai。") from exc

    local_now = datetime.now(tz)
    utc_now = local_now.astimezone(timezone.utc)
    offset = local_now.strftime("%z")
    offset_text = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset

    return {
        "tool_name": "get_current_time",
        "display_name": str((context or {}).get("tool", {}).get("display_name", "")).strip() or "获取指定时区时间",
        "timezone": timezone_name,
        "timezone_abbreviation": local_now.tzname() or "",
        "utc_offset": offset_text,
        "current_time": _iso_text(local_now),
        "local_time": {
            "iso8601": _iso_text(local_now),
            "rfc3339": _iso_text(local_now),
            "date": local_now.strftime("%Y-%m-%d"),
            "time": local_now.strftime("%H:%M:%S"),
        },
        "utc_time": {
            "iso8601": _iso_text(utc_now),
            "rfc3339": _iso_text(utc_now),
        },
        "unix_timestamp": int(local_now.timestamp()),
    }
