"""Detect of the nsud-decisions Source: validates the config, emits catalog items, never uses the network (P81-04).

Items: one per calendar month of decision dates (``nsud:2026-09``, window = the month), from ``max(annoFrom, 2005)`` to the current month; or, when ``ids`` is
set, ONE item ``nsud:ids`` carrying those ids (sample filter, no window call in grab). Item key = ``<itemId>|v<version>``; the version is ``1`` and a non-blank
``refreshToken`` makes it ``1-<hash8>``. How many decisions a month holds is found out by grab (a month with none is an empty item). The sample filter
``maxDocs`` travels in ``meta`` and never trims the Catalog. Unset (null) settings are absent: the Host sends null for a Source key the type does not declare.
"""
from __future__ import annotations

import calendar
import hashlib
import re
from datetime import UTC, date, datetime
from typing import Any, TypeGuard
from urllib.parse import urlencode

from v11 import ProcErrorCode

SITE_FIRST_YEAR = 2005
MIN_YEAR = 1900
SEEN_LIMIT = 2000
MAX_ITEMS = 2000
MAX_IDS = 50
BASE_VERSION = "1"
API = "https://www.nsud.sk/ws/opendata.php"
IDS_ITEM = "nsud:ids"
_DIGITS = re.compile(r"^[0-9]{1,9}$")


