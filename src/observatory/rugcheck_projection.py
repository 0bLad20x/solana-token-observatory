from __future__ import annotations

import json
from typing import Any

MARKET_FIELDS = (
    "pubkey",
    "marketType",
    "mintA",
    "mintB",
)
MARKET_LP_FIELDS = (
    "baseUSD",
    "quoteUSD",
    "holders",
    "lpLocked",
    "lpUnlocked",
    "lpLockedPct",
    "lpLockedUSD",
    "lpTotalSupply",
)


def _json_bytes(value: Any) -> int:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return len(payload.encode("utf-8"))


def _project_market(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    projected = {key: value[key] for key in MARKET_FIELDS if key in value}
    lp = value.get("lp")
    if isinstance(lp, dict):
        projected["lp"] = {
            key: lp[key]
            for key in MARKET_LP_FIELDS
            if key in lp
        }
    elif "lp" in value:
        projected["lp"] = lp
    return projected


def _collect_strings(value: Any, target: set[str]) -> None:
    if isinstance(value, str):
        target.add(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_strings(item, target)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if isinstance(key, str):
            target.add(key)
        _collect_strings(item, target)


def project_rugcheck_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded transport projection without changing RugCheck provider facts.

    The direct evidence adapter remains raw. This projection is only for LLM transport:
    repeated per-market account snapshots are removed, while every market keeps identity,
    pair, provider USD liquidity and LP-lock facts. The provider-wide knownAccounts map is
    reduced to labels for addresses referenced elsewhere in the token report.
    """

    report = evidence.get("report")
    if not isinstance(report, dict):
        return evidence

    projected_report = dict(report)

    markets = report.get("markets")
    if isinstance(markets, list):
        projected_report["markets"] = [_project_market(market) for market in markets]

    known_accounts = report.get("knownAccounts")
    known_total = len(known_accounts) if isinstance(known_accounts, dict) else None
    known_retained = known_total
    if isinstance(known_accounts, dict):
        referenced: set[str] = set()
        for key, value in projected_report.items():
            if key in {"knownAccounts", "markets"}:
                continue
            _collect_strings(value, referenced)
        filtered = {
            address: value
            for address, value in known_accounts.items()
            if address in referenced
        }
        projected_report["knownAccounts"] = filtered
        known_retained = len(filtered)

    raw_report_bytes = evidence.get("report_bytes")
    if not isinstance(raw_report_bytes, int):
        raw_report_bytes = _json_bytes(report)
    raw_rough_tokens = evidence.get("rough_report_tokens")
    if not isinstance(raw_rough_tokens, int):
        raw_rough_tokens = (raw_report_bytes + 3) // 4

    projected_report_bytes = _json_bytes(projected_report)
    markets_total = len(markets) if isinstance(markets, list) else None

    return {
        "source": evidence.get("source", "rugcheck"),
        "mint": evidence.get("mint"),
        "fetched_at": evidence.get("fetched_at"),
        "projection": {
            "type": "rugcheck_analysis_v1",
            "raw_report_bytes": raw_report_bytes,
            "raw_rough_report_tokens": raw_rough_tokens,
            "projected_report_bytes": projected_report_bytes,
            "projected_rough_report_tokens": (projected_report_bytes + 3) // 4,
            "markets_total": markets_total,
            "known_accounts_total": known_total,
            "known_accounts_retained": known_retained,
        },
        "report": projected_report,
    }
