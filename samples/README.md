# Sample outputs (mode `--mock`)

Sorties générées par `python main.py --mock --seasonality` à partir des
fixtures synthétiques de `modules/mock_client.py`. **Aucun appel API réel** —
les volumes, KD et positions sont curated pour produire des cas de figure
représentatifs (top 3 acquis, quick wins, content gaps, saisonnalité).

À utiliser pour valider la **forme** des livrables avant d'acheter un plan
Ahrefs ; les données de production seront différentes.

| Fichier | Description |
|---|---|
| [`rapport_seo.md`](rapport_seo.md) | Rapport de synthèse markdown |
| [`positionnement_actuel.csv`](positionnement_actuel.csv) | Tous les mots-clés positionnés |
| [`quick_wins.csv`](quick_wins.csv) | Positions 4-20, KD ≤ 30, triés par uplift |
| [`content_gap.csv`](content_gap.csv) | Concurrents top 10 où le site n'apparaît pas |
| [`opportunites_thematiques.csv`](opportunites_thematiques.csv) | Découverte par cluster + saisonnalité |