class DetectError(Exception):
    """A protocol error: ``code`` is one of the three v1.1 codes."""

    def __init__(self, code: ProcErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _config_error(message: str) -> DetectError:
    return DetectError(ProcErrorCode.CONFIG_ERROR, message)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def today() -> date:
    """The date used for 'now'; a function so that tests can fix it."""
    return datetime.now(tz=UTC).date()


def validate_refresh_token(token: Any) -> str | None:
    if token is None or token == "":
        return None
    if not isinstance(token, str):
        raise _config_error("refreshToken must be a string")
    return token


def validate_state(state: Any) -> dict[str, Any] | None:
    if state is None:
        return None
    seen = state.get("seen") if isinstance(state, dict) else None
    if not isinstance(state, dict) or (seen is not None and not (isinstance(seen, list) and all(isinstance(s, str) for s in seen))):
        raise _config_error("state must be an object {seen: [string]}")
    return state


def version_of(refresh_token: str | None) -> str:
    if not refresh_token:
        return BASE_VERSION
    return f"{BASE_VERSION}-{hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()[:8]}"


def _with_refresh(url: str, version: str, refresh_token: str | None) -> str:
    if not refresh_token:
        return url
    return url + "&" + urlencode({"refresh": version})


def _years(params: dict[str, Any]) -> tuple[int, int]:
    now = today().year
    first = params.get("annoFrom", SITE_FIRST_YEAR)
    last = params.get("annoTo", now)
    limit = now + 1
    for name, value in (("annoFrom", first), ("annoTo", last)):
        if not _is_int(value) or not MIN_YEAR <= value <= limit + 100:
            raise _config_error(f"{name} must be an integer year, got {value!r}")
    if first > last:
        raise _config_error(f"annoFrom ({first}) must not be after annoTo ({last})")
    return max(first, SITE_FIRST_YEAR), last


def _positive(params: dict[str, Any], name: str) -> int | None:
    value = params.get(name)
    if value is None:
        return None
    if not _is_int(value) or value < 1:
        raise _config_error(f"{name} must be an integer >= 1")
    return value


def _ids(params: dict[str, Any]) -> list[str] | None:
    ids = params.get("ids")
    if ids is None or ids == []:
        return None
    ok = isinstance(ids, list) and len(ids) <= MAX_IDS and all(isinstance(i, str) and _DIGITS.match(i) for i in ids)
    if not ok:
        raise _config_error(f"ids must be an array of at most {MAX_IDS} decision ids written as digits")
    return sorted(set(ids), key=int)


def build_found(params: dict[str, Any], refresh_token: str | None) -> list[dict[str, Any]]:
    """Every item of the Source config, in stable order (validates the whole config)."""
    version = version_of(refresh_token)
    first, last = _years(params)
    max_docs = _positive(params, "maxDocs")
    ids = _ids(params)
    if ids is not None:
        meta: dict[str, Any] = {"kind": "nsud", "itemId": IDS_ITEM, "version": version, "ids": ids}
        if max_docs is not None:
            meta["maxDocs"] = max_docs
        return [{"key": f"{IDS_ITEM}|v{version}", "url": _with_refresh(f"{API}?getDecision", version, refresh_token), "meta": meta}]
    now = today()
    items: list[dict[str, Any]] = []
    for year in range(first, last + 1):
        for month in range(1, 13):
            if (year, month) > (now.year, now.month):
                break
            start = date(year, month, 1)
            end = date(year, month, calendar.monthrange(year, month)[1])
            item_id = f"nsud:{year}-{month:02d}"
            meta = {"kind": "nsud", "itemId": item_id, "version": version, "from": start.isoformat(), "to": end.isoformat()}
            if max_docs is not None:
                meta["maxDocs"] = max_docs
            url = f"{API}?searchDecision&art_datrozh_od={start.isoformat()}&art_datrozh_do={end.isoformat()}"
            items.append({"key": f"{item_id}|v{version}", "url": _with_refresh(url, version, refresh_token), "meta": meta})
    if len(items) > MAX_ITEMS:
        raise _config_error(f"at most {MAX_ITEMS} items per Source, got {len(items)}: narrow the years")
    return items


def build_run_result(found: list[dict[str, Any]], state_in: dict[str, Any] | None) -> dict[str, Any]:
    """Items = those whose key is not in state.seen; state keeps the newest SEEN_LIMIT keys."""
    seen = list((state_in or {}).get("seen") or [])
    known = set(seen)
    new = [item for item in found if item["key"] not in known]
    seen_out = (seen + [item["key"] for item in new])[-SEEN_LIMIT:]
    return {
        "items": new,
        "state": {"seen": seen_out},
        "metrics": {"items": len(found), "newItems": len(new)},
        "checks": [{"name": "items_found", "passed": len(found) > 0, "severity": "error"}],
    }


CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "annoFrom": {"type": "integer", "minimum": SITE_FIRST_YEAR - 100, "description": "first year of decision dates (clamped to 2005)"},
        "annoTo": {"type": "integer", "description": "last year of decision dates (default: the current year)"},
        "ids": {"type": "array", "maxItems": MAX_IDS, "items": {"type": "string", "pattern": "^[0-9]{1,9}$"}, "description": "explicit nsud ids (sample)"},
        "maxDocs": {"type": "integer", "minimum": 1},
        "includePdfOnly": {"type": "boolean"},
        "verifyTls": {"type": "boolean"},
        "delaySeconds": {"type": "number"},
        "baseUrl": {"type": "string"},
        "refreshToken": {"type": ["string", "null"], "description": "change it to fetch every item again"},
        "state": {"type": ["object", "null"], "properties": {"seen": {"type": "array", "items": {"type": "string"}}}},
    },
    "additionalProperties": True,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["items", "state", "metrics", "checks"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "required": ["key", "url", "meta"], "properties": {
            "key": {"type": "string", "minLength": 1}, "url": {"type": "string", "minLength": 1},
            "meta": {"type": "object", "required": ["kind", "itemId", "version"], "properties": {
                "kind": {"enum": ["nsud"]}, "itemId": {"type": "string"}, "version": {"type": "string"}}}}}},
        "state": {"type": "object", "required": ["seen"], "properties": {"seen": {"type": "array", "items": {"type": "string"}}}},
        "metrics": {"type": "object", "properties": {"items": {"type": "integer"}, "newItems": {"type": "integer"}}},
        "checks": {"type": "array"},
    },
}
