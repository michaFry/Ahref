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

## Analyse d'une action (ticker)

Les 7 indicateurs ci-dessus sont **macro** : identiques quel que soit le titre.
Pour analyser une **action précise**, `stock_engine.py` récupère ses propres
fondamentaux depuis Yahoo Finance (sans clé API), les score sur la même échelle
0-100 (0 = attractif/solide, 100 = cher/fragile) et les **combine avec le
contexte macro** :

```bash
python stock_engine.py AAPL [MSFT ...]   # rapport + data/stock_<TICKER>.json
python render_stock.py AAPL              # -> stock_AAPL.html
python test_stock_engine.py             # tests offline (sans réseau)
```

Trois scores sont produits :

| Score | Répond à |
|---|---|
| **Score titre** | Cette entreprise est-elle chère/bon marché et solide/fragile ? |
| **Score marché** | L'environnement est-il tendu ? (plafonne les rendements) |
| **Score global** | Perspective combinée (titre 60 % / marché 40 %) |

Métriques du titre, par famille :

- **Valorisation** : PEG, P/E, P/E anticipé, P/S, P/B
- **Rentabilité** : marge nette, ROE, marge opérationnelle
- **Croissance** : croissance BPA, croissance CA
- **Solidité** : dette/capitaux, ratio de liquidité

Les métriques « plus haut = mieux » (marges, croissance, ROE, liquidité) sont
inversées : une valeur forte donne un score bas (favorable). Toute donnée
manquante est ignorée et les poids se renormalisent.

## Fichiers

- `valuation_engine.py` — moteur macro (scoring, composite, verdict, rendement) + CLI
- `render_valuation.py` — rendu du dashboard macro `valuation.html`
- `test_valuation_engine.py` — tests du moteur macro
- `stock_engine.py` — moteur titre (fetch Yahoo + scoring + combinaison macro) + CLI
- `render_stock.py` — rendu du dashboard titre `stock_<TICKER>.html`
- `test_stock_engine.py` — tests du moteur titre (offline)
- `data/indicators.json` — relevés macro d'entrée
