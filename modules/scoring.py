"""Intent classification and opportunity scoring.

Ahrefs returns an `intents` field on Keywords Explorer endpoints. When it is
absent or empty (older payloads, organic-keywords response), we fall back to
a French-language heuristic.
"""

from __future__ import annotations

from typing import Iterable

INTENT_WEIGHT = {
    "transactional": 1.5,
    "commercial": 1.3,
    "informational": 1.0,
    "navigational": 0.5,
}

_TRANSACTIONAL_TOKENS = (
    "acheter", "achat", "ouvrir", "souscrire", "simulateur", "simulation",
    "devis", "comparateur", "tarif", "prix",
)
_COMMERCIAL_TOKENS = (
    "meilleur", "meilleurs", "meilleure", "comparatif", "avis", "test",
    "vs", "top", "classement",
)
_INFORMATIONAL_TOKENS = (
    "comment", "pourquoi", "qu'est-ce", "quest-ce", "quoi", "guide",
    "définition", "definition", "exemple", "calcul", "calculer",
)
_NAVIGATIONAL_TOKENS = (
    ".com", ".fr", "connexion", "login", "espace client",
)


def normalize_intent(raw: object) -> str:
    """Pick the strongest intent label from an Ahrefs `intents` value."""
    if not raw:
        return ""
    if isinstance(raw, str):
        labels = [raw]
    elif isinstance(raw, Iterable):
        labels = [str(x) for x in raw]
    else:
        return ""
    priority = ("transactional", "commercial", "informational", "navigational")
    lowered = [s.lower() for s in labels]
    for p in priority:
        if any(p in s for s in lowered):
            return p
    return lowered[0] if lowered else ""


def classify_intent_fr(keyword: str) -> str:
    kw = keyword.lower()
    if any(t in kw for t in _NAVIGATIONAL_TOKENS):
        return "navigational"
    if any(t in kw for t in _TRANSACTIONAL_TOKENS):
        return "transactional"
    if any(t in kw for t in _COMMERCIAL_TOKENS):
        return "commercial"
    if any(t in kw for t in _INFORMATIONAL_TOKENS):
        return "informational"
    return "informational"


def resolve_intent(keyword: str, ahrefs_intents: object = None) -> str:
    intent = normalize_intent(ahrefs_intents)
    if intent in INTENT_WEIGHT:
        return intent
    return classify_intent_fr(keyword)


def opportunity_score(volume: float, kd: float, intent: str) -> float:
    """score = (volume × intent_weight) / (KD + 1)"""
    weight = INTENT_WEIGHT.get(intent, 1.0)
    safe_volume = max(float(volume or 0), 0.0)
    safe_kd = max(float(kd or 0), 0.0)
    return round((safe_volume * weight) / (safe_kd + 1), 2)
