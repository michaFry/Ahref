# Esprit Riche — Analyse SEO via API Ahrefs

Pipeline d'analyse de mots-clés SEO pour **esprit-riche.com**, branchée sur l'API
Ahrefs v3. Produit quatre CSV (positionnement actuel, quick wins, content gap,
opportunités thématiques) plus un rapport de synthèse `rapport_seo.md`.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# éditer .env pour renseigner AHREFS_API_TOKEN
```

## Lancement

```bash
python main.py                      # toutes les analyses
python main.py --skip thematic      # sauter une étape
python main.py --seasonality        # ajouter l'analyse de saisonnalité
python main.py --no-cache           # forcer le rafraîchissement
```

Sorties dans `./output/` :
- `positionnement_actuel.csv`
- `quick_wins.csv`
- `content_gap.csv`
- `opportunites_thematiques.csv`
- `rapport_seo.md`

## Architecture

```
modules/
├── ahrefs_client.py       # client HTTP, cache disque, rate limit, retry, logs
├── scoring.py             # classification d'intent + score d'opportunité
├── analyzers/
│   ├── positioning.py     # /site-explorer/organic-keywords
│   ├── quick_wins.py      # filtre positions 4-20 + estimation d'uplift
│   ├── content_gap.py     # /site-explorer/competitors-overview + diff
│   ├── thematic_research.py  # /keywords-explorer/matching-terms par cluster
│   └── seasonality.py     # /keywords-explorer/volume-history (optionnel)
└── reporting/
    ├── csv_export.py
    └── markdown_report.py
```

## Score d'opportunité

```
score = (volume × intent_weight) / (KD + 1)
```

| Intent | Weight |
|---|---|
| transactional | 1.5 |
| commercial | 1.3 |
| informational | 1.0 |
| navigational | 0.5 |

L'intent provient du champ `intents` d'Ahrefs quand il est présent ; sinon une
heuristique sur tokens FR (`acheter`, `comparatif`, `comment`...) prend le relais.

## Clusters thématiques

Configurés dans `modules/analyzers/thematic_research.py` (constante `THEMES`) :
LMNP, viager / vente à terme, indépendance financière, bourse long terme, HCSF
& crédit immobilier. Chaque seed est élargi via `keywords-explorer/matching-terms`.

## Cache & rate limit

- Cache disque JSON dans `./cache/`, clé = hash SHA-1 de `endpoint + params triés`
- TTL configurable via `CACHE_TTL_HOURS` (défaut 168 h)
- Rate limit token-bucket : `RATE_LIMIT_PER_MIN` (défaut 60)
- Retry exponentiel sur 429 / 5xx (5 tentatives, backoff 2-60 s)
- Logs dans `./logs/ahrefs.log`

## Notes API

Les noms d'endpoints et de paramètres suivent la doc publique Ahrefs v3
([docs.ahrefs.com/docs/api/reference](https://docs.ahrefs.com/docs/api/reference/)).
Certaines variantes (`volume_from` vs `min_volume`, structure des champs `intents`)
peuvent diverger selon le palier de plan : ajuster `where=` dans les analyseurs
au premier appel réel si l'API retourne une 400.

Le module `content_gap` n'utilise PAS l'endpoint dédié `content-gap`
(souvent réservé aux paliers Advanced/Enterprise). Il l'émule en croisant les
`organic-keywords` du target et de chaque concurrent.
