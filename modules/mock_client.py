"""Drop-in mock for AhrefsClient that returns synthetic fixtures.

The catalog is curated so the pipeline produces meaningful outputs:
- Target ranks top-3 on some queries (won't appear in quick wins)
- Target ranks 4-20 on others (the quick-win bucket)
- Some queries are held only by competitors (content gap)
- Thematic seeds expand into believable variations

Honors the lightweight `where=` filters used by the analyzers
(volume>=N, position<=N, keyword_difficulty<=N).
"""

from __future__ import annotations

import math
import random
import re
from typing import Any

TARGET = "esprit-riche.com"

# (keyword, volume, kd, cpc, intent, parent_topic, ranking_per_domain)
# ranking_per_domain: dict domain -> position (1-100). Missing = not ranked.
_CATALOG: list[tuple] = [
    # === Target ranks top 3 (already winning, NOT quick wins) ===
    ("etf pea", 8100, 48, 1.2, "commercial", "ETF",
     {TARGET: 2, "avenuedesinvestisseurs.fr": 1, "plus-riche.com": 4}),
    ("lmnp définition", 4400, 22, 0.6, "informational", "LMNP",
     {TARGET: 1, "devenir-rentier.fr": 5, "avenuedesinvestisseurs.fr": 8}),
    ("indépendance financière", 5400, 42, 1.1, "informational", "FIRE",
     {TARGET: 3, "plus-riche.com": 1, "esi-bourse.com": 12}),
    ("pea fonctionnement", 3600, 35, 0.9, "informational", "PEA",
     {TARGET: 2, "avenuedesinvestisseurs.fr": 3}),
    ("dca bourse", 1900, 22, 0.7, "informational", "DCA",
     {TARGET: 1, "esi-bourse.com": 6, "plus-riche.com": 9}),

    # === Quick wins: target in positions 4-20, decent volume, KD <= 30 ===
    ("lmnp 2026", 1900, 28, 0.8, "informational", "LMNP",
     {TARGET: 7, "avenuedesinvestisseurs.fr": 3, "devenir-rentier.fr": 5}),
    ("réforme lmnp 2026", 880, 24, 0.7, "informational", "LMNP",
     {TARGET: 11, "avenuedesinvestisseurs.fr": 4, "devenir-rentier.fr": 8}),
    ("amortissement lmnp", 2400, 25, 0.6, "informational", "LMNP",
     {TARGET: 8, "devenir-rentier.fr": 2, "avenuedesinvestisseurs.fr": 6}),
    ("déclaration lmnp 2026", 1100, 18, 0.9, "transactional", "LMNP",
     {TARGET: 14, "devenir-rentier.fr": 3}),
    ("lmnp ou lmp", 720, 22, 0.5, "commercial", "LMNP",
     {TARGET: 6, "avenuedesinvestisseurs.fr": 4}),
    ("calcul viager occupé", 2900, 26, 0.4, "informational", "Viager",
     {TARGET: 9, "avenuedesinvestisseurs.fr": 5}),
    ("vente à terme immobilier", 880, 22, 0.6, "informational", "Vente à terme",
     {TARGET: 12}),
    ("fiscalité viager", 1300, 28, 0.5, "informational", "Viager",
     {TARGET: 8, "avenuedesinvestisseurs.fr": 3}),
    ("bouquet viager calcul", 590, 20, 0.4, "informational", "Viager",
     {TARGET: 15}),
    ("fire retraite anticipée", 720, 25, 0.5, "informational", "FIRE",
     {TARGET: 11, "plus-riche.com": 2}),
    ("rente passive", 1300, 22, 0.6, "informational", "FIRE",
     {TARGET: 7, "plus-riche.com": 4}),
    ("revenu passif immobilier", 1900, 28, 0.9, "commercial", "FIRE",
     {TARGET: 10, "plus-riche.com": 3, "avenuedesinvestisseurs.fr": 7}),
    ("msci world etf", 2900, 30, 1.4, "commercial", "ETF",
     {TARGET: 13, "avenuedesinvestisseurs.fr": 2, "esi-bourse.com": 5}),
    ("dividendes mensuels", 880, 24, 0.7, "informational", "Dividendes",
     {TARGET: 9, "esi-bourse.com": 3}),
    ("hcsf 2026", 480, 18, 0.8, "informational", "HCSF",
     {TARGET: 6, "avenuedesinvestisseurs.fr": 4}),
    ("renégocier prêt immobilier", 1900, 30, 1.6, "transactional", "Crédit",
     {TARGET: 16, "avenuedesinvestisseurs.fr": 3}),
    ("simulateur lmnp gratuit", 1100, 26, 1.2, "transactional", "LMNP",
     {TARGET: 17, "devenir-rentier.fr": 4}),
    ("meilleur etf pea", 2400, 28, 1.3, "commercial", "ETF",
     {TARGET: 12, "avenuedesinvestisseurs.fr": 2, "esi-bourse.com": 6}),

    # === Long tail: target in positions 21-100 (not actionable here) ===
    ("livret a plafond 2026", 6600, 32, 0.4, "informational", "Épargne",
     {TARGET: 35, "avenuedesinvestisseurs.fr": 2}),
    ("assurance vie meilleure", 3600, 48, 2.1, "commercial", "Assurance vie",
     {TARGET: 42, "avenuedesinvestisseurs.fr": 1}),
    ("courtier bourse en ligne", 4400, 55, 3.2, "commercial", "Courtier",
     {TARGET: 67, "avenuedesinvestisseurs.fr": 4, "esi-bourse.com": 2}),
    ("scpi rendement 2026", 2400, 38, 1.8, "commercial", "SCPI",
     {TARGET: 28}),
    ("fiscalité dividendes pea", 880, 24, 0.5, "informational", "PEA",
     {TARGET: 22, "avenuedesinvestisseurs.fr": 6}),
    ("compte titres ou pea", 1300, 28, 0.7, "commercial", "PEA",
     {TARGET: 24, "avenuedesinvestisseurs.fr": 3}),

    # === Content gaps: competitors top 10, target NOT ranking ===
    ("simulateur lmnp 2026", 5400, 30, 1.5, "transactional", "LMNP",
     {"avenuedesinvestisseurs.fr": 3, "devenir-rentier.fr": 5, "plus-riche.com": 8}),
    ("lmnp réel ou micro bic", 2900, 22, 0.7, "informational", "LMNP",
     {"devenir-rentier.fr": 2, "avenuedesinvestisseurs.fr": 4}),
    ("expert comptable lmnp", 3600, 28, 4.2, "transactional", "LMNP",
     {"devenir-rentier.fr": 6, "avenuedesinvestisseurs.fr": 3}),
    ("calcul rentabilité locative", 4400, 32, 1.1, "informational", "Immobilier",
     {"avenuedesinvestisseurs.fr": 2, "plus-riche.com": 5, "devenir-rentier.fr": 7}),
    ("achat viager fiscalité", 1300, 24, 0.6, "informational", "Viager",
     {"avenuedesinvestisseurs.fr": 4, "plus-riche.com": 9}),
    ("pinel ou lmnp", 1900, 28, 1.2, "commercial", "LMNP",
     {"avenuedesinvestisseurs.fr": 3, "devenir-rentier.fr": 6}),
    ("etf monde capitalisant", 2400, 26, 1.4, "commercial", "ETF",
     {"avenuedesinvestisseurs.fr": 2, "esi-bourse.com": 4, "plus-riche.com": 8}),
    ("dividendes aristocrats europe", 720, 22, 0.9, "informational", "Dividendes",
     {"esi-bourse.com": 3, "avenuedesinvestisseurs.fr": 7}),
    ("retraite anticipée 50 ans", 1900, 30, 0.8, "informational", "FIRE",
     {"plus-riche.com": 2, "avenuedesinvestisseurs.fr": 6}),
    ("portefeuille etf permanent", 590, 24, 1.0, "informational", "ETF",
     {"esi-bourse.com": 2, "plus-riche.com": 7}),
    ("crédit hypothécaire 2026", 880, 32, 2.4, "transactional", "Crédit",
     {"avenuedesinvestisseurs.fr": 4, "plus-riche.com": 9}),
    ("comment calculer son taux d'endettement", 8100, 35, 0.9, "informational", "Crédit",
     {"avenuedesinvestisseurs.fr": 3, "plus-riche.com": 5, "devenir-rentier.fr": 8}),

    # Strong gap signal (3+ competitors)
    ("comment investir 100000 euros", 3600, 38, 1.2, "commercial", "Investissement",
     {"avenuedesinvestisseurs.fr": 2, "plus-riche.com": 4, "esi-bourse.com": 6}),
    ("ouvrir pea credit agricole", 1900, 25, 1.8, "transactional", "PEA",
     {"avenuedesinvestisseurs.fr": 3, "plus-riche.com": 7, "esi-bourse.com": 5}),
]


