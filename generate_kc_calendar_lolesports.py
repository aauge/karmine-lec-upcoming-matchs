#!/usr/bin/env python3
"""
Génère un calendrier .ics des matchs LEC de la Karmine Corp
à partir de l'API JSON utilisée en interne par lolesports.com
(le site officiel de Riot Games).

Cette API n'est pas officiellement documentée par Riot, mais elle est
publique (utilisée directement par le site web, sans authentification
utilisateur) et largement utilisée par la communauté depuis des années.
La clé ci-dessous est la clé publique partagée par lolesports.com lui-même
(visible dans le code source du site), pas un secret personnel.

pip install requests icalendar

Usage :
    python3 generate_kc_calendar_lolesports.py
    -> produit kc_lec.ics dans le dossier courant
"""

import sys
from datetime import datetime, timedelta, timezone

import requests
from icalendar import Calendar, Event

# --- Configuration ------------------------------------------------------

API_BASE = "https://esports-api.lolesports.com/persisted/gw"
API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # clé publique lolesports.com

# Compétitions à surveiller. KC n'apparaîtra dans MSI/Worlds que si
# l'équipe s'est qualifiée cette année-là — sinon ces requêtes ne
# renverront simplement aucun match KC, sans erreur.
LEAGUE_IDS = {
    "LEC": "98767991302996019",
    "MSI": "98767991325878492",
    "Worlds": "98767975604431411",
}

TEAM_KEYWORDS = ["karmine corp", "kc"]  # variantes du nom d'équipe à matcher
OUTPUT_FILE = "kc_lec.ics"
MAX_PAGES = 15  # limite de sécurité pour la pagination (par ligue)

# Durée estimée d'un match selon son format, pour un événement calendrier
# plus réaliste (un Bo5 dure nettement plus longtemps qu'un Bo1).
BO_DURATIONS_HOURS = {
    1: 1.0,   # Bo1
    3: 3.0,   # Bo3
    5: 5.0,   # Bo5
}
DEFAULT_DURATION_HOURS = 1.5  # si le format n'est pas précisé

HEADERS = {"x-api-key": API_KEY}


def fetch_schedule_page(league_id: str, page_token: str | None = None) -> dict:
    params = {"hl": "fr-FR", "leagueId": league_id}
    if page_token:
        params["pageToken"] = page_token
    resp = requests.get(f"{API_BASE}/getSchedule", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_events_for_league(league_id: str, league_label: str) -> list[dict]:
    """
    Récupère tous les événements d'une ligue en paginant vers les matchs
    plus récents/futurs (pages.newer), pour couvrir toute la saison et
    pas seulement la fenêtre glissante autour d'aujourd'hui.
    """
    events = []
    seen_ids = set()

    data = fetch_schedule_page(league_id)
    for _ in range(MAX_PAGES):
        schedule = data["data"]["schedule"]
        for ev in schedule["events"]:
            ev_id = ev.get("match", {}).get("id") or f"{ev['startTime']}-{ev.get('blockName')}"
            if ev_id in seen_ids:
                continue
            seen_ids.add(ev_id)
            events.append(ev)

        newer_token = schedule.get("pages", {}).get("newer")
        if not newer_token:
            break
        data = fetch_schedule_page(league_id, newer_token)

    print(f"[diag] {len(events)} événement(s) {league_label} récupéré(s) au total.", file=sys.stderr)
    return events


def fetch_all_events() -> list[dict]:
    """Récupère les événements de toutes les ligues suivies (LEC, MSI, Worlds...)."""
    all_events = []
    for label, league_id in LEAGUE_IDS.items():
        all_events.extend(fetch_events_for_league(league_id, label))
    return all_events


def matches_kc(team_names) -> bool:
    combined = " ".join(team_names).lower()
    return any(kw in combined for kw in TEAM_KEYWORDS)


def build_calendar(events) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//KC LEC Calendar (lolesports API)//perso//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Karmine Corp - LEC")
    cal.add("refresh-interval;value=duration", "PT1H")

    for ev in events:
        if ev.get("type") != "match":
            continue

        teams = ev.get("match", {}).get("teams", [])
        team_names = [t.get("name") or t.get("code") or "TBD" for t in teams]
        while len(team_names) < 2:
            team_names.append("TBD")

        if not matches_kc(team_names):
            continue

        try:
            start = datetime.fromisoformat(ev["startTime"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue

        block_name = ev.get("blockName", "")
        league_name = ev.get("league", {}).get("name", "LEC")
        strategy = ev.get("match", {}).get("strategy", {})
        bo_count = strategy.get("count") if strategy.get("type") == "bestOf" else None
        bo_label = f"Bo{bo_count}" if bo_count else ""

        duration_hours = BO_DURATIONS_HOURS.get(bo_count, DEFAULT_DURATION_HOURS)

        title_bits = [f"{team_names[0]} vs {team_names[1]} ({league_name}"]
        if block_name:
            title_bits.append(f" - {block_name}")
        if bo_label:
            title_bits.append(f" - {bo_label}")
        title_bits.append(")")
        title = "".join(title_bits)

        event = Event()
        event.add("summary", title)
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=duration_hours))
        match_id = ev.get("match", {}).get("id", start.isoformat())
        event.add("uid", f"{match_id}@kc-lec-calendar")
        if bo_label:
            event.add("description", bo_label)
        cal.add_component(event)

    return cal


def main():
    events = fetch_all_events()
    cal = build_calendar(events)

    with open(OUTPUT_FILE, "wb") as f:
        f.write(cal.to_ical())

    n_events = sum(
        1
        for ev in events
        if ev.get("type") == "match"
        and matches_kc([t.get("name") or t.get("code") or "TBD" for t in ev.get("match", {}).get("teams", [])])
    )
    print(f"{OUTPUT_FILE} généré avec {n_events} match(s).")


if __name__ == "__main__":
    main()