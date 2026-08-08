from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from config import Settings


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "token_lifecycle_samples.json"

PER_CATEGORY = 2
TOTAL_TOKENS = 10


def json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Nicht JSON-serialisierbar: {type(value).__name__}")


def number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def drop_pct(peak: Any, current: Any) -> float | None:
    peak_value = number(peak)
    current_value = number(current)

    if peak_value is None or peak_value <= 0 or current_value is None:
        return None

    return max((peak_value - current_value) / peak_value * 100, 0.0)


def ratio(left: Any, right: Any) -> float | None:
    left_value = number(left)
    right_value = number(right)

    if left_value is None or right_value is None or right_value == 0:
        return None

    return left_value / right_value


def in_floor(feature: dict[str, Any]) -> bool:
    mcap = number(feature.get("current_mcap"))
    return mcap is not None and 2_000 <= mcap < 5_000


def build_latest_cache(connection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE inspect_latest ON COMMIT DROP AS
        SELECT
            m.mint,
            m.created_at,
            m.unchanged_since,
            m.last_polled_at,
            s.observed_at AS latest_observed_at,
            s.payload AS current_payload,

            s.payload->>'name' AS name,
            s.payload->>'symbol' AS symbol,
            s.payload->>'launchpad' AS launchpad,
            s.payload->>'dev' AS dev,

            NULLIF(s.payload->>'mcap', '')::float8 AS current_mcap,
            NULLIF(s.payload->>'liquidity', '')::float8 AS current_liquidity,
            NULLIF(s.payload->>'holderCount', '')::int AS current_holders,

            CASE
                WHEN s.payload ? 'stats1h'
                THEN
                    COALESCE(
                        NULLIF(s.payload->'stats1h'->>'numBuys', '')::int,
                        0
                    )
                    +
                    COALESCE(
                        NULLIF(s.payload->'stats1h'->>'numSells', '')::int,
                        0
                    )
                ELSE NULL
            END AS stats1h_activity,

            NULLIF(s.payload->>'graduatedAt', '') IS NOT NULL AS is_graduated,

            EXTRACT(
                EPOCH FROM (
                    now() - COALESCE(m.created_at, s.observed_at)
                )
            ) / 60.0 AS age_minutes,

            CASE
                WHEN m.last_polled_at IS NOT NULL
                 AND m.unchanged_since IS NOT NULL
                THEN EXTRACT(
                    EPOCH FROM (
                        m.last_polled_at - m.unchanged_since
                    )
                ) / 60.0
                ELSE NULL
            END AS unchanged_minutes

        FROM mints AS m

        JOIN LATERAL (
            SELECT
                ms.observed_at,
                ms.payload
            FROM mint_snapshots AS ms
            WHERE ms.mint = m.mint
            ORDER BY ms.observed_at DESC
            LIMIT 1
        ) AS s ON true

        WHERE m.tracking_enabled = true
        """
    )

    connection.execute("ANALYZE inspect_latest")


def build_history_cache(connection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE inspect_history ON COMMIT DROP AS
        SELECT
            s.mint,
            COUNT(*) AS snapshot_count,
            MIN(s.observed_at) AS first_snapshot_at,
            MAX(s.observed_at) AS last_snapshot_at,

            MAX(NULLIF(s.payload->>'mcap', '')::float8)
                FILTER (
                    WHERE NULLIF(s.payload->>'mcap', '') IS NOT NULL
                ) AS peak_mcap,

            MAX(NULLIF(s.payload->>'liquidity', '')::float8)
                FILTER (
                    WHERE NULLIF(s.payload->>'liquidity', '') IS NOT NULL
                ) AS peak_liquidity,

            MIN(NULLIF(s.payload->>'holderCount', '')::int)
                FILTER (
                    WHERE NULLIF(s.payload->>'holderCount', '') IS NOT NULL
                ) AS min_holders,

            MAX(NULLIF(s.payload->>'holderCount', '')::int)
                FILTER (
                    WHERE NULLIF(s.payload->>'holderCount', '') IS NOT NULL
                ) AS peak_holders

        FROM mint_snapshots AS s

        JOIN inspect_latest AS l
          ON l.mint = s.mint

        GROUP BY s.mint
        """
    )

    connection.execute("ANALYZE inspect_history")


