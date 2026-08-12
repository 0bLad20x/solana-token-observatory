from __future__ import annotations

import json
from collections import Counter
from typing import Any


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


def _authority_present(value: Any) -> bool:
    return value not in (None, "", {}, [])


def _risk_summary(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
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

    mint_authority = token.get("mintAuthority", report.get("mintAuthority"))
    freeze_authority = token.get("freezeAuthority", report.get("freezeAuthority"))

    result: dict[str, Any] = {
        "token_program": report.get("tokenProgram"),
        "token_type": report.get("tokenType"),
        "deploy_platform": report.get("deployPlatform"),
        "launchpad": report.get("launchpad"),
        "detected_at": report.get("detectedAt"),
        "mint_authority_present": _authority_present(mint_authority),
        "freeze_authority_present": _authority_present(freeze_authority),
        "metadata_mutable": token_meta.get("mutable"),
        "metadata_update_authority_present": _authority_present(
            token_meta.get("updateAuthority")
        ),
    }

    transfer_fee = report.get("transferFee")
    if isinstance(transfer_fee, dict):
        fee: dict[str, Any] = {
            "authority_present": _authority_present(transfer_fee.get("authority"))
        }
        for key in ("basisPoints", "maxAmount"):
            if key in transfer_fee:
                fee[key] = transfer_fee[key]
        result["transfer_fee"] = fee
    elif transfer_fee is not None:
        result["transfer_fee"] = transfer_fee

    return result


def _holder_metadata(report: dict[str, Any]) -> dict[str, Any]:
    holders = report.get("topHolders")
    holders = holders if isinstance(holders, list) else []
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

    insider_count = 0
    insider_pct = 0.0
    insider_pct_known = False
    known_names: Counter[str] = Counter()
    known_types: Counter[str] = Counter()
    creator = report.get("creator")
    creator_pct = 0.0
    creator_pct_known = False

    for item in holders:
        if not isinstance(item, dict):
            continue
        pct = _number(item.get("pct"))
        if item.get("insider") is True:
            insider_count += 1
            if pct is not None:
                insider_pct += pct
                insider_pct_known = True

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
        for address in addresses:
            label = known_accounts.get(address)
            if not isinstance(label, dict):
                continue
            name = label.get("name")
            account_type = label.get("type")
            if isinstance(name, str) and name:
                known_names[name] += 1
            if isinstance(account_type, str) and account_type:
                known_types[account_type] += 1

    creator_tokens = report.get("creatorTokens")
    creator_tokens_count = len(creator_tokens) if isinstance(creator_tokens, list) else None

    result: dict[str, Any] = {
        "total_holders": report.get("totalHolders"),
        "top_holders_reported": len(holders),
        "top1_pct": concentration(1),
        "top5_pct": concentration(5),
        "top10_pct": concentration(10),
        "top20_pct": concentration(20),
        "insiders_in_top_holders": insider_count,
        "insider_pct_in_top_holders": (
            _rounded(insider_pct) if insider_pct_known else None
        ),
        "graph_insiders_detected": report.get("graphInsidersDetected"),
        "creator_in_top_holders_pct": (
            _rounded(creator_pct) if creator_pct_known else None
        ),
        "creator_tokens_count": creator_tokens_count,
    }

    insider_networks = report.get("insiderNetworks")
    if isinstance(insider_networks, (list, dict)):
        result["insider_networks"] = len(insider_networks)
    elif insider_networks is None:
        result["insider_networks"] = None

    if known_types:
        result["known_top_holder_types"] = dict(sorted(known_types.items()))
    if known_names:
        result["known_top_holder_labels"] = dict(sorted(known_names.items()))
    return result


def _market_metadata(report: dict[str, Any]) -> dict[str, Any]:
    markets = report.get("markets")
    markets = markets if isinstance(markets, list) else []
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
        base_usd = _number(lp.get("baseUSD")) or 0.0
        quote_usd = _number(lp.get("quoteUSD")) or 0.0
        market_liquidities.append(base_usd + quote_usd)

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

    lockers = report.get("lockers")
    locker_count = len(lockers) if isinstance(lockers, (list, dict)) else None

    return {
        "market_count": len(markets),
        "market_types": dict(sorted(market_types.items())),
        "total_market_liquidity": report.get("totalMarketLiquidity"),
        "total_stable_liquidity": report.get("totalStableLiquidity"),
        "total_lp_providers": report.get("totalLPProviders"),
        "largest_market_liquidity_usd": _rounded(largest_market),
        "largest_market_share_pct": _rounded(largest_share),
        "markets_with_lp_lock_data": with_lock_data,
        "markets_with_positive_lp_lock": with_positive_lock,
        "markets_with_zero_lp_lock": with_zero_lock,
        "locker_count": locker_count,
        "locker_scan_status": report.get("lockerScanStatus"),
    }


def _compact_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_risk": {
            "score": report.get("score"),
            "score_normalised": report.get("score_normalised"),
            "rugged": report.get("rugged"),
            "risks": _risk_summary(report.get("risks")),
        },
        "token_control": _token_metadata(report),
        "ownership": _holder_metadata(report),
        "liquidity": _market_metadata(report),
    }


def project_rugcheck_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Convert the raw RugCheck report into bounded safety metadata for LLM transport.

    The direct evidence adapter remains raw and complete. The LLM receives aggregates and
    provider labels rather than wallet addresses, per-market account snapshots or provider
    registries. This is a deterministic projection: it does not create a new safety score.
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
            "type": "rugcheck_analysis_v2",
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
