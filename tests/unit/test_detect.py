"""Proc-protocol v1.1 detect for the nsud-decisions Source (one item per calendar month of decision dates, or one item for explicit ids): no network, deterministic."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from jsonschema import Draft202012Validator

from conftest import Run
from dp_sk_judikatura_detect import detect

Invoke = Callable[..., Run]
NULLS = {"annoFrom": None, "annoTo": None, "ids": None, "maxDocs": None, "includePdfOnly": None, "verifyTls": None, "delaySeconds": None, "baseUrl": None,
         "refreshToken": None, "state": None, "tokenBudget": None, "dryRun": None}


@pytest.fixture(autouse=True)
def november_2026(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "today", lambda: date(2026, 11, 12))


def keys(run: Run) -> list[str]:
    return [item["key"] for item in run.result["items"]]


def test_spec_declares_protocol_11_with_valid_schemas(invoke: Invoke) -> None:
    run = invoke("spec")

    assert run.result["protocol"] == "1.1"
    for name in ("configSchema", "outputSchema"):
        Draft202012Validator.check_schema(run.result[name])
    assert {"annoFrom", "annoTo", "ids", "maxDocs", "refreshToken", "state"} <= set(run.result["configSchema"]["properties"])


def test_one_year_up_to_november_gives_eleven_month_items(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2026, annoTo=2026)

    assert keys(run) == [f"nsud:2026-{month:02d}|v1" for month in range(1, 12)]
    assert run.result["metrics"] == {"items": 11, "newItems": 11}


def test_month_item_meta_url_and_window(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2024, annoTo=2024)

    february = run.result["items"][1]
    assert february["meta"] == {"kind": "nsud", "itemId": "nsud:2024-02", "version": "1", "from": "2024-02-01", "to": "2024-02-29"}
    assert february["url"] == "https://www.nsud.sk/ws/opendata.php?searchDecision&art_datrozh_od=2024-02-01&art_datrozh_do=2024-02-29"


def test_a_complete_past_range_has_twelve_months_per_year(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2024, annoTo=2025)

    assert len(keys(run)) == 24
    assert keys(run)[0] == "nsud:2024-01|v1"
    assert keys(run)[-1] == "nsud:2025-12|v1"


def test_annofrom_before_the_site_starts_is_clamped_to_2005(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2004, annoTo=2005)

    assert keys(run)[0] == "nsud:2005-01|v1"
    assert len(keys(run)) == 12


def test_defaults_run_from_2005_to_the_current_month(invoke: Invoke) -> None:
    run = invoke("run")

    assert keys(run)[0] == "nsud:2005-01|v1"
    assert keys(run)[-1] == "nsud:2026-11|v1"
    assert len(keys(run)) == (2026 - 2005) * 12 + 11


def test_months_in_the_future_are_never_emitted(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2026, annoTo=2027)

    assert keys(run)[-1] == "nsud:2026-11|v1"


def test_a_range_entirely_in_the_future_gives_no_items(invoke: Invoke) -> None:
    assert keys(invoke("run", annoFrom=2027, annoTo=2027)) == []


def test_same_state_gives_no_new_items(invoke: Invoke) -> None:
    first = invoke("run", annoFrom=2026, annoTo=2026)

    second = invoke("run", annoFrom=2026, annoTo=2026, state=first.result["state"])

    assert keys(second) == []
    assert second.result["metrics"] == {"items": 11, "newItems": 0}
    assert second.result["state"]["seen"] == first.result["state"]["seen"]


def test_a_new_refresh_token_gives_a_new_version_and_every_item_again(invoke: Invoke) -> None:
    first = invoke("run", annoFrom=2026, annoTo=2026)

    refreshed = invoke("run", annoFrom=2026, annoTo=2026, refreshToken="r1", state=first.result["state"])

    version = refreshed.result["items"][0]["meta"]["version"]
    assert version.startswith("1-")
    assert len(version) == 10
    assert len(keys(refreshed)) == 11
    assert refreshed.result["items"][0]["meta"]["itemId"] == "nsud:2026-01"
    assert "refresh=" in refreshed.result["items"][0]["url"]
    again = invoke("run", annoFrom=2026, annoTo=2026, refreshToken="r1", state=refreshed.result["state"])
    assert keys(again) == []
    assert keys(invoke("run", annoFrom=2026, annoTo=2026, refreshToken="r2", state=refreshed.result["state"])) != []


def test_ids_make_one_explicit_item_and_no_month_items(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2005, annoTo=2026, ids=["177749", "150000", "177749"])

    assert keys(run) == ["nsud:ids|v1"]
    item = run.result["items"][0]
    assert item["meta"] == {"kind": "nsud", "itemId": "nsud:ids", "version": "1", "ids": ["150000", "177749"]}


@pytest.mark.parametrize("ids", [["12a"], ["../x"], [""], "150000", [1], [str(n) for n in range(51)]])
def test_bad_ids_are_a_config_error(invoke: Invoke, ids: object) -> None:
    run = invoke("check", ids=ids)

    assert run.error["code"] == "config_error"


@pytest.mark.parametrize(("name", "value"), [("annoFrom", "2020"), ("annoTo", 2020.5), ("annoFrom", True), ("maxDocs", 0), ("refreshToken", 5), ("state", "x")])
def test_bad_values_are_a_config_error(invoke: Invoke, name: str, value: object) -> None:
    assert invoke("check", **{name: value}).error["code"] == "config_error"


def test_annofrom_after_annoto_is_a_config_error(invoke: Invoke) -> None:
    assert invoke("check", annoFrom=2026, annoTo=2025).error["code"] == "config_error"
    assert invoke("run", annoFrom=2026, annoTo=2025).error["code"] == "config_error"


def test_max_docs_travels_in_meta_without_trimming_the_catalog(invoke: Invoke) -> None:
    run = invoke("run", annoFrom=2026, annoTo=2026, maxDocs=3)

    assert len(keys(run)) == 11
    assert run.result["items"][0]["meta"]["maxDocs"] == 3


def test_null_settings_behave_as_absent(invoke: Invoke) -> None:
    assert keys(invoke("run", **NULLS)) == keys(invoke("run"))
    assert keys(invoke("run", **{**NULLS, "annoFrom": 2026, "annoTo": 2026})) == keys(invoke("run", annoFrom=2026, annoTo=2026))


def test_check_validates_the_config_only(invoke: Invoke) -> None:
    assert invoke("check", annoFrom=2026, annoTo=2026).result == {"ok": True}
    assert invoke("check").result == {"ok": True}


def test_execute_is_an_alias_of_run(invoke: Invoke) -> None:
    assert keys(invoke("execute", annoFrom=2026, annoTo=2026, ids=None)) == keys(invoke("run", annoFrom=2026, annoTo=2026))


def test_the_state_keeps_at_most_the_newest_keys(invoke: Invoke) -> None:
    seen = [f"old:{n}|v1" for n in range(detect.SEEN_LIMIT)]

    run = invoke("run", annoFrom=2026, annoTo=2026, state={"seen": seen})

    assert len(run.result["state"]["seen"]) == detect.SEEN_LIMIT
    assert run.result["state"]["seen"][-1] == "nsud:2026-11|v1"