# Thematic matching-terms expansions (used by Keywords Explorer)
_MATCHING_TERMS: dict[str, list[tuple]] = {
    "lmnp": [
        ("comment passer en lmnp", 1300, 22, 0.6, "informational"),
        ("lmnp plafond 23000 euros", 880, 18, 0.4, "informational"),
        ("lmnp recettes 2026", 590, 20, 0.5, "informational"),
        ("lmnp tva", 720, 24, 0.7, "informational"),
        ("lmnp et impôt sur le revenu", 1900, 26, 0.6, "informational"),
        ("lmnp avantages", 2400, 22, 0.5, "informational"),
        ("simulateur impôts lmnp", 2900, 28, 1.1, "transactional"),
    ],
    "viager": [
        ("viager libre vs occupé", 880, 18, 0.4, "commercial"),
        ("viager sans bouquet", 590, 20, 0.5, "informational"),
        ("viager avantages inconvénients", 1300, 24, 0.6, "informational"),
        ("rente viagère imposable", 1900, 26, 0.5, "informational"),
        ("acheter en viager risques", 720, 22, 0.4, "informational"),
    ],
    "vente_a_terme": [
        ("vente à terme libre", 480, 18, 0.5, "informational"),
        ("vente à terme fiscalité", 590, 22, 0.6, "informational"),
        ("différence vente à terme et viager", 720, 20, 0.4, "commercial"),
    ],
    "fire": [
        ("méthode FIRE france", 880, 26, 0.7, "informational"),
        ("4% rule retraite", 1300, 28, 0.6, "informational"),
        ("combien pour être indépendant financièrement", 720, 24, 0.5, "informational"),
        ("lean fire vs fat fire", 480, 22, 0.5, "commercial"),
    ],
    "etf_pea": [
        ("etf pea world", 2900, 30, 1.2, "commercial",),
        ("cw8 ou ewld", 1100, 22, 0.8, "commercial"),
        ("etf émergents pea", 880, 26, 0.9, "commercial"),
        ("etf pea sp500", 1900, 28, 1.0, "commercial"),
    ],
    "hcsf_credit": [
        ("dérogation hcsf", 590, 22, 0.8, "informational"),
        ("hcsf 35 ans crédit", 480, 20, 0.7, "informational"),
        ("dscr investissement locatif", 720, 24, 0.9, "informational"),
    ],
}


