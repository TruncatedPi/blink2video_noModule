"""Événements explicites Blink, jamais déduits d'un relevé de caméra.

``homescreen.updated_at`` date aussi les heartbeats et changements de
configuration. ``enabled`` commande la détection : aucun des deux n'est une
preuve de mouvement ou d'appui. Les événements réseau et les médias portent,
eux, un type/source et une date de création. Toute source inconnue est ignorée.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from urllib.parse import urlencode

from blinkpy import api


RING_SOURCES = frozenset({"ring", "ding", "button", "button_press", "doorbell",
                          "doorbell_button", "doorbell_press"})
MOTION_SOURCES = frozenset({"motion", "motion_detected", "pir", "cv_motion"})
LIVE_SOURCES = frozenset({"liveview", "live_view", "live", "manual", "thumbnail"})
EVENT_MAX_AGE_SECONDS = 120


def event_time(value) -> dt.datetime | None:
    try:
        if not isinstance(value, str) or not value:
            return None
        instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return None
        return instant.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def event_type(entry: dict) -> str | None:
    sources = {str(entry.get(key) or "").strip().lower()
               for key in ("source", "motion_source", "event_type")}
    declared_type = str(entry.get("type") or "").strip().lower()
    # « doorbell » peut seulement décrire le matériel. Une source explicite
    # du même nom désigne un appui ; le type du matériel seul ne le prouve pas.
    if declared_type != "doorbell":
        sources.add(declared_type)
    if sources & LIVE_SOURCES:
        return None
    if sources & RING_SOURCES:
        return "ring"
    if sources & MOTION_SOURCES:
        return "motion"
    return None


def normalize_event(entry, doorbells: list[dict], network_id: str = "",
                    now: float | None = None) -> dict | None:
    if not isinstance(entry, dict) or entry.get("deleted"):
        return None
    kind = event_type(entry)
    instant = event_time(entry.get("created_at"))
    if kind is None or instant is None:
        return None
    now = time.time() if now is None else now
    age = now - instant.timestamp()
    if age < -10 or age > EVENT_MAX_AGE_SECONDS:
        return None
    nid = str(entry.get("network_id") or network_id or "")
    cid = str(entry.get("device_id") or entry.get("camera_id") or "")
    candidates = [db for db in doorbells
                  if str(db.get("network_id")) == nid
                  and (str(db.get("id")) == cid if cid else
                       str(db.get("name")) == str(entry.get("camera_name")
                                                  or entry.get("device_name") or ""))]
    if len(candidates) != 1:
        return None
    camera = candidates[0]
    cid = str(camera["id"])
    timestamp = instant.isoformat()
    # Le même événement peut paraître dans le réseau puis comme média cloud.
    # Une identité commune empêche de filmer/carillonner deux fois.
    identity = hashlib.sha256(json.dumps(
        [nid, cid, kind, timestamp], separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {"source_event_id": identity, "camera_id": cid, "network_id": nid,
            "camera": str(camera.get("name") or cid), "type": kind,
            "timestamp": timestamp, "verified": True}


async def request_event_media(blink, time: float, page: int) -> dict:
    """La v2 inclut les alertes sans vidéo (type=event), même sans abonnement.

    La v1 de blinkpy n'inventorie que les médias enregistrés. Garder ce repli
    pour les anciens comptes, mais ne pas l'utiliser si la v2 répond vide.
    Windows peut appliquer son fuseau local au strftime(gmtime, "%z") de
    blinkpy : dater explicitement en UTC évite une fenêtre située dans le futur.
    """
    since = dt.datetime.fromtimestamp(time, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = urlencode({"since": since, "page": page})
    for version in (2, 1):
        url = (f"{blink.urls.base_url}/api/v{version}/accounts/{blink.account_id}"
               f"/media/changed?{query}")
        response = await api.http_get(blink, url)
        if isinstance(response, dict) and isinstance(response.get("media"), list):
            return response
    raise RuntimeError("Inventaire des événements média indisponible")


async def poll(blink) -> list[dict]:
    await blink.get_homescreen()
    home = getattr(blink, "homescreen", None) or {}
    doorbells = [db for db in (home.get("doorbells") or []) if isinstance(db, dict)]
    if not doorbells:
        return []
    now = time.time()
    result = {}
    successes = 0
    errors = []
    for network in sorted({str(db.get("network_id")) for db in doorbells}):
        try:
            response = await api.request_sync_events(blink, network)
            entries = response.get("event") if isinstance(response, dict) else None
            if not isinstance(entries, list):
                raise RuntimeError("Inventaire des événements réseau indisponible")
            successes += 1
            for entry in entries:
                event = normalize_event(entry, doorbells, network, now)
                if event:
                    result[event["source_event_id"]] = event
        except Exception as error:
            errors.append(error)
    # Certains comptes ne publient plus le vieux flux /events/network. Les
    # événements/médias v2 sont un repli explicite : les alertes sans vidéo
    # existent aussi, sans transformer une vidéo live en alerte.
    try:
        for page in range(1, 5):
            response = await request_event_media(
                blink, time=now - EVENT_MAX_AGE_SECONDS, page=page)
            entries = response.get("media") if isinstance(response, dict) else None
            if not isinstance(entries, list):
                raise RuntimeError("Inventaire des événements média indisponible")
            successes += 1
            for entry in entries:
                event = normalize_event(entry, doorbells, now=now)
                if event:
                    result[event["source_event_id"]] = event
            if not entries:
                break
    except Exception as error:
        errors.append(error)
    if not successes:
        raise RuntimeError("Blink n'a fourni aucun inventaire d'événements valide") from errors[-1]
    return sorted(result.values(), key=lambda event: event["timestamp"])
