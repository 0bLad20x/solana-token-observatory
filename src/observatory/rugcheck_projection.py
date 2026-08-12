from __future__ import annotations

import json
from collections import Counter
from typing import Any

_MISSING = object()

SEMANTICS = {
    "score": (
        "RugCheck raw provider score. Public API does not define its formula or numeric "
        "severity thresholds; do not classify the number itself as low/high risk."
    ),
    "score_normalised": (
        "RugCheck normalized provider score. Public API does not define its formula, "
        "direction or category thresholds; report the value without converting it into "
        "a safety/risk rating."
    ),
    "rugged": (
        "RugCheck provider boolean for this report. false means RugCheck did not mark the "
        "token rugged in this observation; it is not proof of safety or future behavior."
    ),
    "risk_fields": (
        "Risk name, level, value, score and description are RugCheck provider fields. "
        "The description is the canonical supplied meaning; do not add unstated causal "
        "consequences as provider facts."
    ),
    "detected_at": (
        "RugCheck provider detection timestamp; not token creation time and not token age."
    ),
    "platform": (
        "launchpad/deploy_platform identify reported infrastructure only; do not assign "
        "reputation or risk unless RugCheck lists an explicit risk for it."
    ),
    "transfer_fee": (
        "Reported transfer-fee fields only; authority presence or maxAmount must not be "
        "expanded into claims about future fee changes unless provider evidence states it."
    ),
    "topN_pct": (
        "Sum of pct for the N largest reported top-holder rows. Rows can include AMM/pool "
        "infrastructure, so this is address-row concentration, not automatically beneficial-"
        "owner concentration."
    ),
    "known_holder_pct": (
        "Known holder percentages are deterministic sums over top-holder rows matched to "
        "RugCheck known-account labels/types. They identify provider-labelled infrastructure "
        "without sending wallet addresses."
    ),
    "insider": (
        "Counts/shares use only rows with an explicit RugCheck insider flag; null means "
        "the required flag or percentage evidence was unavailable."
    ),
    "graph_insiders": (
        "graph_insiders_detected and insider_networks are RugCheck graph-level signals; "
        "do not infer overlap or non-overlap with top-holder insider flags."
    ),
    "largest_market_share_pct": (
        "Largest observed market USD liquidity divided by summed observed markets with "
        "USD liquidity; this is liquidity concentration, not ownership or withdrawability."
    ),
    "lp_lock_counts": (
        "Counts use explicit RugCheck lpLockedPct: >0 positive, =0 zero; missing values "
        "excluded. locker_count and locker_scan_status are separate provider fields. "
        "Do not infer that no locker entry means liquidity is unlocked/withdrawable, and "
        "do not call the fields contradictory without explicit provider evidence."
    ),
}