# Seasonality fixtures: peak month per pattern
_SEASONAL_KEYWORDS = {
    "déclaration lmnp": 5,   # May (tax declaration)
    "déclaration lmnp 2026": 5,
    "lmnp recettes 2026": 5,
    "fiscalité lmnp": 5,
    "fiscalité dividendes pea": 5,
    "livret a plafond 2026": 1,  # January (rate change)
}


def _ctr_at(position: int) -> float:
    table = {1: 0.30, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
             6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.018}
    if position in table:
        return table[position]
    if position <= 20:
        return 0.01
    if position <= 50:
        return 0.005
    return 0.002


def _slug(keyword: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")


_OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b, ">": lambda a, b: a > b,
        "=": lambda a, b: a == b}


def _parse_where(where: str | None) -> list[tuple[str, str, float]]:
    if not where:
        return []
    out: list[tuple[str, str, float]] = []
    for clause in where.split(","):
        m = re.match(r"\s*(\w+)\s*(<=|>=|<|>|=)\s*([0-9.]+)\s*$", clause)
        if not m:
            continue
        out.append((m.group(1), m.group(2), float(m.group(3))))
    return out


def _passes(row: dict[str, Any], filters: list[tuple[str, str, float]]) -> bool:
    for field, op, value in filters:
        actual = row.get(field)
        if actual is None:
            return False
        if not _OPS[op](float(actual), value):
            return False
    return True


def _build_keyword_row(
    domain: str,
    keyword: str,
    volume: int,
    kd: int,
    cpc: float,
    intent: str,
    parent_topic: str,
    position: int,
) -> dict[str, Any]:
    traffic = int(volume * _ctr_at(position))
    return {
        "keyword": keyword,
        "volume": volume,
        "keyword_difficulty": kd,
        "position": position,
        "url": f"https://{domain}/{_slug(keyword)}",
        "traffic": traffic,
        "cpc": cpc,
        "intents": [intent],
        "parent_topic": parent_topic,
        "sf": [],
    }


