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
LEAGUE_ID = "98767991302996019"  # LEC
TEAM_KEYWORDS = ["karmine corp", "kc"]  # variantes du nom d'équipe à matcher
OUTPUT_FILE = "kc_lec.ics"
MAX_PAGES = 15  # limite de sécurité pour la pagination

HEADERS = {"x-api-key": API_KEY}


def fetch_schedule_page(page_token: str | None = None) -> dict:
    params = {"hl": "fr-FR", "leagueId": LEAGUE_ID}
    if page_token:
        params["pageToken"] = page_token
    resp = requests.get(f"{API_BASE}/getSchedule", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_events() -> list[dict]:
    """
    Récupère tous les événements disponibles en paginant vers les matchs
    plus récents/futurs (pages.newer), pour couvrir toute la saison et
    pas seulement la fenêtre glissante autour d'aujourd'hui.
    """
    events = []
    seen_ids = set()

    data = fetch_schedule_page()
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
        data = fetch_schedule_page(newer_token)

    print(f"[diag] {len(events)} événement(s) LEC récupéré(s) au total.", file=sys.stderr)
    return events


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
        strategy = ev.get("match", {}).get("strategy", {})
        bo = f"Bo{strategy['count']}" if strategy.get("type") == "bestOf" else ""

        title_bits = [f"{team_names[0]} vs {team_names[1]} (LEC"]
        if block_name:
            title_bits.append(f" - {block_name}")
        title_bits.append(")")
        title = "".join(title_bits)

        event = Event()
        event.add("summary", title)
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=1))
        match_id = ev.get("match", {}).get("id", start.isoformat())
        event.add("uid", f"{match_id}@kc-lec-calendar")
        if bo:
            event.add("description", bo)
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