def _json_bytes(value: Any) -> int:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return len(payload.encode("utf-8"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _presence(value: Any) -> bool | None:
    if value is _MISSING:
        return None
    return value not in (None, "", {}, [])


def _nested_or_top(
    nested: dict[str, Any], nested_key: str, report: dict[str, Any], top_key: str
) -> Any:
    if nested_key in nested:
        return nested[nested_key]
    if top_key in report:
        return report[top_key]
    return _MISSING


def _risk_summary(value: Any) -> list[dict[str, Any]] | None:
    if value is _MISSING or value is None or not isinstance(value, list):
        return None

    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row = {
            key: item[key]
            for key in ("name", "level", "value", "score", "description")
            if key in item
        }
        if row:
            rows.append(row)
    return rows


def _token_metadata(report: dict[str, Any]) -> dict[str, Any]:
    token_meta = report.get("tokenMeta")
    token_meta = token_meta if isinstance(token_meta, dict) else {}
    token = report.get("token")
    token = token if isinstance(token, dict) else {}

    mint_authority = _nested_or_top(token, "mintAuthority", report, "mintAuthority")
    freeze_authority = _nested_or_top(token, "freezeAuthority", report, "freezeAuthority")
    update_authority = (
        token_meta["updateAuthority"] if "updateAuthority" in token_meta else _MISSING
    )

    result: dict[str, Any] = {
        "token_program": report.get("tokenProgram"),
        "token_type": report.get("tokenType"),
        "deploy_platform": report.get("deployPlatform"),
        "launchpad": report.get("launchpad"),
        "detected_at": report.get("detectedAt"),
        "mint_authority_present": _presence(mint_authority),
        "freeze_authority_present": _presence(freeze_authority),
        "metadata_mutable": token_meta.get("mutable"),
        "metadata_update_authority_present": _presence(update_authority),
    }

    if "transferFee" in report:
        transfer_fee = report["transferFee"]
        if isinstance(transfer_fee, dict):
            fee: dict[str, Any] = {
                "authority_present": _presence(
                    transfer_fee["authority"]
                    if "authority" in transfer_fee
                    else _MISSING
                )
            }
            for key in ("basisPoints", "maxAmount"):
                if key in transfer_fee:
                    fee[key] = transfer_fee[key]
            result["transfer_fee"] = fee
        else:
            result["transfer_fee"] = transfer_fee
    else:
        result["transfer_fee"] = None

    return result


def _holder_metadata(report: dict[str, Any]) -> dict[str, Any]:
    holders_value = report.get("topHolders", _MISSING)
    holders_known = isinstance(holders_value, list)
    holders = holders_value if holders_known else []

    known_accounts = report.get("knownAccounts")
    known_accounts = known_accounts if isinstance(known_accounts, dict) else {}

    pcts = sorted(
        (
            pct
            for item in holders
            if isinstance(item, dict)
            for pct in [_number(item.get("pct"))]
            if pct is not None
        ),
        reverse=True,
    )

    def concentration(limit: int) -> float | None:
        if not pcts:
            return None
        return _rounded(sum(pcts[:limit]))

    insider_flags_reported = 0
    insider_count = 0
    insider_pct = 0.0
    insider_true_pct_complete = True
    known_names: Counter[str] = Counter()
    known_types: Counter[str] = Counter()
    known_name_pct: Counter[str] = Counter()
    known_type_pct: Counter[str] = Counter()
    labelled_pct = 0.0
    labelled_pct_known = False
    largest_unlabelled_pct: float | None = None
    creator = report.get("creator")
    creator_pct = 0.0
    creator_pct_known = False

    for item in holders:
        if not isinstance(item, dict):
            continue
        pct = _number(item.get("pct"))
        insider = item.get("insider", _MISSING)
        if isinstance(insider, bool):
            insider_flags_reported += 1
            if insider:
                insider_count += 1
                if pct is None:
                    insider_true_pct_complete = False
                else:
                    insider_pct += pct

        if isinstance(creator, str) and creator:
            if item.get("owner") == creator or item.get("address") == creator:
                if pct is not None:
                    creator_pct += pct
                    creator_pct_known = True

        addresses = {
            value
            for key in ("address", "owner")
            for value in [item.get(key)]
            if isinstance(value, str) and value
        }
        row_names: set[str] = set()
        row_types: set[str] = set()
        for address in addresses:
            label = known_accounts.get(address)
            if not isinstance(label, dict):
                continue
            name = label.get("name")
            account_type = label.get("type")
            if isinstance(name, str) and name:
                row_names.add(name)
            if isinstance(account_type, str) and account_type:
                row_types.add(account_type)

        for name in row_names:
            known_names[name] += 1
            if pct is not None:
                known_name_pct[name] += pct
        for account_type in row_types:
            known_types[account_type] += 1
            if pct is not None:
                known_type_pct[account_type] += pct

        if row_names or row_types:
            if pct is not None:
                labelled_pct += pct
                labelled_pct_known = True
        elif pct is not None:
            largest_unlabelled_pct = (
                pct
                if largest_unlabelled_pct is None
                else max(largest_unlabelled_pct, pct)
            )

    creator_tokens = report.get("creatorTokens", _MISSING)
    creator_tokens_count = (
        len(creator_tokens) if isinstance(creator_tokens, list) else None
    )

    insider_count_value = insider_count if insider_flags_reported else None
    insider_pct_value: float | None
    if not insider_flags_reported:
        insider_pct_value = None
    elif insider_count == 0:
        insider_pct_value = 0.0
    elif insider_true_pct_complete:
        insider_pct_value = _rounded(insider_pct)
    else:
        insider_pct_value = None

    result: dict[str, Any] = {
        "total_holders": report.get("totalHolders"),
        "top_holders_reported": len(holders) if holders_known else None,
        "top1_pct": concentration(1),
        "top5_pct": concentration(5),
        "top10_pct": concentration(10),
        "top20_pct": concentration(20),
        "known_labelled_top_holder_pct": (
            _rounded(labelled_pct) if labelled_pct_known else None
        ),
        "largest_unlabelled_top_holder_pct": _rounded(largest_unlabelled_pct),
        "insider_flags_reported": insider_flags_reported if holders_known else None,
        "insiders_in_top_holders": insider_count_value,
        "insider_pct_in_top_holders": insider_pct_value,
        "graph_insiders_detected": report.get("graphInsidersDetected"),
        "creator_in_top_holders_pct": (
            _rounded(creator_pct) if creator_pct_known else None
        ),
        "creator_tokens_count": creator_tokens_count,
    }

    insider_networks = report.get("insiderNetworks", _MISSING)
    if isinstance(insider_networks, (list, dict)):
        result["insider_networks"] = len(insider_networks)
    else:
        result["insider_networks"] = None

    if known_types:
        result["known_top_holder_types"] = dict(sorted(known_types.items()))
    if known_names:
        result["known_top_holder_labels"] = dict(sorted(known_names.items()))
    if known_type_pct:
        result["known_top_holder_type_pct"] = {
            key: _rounded(value) for key, value in sorted(known_type_pct.items())
        }
    if known_name_pct:
        result["known_top_holder_label_pct"] = {
            key: _rounded(value) for key, value in sorted(known_name_pct.items())
        }
    return result


def _market_metadata(report: dict[str, Any]) -> dict[str, Any]:
    markets_value = report.get("markets", _MISSING)
    markets_known = isinstance(markets_value, list)
    markets = markets_value if markets_known else []

    market_types: Counter[str] = Counter()
    market_liquidities: list[float] = []
    with_positive_lock = 0
    with_zero_lock = 0
    with_lock_data = 0

    for market in markets:
        if not isinstance(market, dict):
            continue
        market_type = market.get("marketType")
        if isinstance(market_type, str) and market_type:
            market_types[market_type] += 1

        lp = market.get("lp")
        if not isinstance(lp, dict):
            continue
        base_usd = _number(lp.get("baseUSD"))
        quote_usd = _number(lp.get("quoteUSD"))
        if base_usd is not None or quote_usd is not None:
            market_liquidities.append((base_usd or 0.0) + (quote_usd or 0.0))

        locked_pct = _number(lp.get("lpLockedPct"))
        if locked_pct is not None:
            with_lock_data += 1
            if locked_pct > 0:
                with_positive_lock += 1
            else:
                with_zero_lock += 1

    liquidity_sum = sum(market_liquidities)
    largest_market = max(market_liquidities) if market_liquidities else None
    largest_share = (
        largest_market / liquidity_sum * 100.0
        if largest_market is not None and liquidity_sum > 0
        else None
    )

    lockers = report.get("lockers", _MISSING)
    locker_count = len(lockers) if isinstance(lockers, (list, dict)) else None

    return {
        "market_count": len(markets) if markets_known else None,
        "market_types": dict(sorted(market_types.items())) if markets_known else None,
        "total_market_liquidity": report.get("totalMarketLiquidity"),
        "total_stable_liquidity": report.get("totalStableLiquidity"),
        "total_lp_providers": report.get("totalLPProviders"),
        "largest_market_liquidity_usd": _rounded(largest_market),
        "largest_market_share_pct": _rounded(largest_share),
        "markets_with_lp_lock_data": with_lock_data if markets_known else None,
        "markets_with_positive_lp_lock": with_positive_lock if markets_known else None,
        "markets_with_zero_lp_lock": with_zero_lock if markets_known else None,
        "locker_count": locker_count,
        "locker_scan_status": report.get("lockerScanStatus"),
    }


def _compact_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "semantics": SEMANTICS,
        "provider_risk": {
            "score": report.get("score"),
            "score_normalised": report.get("score_normalised"),
            "rugged": report.get("rugged"),
            "risks": _risk_summary(report.get("risks", _MISSING)),
        },
        "token_control": _token_metadata(report),
        "ownership": _holder_metadata(report),
        "liquidity": _market_metadata(report),
    }


def project_rugcheck_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Convert the raw RugCheck report into bounded safety metadata for LLM transport.

    The direct evidence adapter remains raw and complete. The LLM receives provider-defined
    risk semantics plus deterministic aggregates rather than wallet addresses, per-market
    account snapshots or provider registries. Missing provider evidence remains unknown.
    No internal safety score or undocumented RugCheck threshold is created.
    """

    report = evidence.get("report")
    if not isinstance(report, dict):
        return evidence

    raw_report_bytes = evidence.get("report_bytes")
    if not isinstance(raw_report_bytes, int):
        raw_report_bytes = _json_bytes(report)
    raw_rough_tokens = evidence.get("rough_report_tokens")
    if not isinstance(raw_rough_tokens, int):
        raw_rough_tokens = (raw_report_bytes + 3) // 4

    summary = _compact_summary(report)
    projected_bytes = _json_bytes(summary)

    markets = report.get("markets")
    holders = report.get("topHolders")
    known_accounts = report.get("knownAccounts")

    return {
        "source": evidence.get("source", "rugcheck"),
        "mint": evidence.get("mint"),
        "fetched_at": evidence.get("fetched_at"),
        "projection": {
            "type": "rugcheck_analysis_v4",
            "raw_report_bytes": raw_report_bytes,
            "raw_rough_report_tokens": raw_rough_tokens,
            "projected_report_bytes": projected_bytes,
            "projected_rough_report_tokens": (projected_bytes + 3) // 4,
            "markets_observed": len(markets) if isinstance(markets, list) else None,
            "top_holders_observed": len(holders) if isinstance(holders, list) else None,
            "known_accounts_observed": (
                len(known_accounts) if isinstance(known_accounts, dict) else None
            ),
            "wallet_addresses_sent_to_llm": 0,
        },
        "summary": summary,
    }