class MockAhrefsClient:
    """Same surface as AhrefsClient — no HTTP, deterministic fixtures."""

    def __init__(self, *, country: str = "fr", language: str = "fr",
                 seed: int = 42) -> None:
        self.country = country
        self.language = language
        self._rng = random.Random(seed)

    # ----- main endpoints -----

    def organic_keywords(
        self,
        target: str,
        *,
        limit: int = 1000,
        where: str | None = None,
        order_by: str = "traffic:desc",
        select: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = _parse_where(where)
        rows: list[dict[str, Any]] = []
        for entry in _CATALOG:
            keyword, volume, kd, cpc, intent, topic, ranks = entry
            if target not in ranks:
                continue
            row = _build_keyword_row(
                target, keyword, volume, kd, cpc, intent, topic, ranks[target]
            )
            if _passes(row, filters):
                rows.append(row)
        sort_key, _, direction = order_by.partition(":")
        sort_field = {"traffic": "traffic", "volume": "volume",
                      "position": "position"}.get(sort_key, "traffic")
        rows.sort(key=lambda r: r.get(sort_field, 0),
                  reverse=(direction != "asc"))
        return rows[:limit]

    def matching_terms(
        self,
        seed: str,
        *,
        limit: int = 200,
        match_mode: str = "terms",
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = _parse_where(where)
        # Try direct theme key, otherwise fall back to substring match on keyword
        seed_norm = seed.lower().replace(" ", "_").replace("é", "e")
        rows: list[dict[str, Any]] = []

        # Seed-keyed fixtures
        bucket_key = None
        for k in _MATCHING_TERMS:
            if k in seed_norm or seed_norm in k:
                bucket_key = k
                break
        if bucket_key:
            for entry in _MATCHING_TERMS[bucket_key]:
                kw, vol, kd, cpc, intent = entry[:5]
                row = {
                    "keyword": kw,
                    "volume": vol,
                    "keyword_difficulty": kd,
                    "cpc": cpc,
                    "intents": [intent],
                    "parent_topic": seed.title(),
                }
                if _passes(row, filters):
                    rows.append(row)

        # Also surface catalog entries containing the seed
        seed_lc = seed.lower()
        for entry in _CATALOG:
            keyword, volume, kd, cpc, intent, topic, _ = entry
            if seed_lc in keyword.lower():
                row = {
                    "keyword": keyword,
                    "volume": volume,
                    "keyword_difficulty": kd,
                    "cpc": cpc,
                    "intents": [intent],
                    "parent_topic": topic,
                }
                if _passes(row, filters):
                    rows.append(row)

        # Dedup by keyword
        seen = set()
        deduped = []
        for r in rows:
            if r["keyword"] in seen:
                continue
            seen.add(r["keyword"])
            deduped.append(r)
        deduped.sort(key=lambda r: r["volume"], reverse=True)
        return deduped[:limit]

    def volume_history(self, keyword: str) -> list[dict[str, Any]]:
        kw_lc = keyword.lower()
        peak_month = next(
            (m for k, m in _SEASONAL_KEYWORDS.items() if k in kw_lc),
            None,
        )
        history: list[dict[str, Any]] = []
        base = 100
        for month in range(1, 13):
            if peak_month and month == peak_month:
                vol = int(base * 3.5)
            elif peak_month and abs(month - peak_month) == 1:
                vol = int(base * 1.8)
            else:
                vol = int(base * (0.9 + 0.2 * self._rng.random()))
            history.append({
                "month": f"{month:02d}",
                "date": f"2025-{month:02d}-01",
                "volume": vol,
            })
        return history

    def keywords_overview(self, keywords: list[str]) -> list[dict[str, Any]]:
        return [
            {"keyword": k, "volume": 1000, "keyword_difficulty": 25,
             "cpc": 0.5, "intents": ["informational"]}
            for k in keywords
        ]

    def competitors(self, target: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {"domain": d, "common_keywords": 120, "target_keywords": 800}
            for d in ("avenuedesinvestisseurs.fr", "esi-bourse.com",
                      "devenir-rentier.fr", "plus-riche.com")
            if d != target
        ][:limit]
