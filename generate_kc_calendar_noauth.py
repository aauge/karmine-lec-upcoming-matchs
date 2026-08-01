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
MATCHES_PAGE = "Liquipedia:Matches"   # page publique listant les prochains matchs (fenêtre glissante, proche uniquement)

# Pages de tournoi à interroger en plus, pour avoir tout le programme de la
# saison (y compris les matchs plus lointains, playoffs compris) que la page
# glissante ci-dessus ne montre pas encore.
# Ajoute ici d'autres splits/pages si besoin (ex: LEC/2026/Winter, playoffs...).
TOURNAMENT_PAGES = [
    "LEC/2026/Summer/Regular_Season",
    "LEC/2026/Summer/Playoffs",
]

TEAM_KEYWORDS = ["karmine corp", "kc"]     # variantes du nom d'équipe à matcher
OUTPUT_FILE = "kc_lec.ics"

# ⚠️ Remplace par une adresse à toi : Liquipedia bloque les User-Agent génériques.
USER_AGENT = "kc-calendar-perso/1.0 (ton.email@example.com)"

API_URL = f"https://liquipedia.net/{WIKI}/api.php"


def fetch_page_html(page: str) -> str:
    """Récupère le HTML rendu d'une page Liquipedia donnée."""
    params = {
        "action": "parse",
        "page": page,
        "format": "json",
        "prop": "text",
    }
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(API_URL, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        sys.exit(f"Erreur API Liquipedia pour la page '{page}' : {data['error']}")
    return data["parse"]["text"]["*"]


def parse_matches(html: str, known_tournament: str | None = None):
    """
    Parcourt le HTML pour en extraire les matchs.

    Si `known_tournament` est fourni (cas d'une page de tournoi
    spécifique, ex: "LEC/2026/Summer"), tous les matchs trouvés sont
    étiquetés avec ce nom directement, sans essayer de le déduire du
    HTML (plus simple et plus fiable dans ce cas précis).

    Structure Liquipedia (observée en juillet 2026) :
    - chaque match est contenu dans un <div class="match-info">
    - l'heure est dans un descendant avec l'attribut data-timestamp
    - les deux équipes sont dans des <div class="match-info-header-opponent">,
      le nom complet de l'équipe est dans l'attribut title="" du lien <a>
      (le texte visible n'est qu'un logo / une abréviation)
    - le tournoi est identifiable via le lien dans
      <div class="match-info-tournament">, soit par son texte
      (class="match-info-tournament-name" si présent), soit par son
      attribut href (ex: /leagueoflegends/LEC/2026/Summer/...)

    NOTE : si Liquipedia change à nouveau sa structure, il faudra
    ré-inspecter le HTML réel (voir historique de ce fichier pour
    un exemple de bloc diagnostic).
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    seen = set()

    for match_el in soup.select("div.match-info"):
        ts_el = match_el.select_one("[data-timestamp]")
        if not ts_el:
            continue
        try:
            timestamp = int(ts_el["data-timestamp"])
        except (KeyError, ValueError):
            continue

        opponent_divs = match_el.select(".match-info-header-opponent")
        team_names = []
        for opp in opponent_divs:
            name_link = opp.select_one("a[title]")
            team_names.append(name_link["title"].strip() if name_link else "TBD")
        while len(team_names) < 2:
            team_names.append("TBD")
        team_a, team_b = team_names[0], team_names[1]

        if known_tournament:
            tournament = known_tournament
            tournament_href = f"/{WIKI}/{known_tournament.replace(' ', '_')}"
        else:
            tournament_name_el = match_el.select_one(".match-info-tournament-name")
            tournament_link = match_el.select_one(".match-info-tournament a[href]")
            tournament_href = tournament_link["href"] if tournament_link else ""
            tournament_title_attr = tournament_link.get("title", "") if tournament_link else ""
            tournament = (
                tournament_name_el.get_text(strip=True)
                if tournament_name_el and tournament_name_el.get_text(strip=True)
                else (tournament_title_attr or tournament_href)
            )

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
                "tournament_href": tournament_href,
            }
        )

    label = known_tournament or "page générale"
    print(f"[diag] {len(matches)} match(s) détecté(s) sur '{label}'.", file=sys.stderr)
    return matches


def matches_kc(team_a: str, team_b: str) -> bool:
    combined = f"{team_a} {team_b}".lower()
    return any(kw in combined for kw in TEAM_KEYWORDS)


def matches_lec(tournament: str, tournament_href: str = "") -> bool:
    # Le chemin de la page Liquipedia contient l'abréviation du tournoi
    # (ex: /leagueoflegends/LEC/2026/Summer/...) : c'est plus fiable que
    # le texte affiché, qui peut être vide (juste une image) sur certains
    # matchs.
    if re.search(r"/LEC/", tournament_href):
        return True
    return bool(re.search(r"\blec\b", tournament.lower()))


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
    all_kc_matches = {}  # clé = (date, team_a, team_b) pour dédoublonner entre sources

    # Source 1 : page glissante générale (matchs proches, toutes ligues confondues)
    html = fetch_page_html(MATCHES_PAGE)
    general_matches = parse_matches(html)
    for m in general_matches:
        if matches_kc(m["team_a"], m["team_b"]) and matches_lec(m["tournament"], m["tournament_href"]):
            all_kc_matches[(m["date"], m["team_a"], m["team_b"])] = m

    # Source 2 : pages de tournoi spécifiques (programme complet de la saison,
    # y compris les matchs plus lointains que la page glissante ne montre pas)
    for page in TOURNAMENT_PAGES:
        time.sleep(30)  # respecte la limite Liquipedia : 1 requête "parse" / 30s
        tournament_html = fetch_page_html(page)
        tournament_matches = parse_matches(tournament_html, known_tournament=page)
        for m in tournament_matches:
            if matches_kc(m["team_a"], m["team_b"]):
                all_kc_matches[(m["date"], m["team_a"], m["team_b"])] = m

    kc_matches = sorted(all_kc_matches.values(), key=lambda m: m["date"])

    if not kc_matches:
        print(
            "Aucun match trouvé avec les filtres actuels.\n"
            "Vérifie les mots-clés TEAM_KEYWORDS, ou que le parsing HTML "
            "fonctionne toujours (voir les lignes [diag] ci-dessus)."
        )

    cal = build_calendar(kc_matches)
    with open(OUTPUT_FILE, "wb") as f:
        f.write(cal.to_ical())

    print(f"{OUTPUT_FILE} généré avec {len(kc_matches)} match(s).")


if __name__ == "__main__":
    main()