def gmgn_table_exists(connection) -> bool:
    row = connection.execute(
        """
        SELECT to_regclass('public.gmgn_mint_observations') IS NOT NULL
            AS available
        """
    ).fetchone()

    return bool(row["available"])


def load_candidate_features(
    connection,
    gmgn_available: bool,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            l.*,
            h.snapshot_count,
            h.first_snapshot_at,
            h.last_snapshot_at,
            h.peak_mcap,
            h.peak_liquidity,
            h.min_holders,
            h.peak_holders

        FROM inspect_latest AS l

        JOIN inspect_history AS h
          ON h.mint = l.mint
        """
    ).fetchall()

    gmgn_mints: set[str] = set()

    if gmgn_available:
        gmgn_rows = connection.execute(
            """
            SELECT DISTINCT g.mint
            FROM gmgn_mint_observations AS g
            JOIN inspect_latest AS l
              ON l.mint = g.mint
            """
        ).fetchall()

        gmgn_mints = {row["mint"] for row in gmgn_rows}

    features: list[dict[str, Any]] = []

    for row in rows:
        feature = dict(row)
        feature["gmgn_available"] = feature["mint"] in gmgn_mints
        feature["mcap_drop_pct"] = drop_pct(
            feature.get("peak_mcap"),
            feature.get("current_mcap"),
        )
        feature["liquidity_drop_pct"] = drop_pct(
            feature.get("peak_liquidity"),
            feature.get("current_liquidity"),
        )
        feature["holder_retention_pct"] = (
            ratio(
                feature.get("current_holders"),
                feature.get("peak_holders"),
            )
        )

        if feature["holder_retention_pct"] is not None:
            feature["holder_retention_pct"] *= 100

        features.append(feature)

    return features


def select_tokens(
    features: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_mints: set[str] = set()
    selection_report: dict[str, Any] = {}

    def choose(
        category: str,
        description: str,
        predicate: Callable[[dict[str, Any]], bool],
        ranking: Callable[[dict[str, Any]], tuple],
    ) -> None:
        candidates = [
            feature
            for feature in features
            if predicate(feature)
        ]

        candidates.sort(
            key=lambda feature: (
                1 if feature.get("gmgn_available") else 0,
                *ranking(feature),
            ),
            reverse=True,
        )

        picked = []

        for feature in candidates:
            if feature["mint"] in selected_mints:
                continue

            item = dict(feature)
            item["sample_category"] = category
            item["selection_reason"] = description

            selected.append(item)
            picked.append(item["mint"])
            selected_mints.add(item["mint"])

            if len(picked) >= PER_CATEGORY:
                break

        selection_report[category] = {
            "matching_candidates": len(candidates),
            "selected": len(picked),
            "selected_mints": picked,
            "description": description,
        }

    choose(
        category="round_trip_graveyard",
        description=(
            "Nicht graduiert, aktuell im $2k–5k-Floor, mindestens "
            "3 Stunden alt, vorheriger Peak >= $10k und mindestens "
            "80 % unter dem Peak."
        ),
        predicate=lambda feature: (
            in_floor(feature)
            and not feature.get("is_graduated")
            and number(feature.get("age_minutes")) is not None
            and number(feature["age_minutes"]) >= 180
            and number(feature.get("peak_mcap")) is not None
            and number(feature["peak_mcap"]) >= 10_000
            and number(feature.get("mcap_drop_pct")) is not None
            and number(feature["mcap_drop_pct"]) >= 80
        ),
        ranking=lambda feature: (
            number(feature.get("mcap_drop_pct")) or 0,
            number(feature.get("peak_mcap")) or 0,
            number(feature.get("unchanged_minutes")) or 0,
        ),
    )

    choose(
        category="failed_to_ignite",
        description=(
            "Nicht graduiert, seit mindestens 3 Stunden im "
            "$2k–5k-Floor, Peak unter $10k, höchstens 2 Holder "
            "und mindestens 60 Minuten unverändert."
        ),
        predicate=lambda feature: (
            in_floor(feature)
            and not feature.get("is_graduated")
            and number(feature.get("age_minutes")) is not None
            and number(feature["age_minutes"]) >= 180
            and number(feature.get("peak_mcap")) is not None
            and number(feature["peak_mcap"]) < 10_000
            and number(feature.get("current_holders")) is not None
            and number(feature["current_holders"]) <= 2
            and number(feature.get("unchanged_minutes")) is not None
            and number(feature["unchanged_minutes"]) >= 60
        ),
        ranking=lambda feature: (
            number(feature.get("unchanged_minutes")) or 0,
            number(feature.get("age_minutes")) or 0,
        ),
    )

    choose(
        category="floor_but_alive",
        description=(
            "Aktuell im $2k–5k-Floor, aber jung oder mit "
            "beobachtbarer Aktivität beziehungsweise wachsender Holderbasis."
        ),
        predicate=lambda feature: (
            in_floor(feature)
            and not feature.get("is_graduated")
            and (
                (
                    number(feature.get("age_minutes")) is not None
                    and number(feature["age_minutes"]) < 180
                )
                or (
                    number(feature.get("stats1h_activity")) is not None
                    and number(feature["stats1h_activity"]) > 0
                )
                or (
                    number(feature.get("current_holders")) is not None
                    and number(feature["current_holders"]) >= 11
                )
            )
        ),
        ranking=lambda feature: (
            number(feature.get("stats1h_activity")) or 0,
            number(feature.get("current_holders")) or 0,
            -(number(feature.get("age_minutes")) or 0),
        ),
    )

    choose(
        category="terminal_collapse",
        description=(
            "Historisch relevante Liquidität oder Market Cap, "
            "aktuell aber nahezu vollständiger Zusammenbruch."
        ),
        predicate=lambda feature: (
            (
                number(feature.get("peak_liquidity")) is not None
                and number(feature["peak_liquidity"]) >= 1_000
                and number(feature.get("current_liquidity")) is not None
                and number(feature["current_liquidity"]) <= 1
                and number(feature.get("liquidity_drop_pct")) is not None
                and number(feature["liquidity_drop_pct"]) >= 99
            )
            or (
                number(feature.get("peak_mcap")) is not None
                and number(feature["peak_mcap"]) >= 40_000
                and number(feature.get("current_mcap")) is not None
                and number(feature["current_mcap"]) <= 100
            )
        ),
        ranking=lambda feature: (
            number(feature.get("liquidity_drop_pct")) or 0,
            number(feature.get("mcap_drop_pct")) or 0,
            number(feature.get("peak_liquidity")) or 0,
        ),
    )

    choose(
        category="healthy_control",
        description=(
            "Gesunder Kontrollfall mit mindestens $200k Market Cap "
            "und relevanter Liquidität oder Holderbasis."
        ),
        predicate=lambda feature: (
            number(feature.get("current_mcap")) is not None
            and number(feature["current_mcap"]) >= 200_000
            and (
                (
                    number(feature.get("current_liquidity")) is not None
                    and number(feature["current_liquidity"]) >= 10_000
                )
                or (
                    number(feature.get("current_holders")) is not None
                    and number(feature["current_holders"]) >= 100
                )
            )
        ),
        ranking=lambda feature: (
            number(feature.get("current_mcap")) or 0,
            number(feature.get("current_liquidity")) or 0,
            number(feature.get("current_holders")) or 0,
        ),
    )

    if len(selected) < TOTAL_TOKENS:
        fallback = sorted(
            features,
            key=lambda feature: (
                1 if feature.get("gmgn_available") else 0,
                number(feature.get("snapshot_count")) or 0,
            ),
            reverse=True,
        )

        for feature in fallback:
            if feature["mint"] in selected_mints:
                continue

            item = dict(feature)
            item["sample_category"] = "fallback_control"
            item["selection_reason"] = (
                "Fallback, weil eine der vorgesehenen Kategorien "
                "weniger als zwei Kandidaten enthielt."
            )

            selected.append(item)
            selected_mints.add(item["mint"])

            if len(selected) >= TOTAL_TOKENS:
                break

    return selected[:TOTAL_TOKENS], selection_report


def load_jupiter_history(
    connection,
    mint: str,
) -> list[dict[str, Any]]:
    return list(
        connection.execute(
            """
            SELECT
                observed_at,
                payload->>'updatedAt' AS updated_at,
                NULLIF(payload->>'mcap', '')::float8 AS market_cap,
                NULLIF(payload->>'liquidity', '')::float8 AS liquidity,
                NULLIF(payload->>'holderCount', '')::int AS holder_count,

                payload->'stats5m' AS stats5m,
                payload->'stats1h' AS stats1h,
                payload->'stats6h' AS stats6h,
                payload->'stats24h' AS stats24h,

                payload->>'graduatedAt' AS graduated_at,
                payload->>'launchpad' AS launchpad,
                payload->>'dev' AS dev,
                payload->'firstPool' AS first_pool

            FROM mint_snapshots
            WHERE mint = %s
            ORDER BY observed_at
            """,
            (mint,),
        ).fetchall()
    )


def load_gmgn_observations(
    connection,
    mints: list[str],
    available: bool,
    generated_at: datetime,
) -> dict[str, list[dict[str, Any]]]:
    result = {mint: [] for mint in mints}

    if not available:
        return result

    rows = connection.execute(
        """
        SELECT *
        FROM gmgn_mint_observations
        WHERE mint = ANY(%s)
        ORDER BY mint, run_id
        """,
        (mints,),
    ).fetchall()

    for row in rows:
        observation = dict(row)
        observed_at = observation.get("run_id")

        if isinstance(observed_at, datetime):
            observation["observation_age_hours_at_export"] = round(
                max(
                    (generated_at - observed_at).total_seconds() / 3600,
                    0.0,
                ),
                3,
            )

        result[observation["mint"]].append(observation)

    return result


def trajectory_summary(
    feature: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    mcap_rows = [
        row
        for row in history
        if number(row.get("market_cap")) is not None
    ]

    liquidity_rows = [
        row
        for row in history
        if number(row.get("liquidity")) is not None
    ]

    holder_rows = [
        row
        for row in history
        if number(row.get("holder_count")) is not None
    ]

    peak_mcap_row = (
        max(mcap_rows, key=lambda row: number(row["market_cap"]) or 0)
        if mcap_rows
        else None
    )

    peak_liquidity_row = (
        max(
            liquidity_rows,
            key=lambda row: number(row["liquidity"]) or 0,
        )
        if liquidity_rows
        else None
    )

    created_at = feature.get("created_at")
    first_snapshot_at = feature.get("first_snapshot_at")

    first_snapshot_delay_minutes = None

    if isinstance(created_at, datetime) and isinstance(first_snapshot_at, datetime):
        first_snapshot_delay_minutes = round(
            max(
                (first_snapshot_at - created_at).total_seconds() / 60,
                0.0,
            ),
            3,
        )

    return {
        "history_points": len(history),
        "first_snapshot_at": first_snapshot_at,
        "last_snapshot_at": feature.get("last_snapshot_at"),
        "first_snapshot_delay_minutes": first_snapshot_delay_minutes,

        "first_market_cap": (
            mcap_rows[0]["market_cap"] if mcap_rows else None
        ),
        "peak_market_cap": (
            peak_mcap_row["market_cap"] if peak_mcap_row else None
        ),
        "peak_market_cap_at": (
            peak_mcap_row["observed_at"] if peak_mcap_row else None
        ),
        "current_market_cap": feature.get("current_mcap"),
        "market_cap_drop_pct": feature.get("mcap_drop_pct"),

        "first_liquidity": (
            liquidity_rows[0]["liquidity"] if liquidity_rows else None
        ),
        "peak_liquidity": (
            peak_liquidity_row["liquidity"]
            if peak_liquidity_row
            else None
        ),
        "peak_liquidity_at": (
            peak_liquidity_row["observed_at"]
            if peak_liquidity_row
            else None
        ),
        "current_liquidity": feature.get("current_liquidity"),
        "liquidity_drop_pct": feature.get("liquidity_drop_pct"),

        "first_holders": (
            holder_rows[0]["holder_count"] if holder_rows else None
        ),
        "peak_holders": feature.get("peak_holders"),
        "current_holders": feature.get("current_holders"),
        "holder_retention_pct": feature.get("holder_retention_pct"),
    }


def source_comparison(
    feature: dict[str, Any],
    gmgn_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not gmgn_rows:
        return None

    latest = gmgn_rows[-1]

    return {
        "gmgn_observed_at": latest.get("run_id"),
        "gmgn_age_hours": latest.get("observation_age_hours_at_export"),

        "jupiter_market_cap": feature.get("current_mcap"),
        "gmgn_market_cap": latest.get("market_cap"),
        "gmgn_to_jupiter_mcap_ratio": ratio(
            latest.get("market_cap"),
            feature.get("current_mcap"),
        ),

        "jupiter_liquidity": feature.get("current_liquidity"),
        "gmgn_liquidity": latest.get("liquidity"),
        "gmgn_to_jupiter_liquidity_ratio": ratio(
            latest.get("liquidity"),
            feature.get("current_liquidity"),
        ),

        "jupiter_holders": feature.get("current_holders"),
        "gmgn_holders": latest.get("holder_count"),
    }


def main() -> None:
    settings = Settings.from_env()
    generated_at = datetime.now(timezone.utc)

    with psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
    ) as connection:
        connection.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        )

        build_latest_cache(connection)
        build_history_cache(connection)

        has_gmgn = gmgn_table_exists(connection)

        features = load_candidate_features(
            connection,
            gmgn_available=has_gmgn,
        )

        selected, selection_report = select_tokens(features)
        selected_mints = [feature["mint"] for feature in selected]

        gmgn_by_mint = load_gmgn_observations(
            connection,
            selected_mints,
            available=has_gmgn,
            generated_at=generated_at,
        )

        tokens = []

        for feature in selected:
            mint = feature["mint"]
            history = load_jupiter_history(connection, mint)
            gmgn_rows = gmgn_by_mint.get(mint, [])

            current_raw = feature.get("current_payload")
            public_feature = {
                key: value
                for key, value in feature.items()
                if key != "current_payload"
            }

            tokens.append(
                {
                    "mint": mint,
                    "sample_category": feature["sample_category"],
                    "selection_reason": feature["selection_reason"],

                    "current_features": public_feature,
                    "trajectory_summary": trajectory_summary(
                        feature,
                        history,
                    ),

                    "source_comparison": source_comparison(
                        feature,
                        gmgn_rows,
                    ),

                    "current_jupiter_raw": current_raw,
                    "jupiter_history": history,
                    "gmgn_observations": gmgn_rows,
                }
            )

    output = {
        "schema_version": 1,
        "generated_at": generated_at,
        "purpose": (
            "Representative lifecycle inspection before implementing "
            "the lifecycle and graveyard framework."
        ),
        "gmgn_table_available": has_gmgn,
        "selection": selection_report,
        "token_count": len(tokens),
        "tokens": tokens,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            default=json_default,
        ),
        encoding="utf-8",
    )

    print(f"Geschrieben: {OUTPUT_PATH}")
    print(f"Tokens: {len(tokens)}")
    print(f"GMGN-Tabelle vorhanden: {has_gmgn}")

    for token in tokens:
        gmgn_count = len(token["gmgn_observations"])
        print(
            f"{token['sample_category']:<24} "
            f"{token['mint']} "
            f"GMGN={gmgn_count}"
        )


if __name__ == "__main__":
    main()