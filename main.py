"""Orchestrator: run all analyses and produce CSV + markdown deliverables."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from modules.ahrefs_client import AhrefsClient, AhrefsConfig, AhrefsError
from modules.mock_client import MockAhrefsClient
from modules.analyzers.content_gap import find_content_gap
from modules.analyzers.positioning import fetch_positioning
from modules.analyzers.quick_wins import find_quick_wins
from modules.analyzers.seasonality import annotate_seasonality
from modules.analyzers.thematic_research import discover_thematic_keywords
from modules.reporting.csv_export import write_csv
from modules.reporting.markdown_report import render_report

OUTPUT_DIR = Path("output")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SEO keyword analysis for esprit-riche.com")
    p.add_argument("--target", default=os.environ.get("TARGET_DOMAIN", "esprit-riche.com"))
    p.add_argument(
        "--competitors",
        default=os.environ.get(
            "COMPETITORS",
            "avenuedesinvestisseurs.fr,esi-bourse.com,devenir-rentier.fr,plus-riche.com",
        ),
    )
    p.add_argument("--no-cache", action="store_true", help="bypass disk cache")
    p.add_argument(
        "--mock",
        action="store_true",
        help="use synthetic fixtures instead of calling the Ahrefs API "
        "(no token required)",
    )
    p.add_argument(
        "--seasonality",
        action="store_true",
        help="run optional seasonality analysis (extra API calls)",
    )
    p.add_argument(
        "--skip",
        default="",
        help="comma-separated stages to skip (positioning,quick_wins,content_gap,thematic)",
    )
    return p.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.mock:
        print("[mock] running with synthetic fixtures (no API calls)")
        client = MockAhrefsClient()
    else:
        try:
            client = AhrefsClient(AhrefsConfig.from_env())
        except AhrefsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]

    import pandas as pd

    positioning_df = pd.DataFrame()
    quick_wins_df = pd.DataFrame()
    content_gap_df = pd.DataFrame()
    thematic_df = pd.DataFrame()

    if "positioning" not in skip:
        print(f"\n[1/4] Positionnement actuel — {args.target}")
        positioning_df = fetch_positioning(client, args.target)
        write_csv(positioning_df, OUTPUT_DIR / "positionnement_actuel.csv")

    if "quick_wins" not in skip and not positioning_df.empty:
        print("\n[2/4] Quick wins")
        quick_wins_df = find_quick_wins(positioning_df)
        write_csv(quick_wins_df, OUTPUT_DIR / "quick_wins.csv")

    if "content_gap" not in skip:
        print(f"\n[3/4] Content gap vs {len(competitors)} concurrents")
        content_gap_df = find_content_gap(client, args.target, competitors)
        write_csv(content_gap_df, OUTPUT_DIR / "content_gap.csv")

    if "thematic" not in skip:
        print("\n[4/4] Découverte thématique")
        thematic_df = discover_thematic_keywords(client)
        if args.seasonality and not thematic_df.empty:
            print("    + analyse de saisonnalité")
            thematic_df = annotate_seasonality(client, thematic_df)
        write_csv(thematic_df, OUTPUT_DIR / "opportunites_thematiques.csv")

    print("\n[report] Génération du rapport markdown")
    render_report(
        target_domain=args.target,
        positioning_df=positioning_df,
        quick_wins_df=quick_wins_df,
        content_gap_df=content_gap_df,
        thematic_df=thematic_df,
        output_path=OUTPUT_DIR / "rapport_seo.md",
    )
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
