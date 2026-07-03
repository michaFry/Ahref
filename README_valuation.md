# Moteur d'analyse de valorisation (marché actions)

Un moteur qui agrège 7 indicateurs macro de valorisation et de régime de
marché en un **score composite 0-100**, un verdict, une posture suggérée et une
estimation du rendement réel décennal (via le CAPE).

> ⚠️ Ces indicateurs mesurent la valorisation du **marché actions global**
> (pas une action individuelle). Le moteur décrit donc le *contexte macro*
> dans lequel toute décision sur un titre s'inscrit — à combiner avec l'analyse
> propre à l'entreprise. Outil d'orientation, pas un conseil en investissement.

## Indicateurs et pondérations

| Indicateur | Famille | Poids | Sens |
|---|---|---|---|
| Shiller CAPE Ratio | Valorisation | 1.5 | ↑ = plus cher |
| Buffett Indicator (Mkt Cap / PIB) | Valorisation | 1.5 | ↑ = plus cher |
| Tobin's Q | Valorisation | 1.3 | ↑ = plus cher |
| S&P 500 / M2 | Valorisation | 0.8 | ↑ = plus cher |
| High-yield credit spread | Sentiment | 0.7 | en U (serré = complaisance, large = stress) |
| VIX | Sentiment | 0.6 | en U (bas = complaisance, haut = peur/contrarien) |
| Yield curve (10y-2y) | Cycle | 0.9 | inversion = alerte récession |

Les 3 gauges de valorisation les plus fiables historiquement (CAPE, Buffett,
Tobin's Q) portent le poids le plus élevé. Les gauges de sentiment (VIX, spread
HY) sont **en U** : la complaisance extrême *et* le stress extrême scorent haut,
un régime « normal » score bas.

## Convention de score

Chaque indicateur est projeté sur une échelle 0-100 par interpolation linéaire
entre des points d'ancrage :

- **0** = bon marché / calme → favorable aux rendements futurs
- **50** = proche de la juste valeur
- **100** = survalorisation ou complaisance extrême → rendements futurs faibles

Le composite est la moyenne pondérée des scores. Bandes de verdict : sous-valorisé
(0-40), juste valeur (40-55), tendu (55-70), survalorisé (70-85), extrême (85+).

## Utilisation

```bash
# 1. Éditez les relevés dans data/indicators.json
# 2. Lancez le moteur (écrit data/valuation.json + rapport console)
python valuation_engine.py [data/indicators.json]

# 3. Générez le dashboard HTML
python render_valuation.py   # -> valuation.html

# Tests
python test_valuation_engine.py
```

Format d'entrée (`data/indicators.json`) — carte plate `{clé: valeur}` ; toute
clé absente est ignorée et les poids se renormalisent sur les indicateurs
présents :

```json
{
  "shiller_cape": 41.6,
  "buffett_indicator": 218,
  "tobins_q": 1.82,
  "sp500_m2": 0.325,
  "hy_credit_spread": 2.74,
  "vix": 16.6,
  "yield_curve_10y2y": 0.35
}
```

## Fichiers

- `valuation_engine.py` — moteur (scoring, composite, verdict, rendement estimé) + CLI
- `render_valuation.py` — rendu du dashboard `valuation.html`
- `test_valuation_engine.py` — tests unitaires (stdlib, aucune dépendance)
- `data/indicators.json` — relevés d'entrée
