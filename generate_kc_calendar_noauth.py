#!/usr/bin/env python3
"""
Génère un calendrier .ics des matchs LEC de la Karmine Corp
en scrapant directement les pages publiques de Liquipedia
(pas de compte ni de clé API nécessaire).

Respecte les règles d'usage de Liquipedia :
- User-Agent identifiant + contact (obligatoire, sinon bloqué)
- Max 1 requête "action=parse" toutes les 30 secondes

pip install requests beautifulsoup4 icalendar

Usage :
    python3 generate_kc_calendar_noauth.py
    -> produit kc_lec.ics dans le dossier courant
"""

import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

# --- Configuration ------------------------------------------------------

WIKI = "leagueoflegends"
MATCHES_PAGE = "Liquipedia:Matches"   # page publique listant les prochains matchs
TEAM_KEYWORDS = ["karmine corp", "kc"]     # variantes du nom d'équipe à matcher
COMPETITION_KEYWORD = "lec"                # filtre approximatif sur le tournoi
OUTPUT_FILE = "kc_lec.ics"

# ⚠️ Remplace par une adresse à toi : Liquipedia bloque les User-Agent génériques.
USER_AGENT = "kc-calendar-perso/1.0 (ton.email@example.com)"

API_URL = f"https://liquipedia.net/{WIKI}/api.php"


def fetch_matches_html() -> str:
    """Récupère le HTML rendu de la page listant les prochains matchs."""
    params = {
        "action": "parse",
        "page": MATCHES_PAGE,
        "format": "json",
        "prop": "text",
    }
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(API_URL, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        sys.exit(f"Erreur API Liquipedia : {data['error']}")
    return data["parse"]["text"]["*"]


def parse_matches(html: str):
    """
    Parcourt le HTML pour en extraire les matchs.

    NOTE : Liquipedia peut changer la structure de ses templates.
    Si cette fonction ne trouve plus rien, ouvre la page dans un
    navigateur, "Inspecter l'élément" sur un match, et ajuste les
    sélecteurs CSS ci-dessous (cherche des classes contenant "match",
    "team-template", ou un attribut data-timestamp).
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    # --- Mode diagnostic --------------------------------------------
    # Affiche des infos dans les logs pour comprendre la vraie structure
    # de la page si le parsing ne trouve rien. À retirer une fois que
    # tout fonctionne correctement.
    print("=== DIAGNOSTIC ===", file=sys.stderr)
    print(f"Taille du HTML récupéré : {len(html)} caractères", file=sys.stderr)

    # Liste les classes uniques contenant "match" ou "team" pour identifier
    # les vrais noms utilisés par le template actuel de Liquipedia.
    all_classes = set()
    for el in soup.find_all(class_=True):
        classes = el.get("class")
        if isinstance(classes, list):
            all_classes.update(classes)
        elif classes:
            all_classes.add(classes)

    match_classes = sorted(c for c in all_classes if "match" in c.lower())
    team_classes = sorted(c for c in all_classes if "team" in c.lower())
    print(f"Classes contenant 'match' ({len(match_classes)}): {match_classes[:40]}", file=sys.stderr)
    print(f"Classes contenant 'team' ({len(team_classes)}): {team_classes[:40]}", file=sys.stderr)

    # Regarde la structure complète autour du premier timestamp trouvé
    first_ts = soup.select_one("[data-timestamp]")
    if first_ts:
        print("--- Contexte autour du 1er [data-timestamp] (parent puis grand-parent) ---", file=sys.stderr)
        parent = first_ts.find_parent()
        grandparent = parent.find_parent() if parent else None
        if grandparent:
            print(str(grandparent)[:3000], file=sys.stderr)
        elif parent:
            print(str(parent)[:3000], file=sys.stderr)
    print("=== FIN DIAGNOSTIC ===", file=sys.stderr)
    # ------------------------------------------------------------------

    match_blocks = soup.select("[class*='match']")
    seen = set()

    for block in match_blocks:
        ts_el = block.select_one("[data-timestamp]")
        if not ts_el:
            continue
        try:
            timestamp = int(ts_el["data-timestamp"])
        except (KeyError, ValueError):
            continue

        team_els = block.select("[class*='team-template-text']")
        team_names = [t.get_text(strip=True) for t in team_els if t.get_text(strip=True)]

        if len(team_names) < 2:
            continue

        team_a, team_b = team_names[0], team_names[1]

        # Tournoi : cherche un lien/texte proche indiquant la compétition
        tourney_el = block.find_previous(class_=re.compile("tournament|league|matches-header"))
        tournament = tourney_el.get_text(strip=True) if tourney_el else ""

        key = (timestamp, team_a, team_b)
        if key in seen:
            continue
        seen.add(key)

        matches.append(
            {
                "date": datetime.fromtimestamp(timestamp, tz=timezone.utc),
                "team_a": team_a,
                "team_b": team_b,
                "tournament": tournament,
            }
        )

    return matches


def matches_kc(team_a: str, team_b: str) -> bool:
    combined = f"{team_a} {team_b}".lower()
    return any(kw in combined for kw in TEAM_KEYWORDS)


def matches_lec(tournament: str) -> bool:
    return COMPETITION_KEYWORD in tournament.lower()


def build_calendar(matches) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//KC LEC Calendar (scraper)//perso//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Karmine Corp - LEC")
    cal.add("refresh-interval;value=duration", "PT1H")

    for m in matches:
        event = Event()
        title = f"{m['team_a']} vs {m['team_b']} ({m['tournament'] or 'LEC'})"
        event.add("summary", title)
        event.add("dtstart", m["date"])
        event.add("dtend", m["date"] + timedelta(hours=1))
        event.add(
            "uid",
            f"{m['date'].isoformat()}-{m['team_a']}-{m['team_b']}@kc-lec-calendar",
        )
        cal.add_component(event)

    return cal


def main():
    html = fetch_matches_html()
    all_matches = parse_matches(html)

    kc_matches = [
        m for m in all_matches if matches_kc(m["team_a"], m["team_b"]) and matches_lec(m["tournament"])
    ]

    if not kc_matches:
        print(
            "Aucun match trouvé avec les filtres actuels.\n"
            f"({len(all_matches)} matchs détectés au total sur la page — "
            "vérifie les mots-clés TEAM_KEYWORDS / COMPETITION_KEYWORD, "
            "ou que le parsing HTML fonctionne toujours.)"
        )

    cal = build_calendar(kc_matches)
    with open(OUTPUT_FILE, "wb") as f:
        f.write(cal.to_ical())

    print(f"{OUTPUT_FILE} généré avec {len(kc_matches)} match(s).")


if __name__ == "__main__":
    main()