"""Historique Blink v2 : alertes réelles sans clip ni abonnement, dates UTC."""

from __future__ import annotations

import datetime as dt
import os
import queue
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-events-v2-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import blink_events
import serve


NOW = dt.datetime(2026, 10, 9, 12, tzinfo=dt.timezone.utc)
DOORBELL = dict(id=12, network_id=7, name="Front Door", enabled=True)


def event_only(source, seconds_ago=15):
    # Forme observée dans la v2 : aucune URL vidéo, source explicite conservée.
    return dict(id=101, created_at=(NOW - dt.timedelta(seconds=seconds_ago)).isoformat(),
                updated_at=NOW.isoformat(), deleted=False, device="lotus", device_id=12,
                device_name="Front Door", network_id=7, type="event", source=source,
                event_type=None, media=None, thumbnail=None, no_media_reason=None,
                primary_id=None, secondary_id=None, clip_length=None, partial=False)


class V2EventFeedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        camera = SimpleNamespace(device_id="12", network_id="7", attributes={"camera_id": 12})
        self.blink = SimpleNamespace(
            account_id=42, urls=SimpleNamespace(base_url="https://rest-example.immedia-semi.com"),
            homescreen={"doorbells": [DOORBELL], "sync_modules": [], "video_stats": {"storage": 0}},
            sync={"Home": SimpleNamespace(network_id="7", cameras={"Front Door": camera})},
            get_homescreen=mock.AsyncMock())
        self.events = [event_only("pir"), event_only("button_press", seconds_ago=30)]
        self.urls = []

        async def get(blink, url):
            self.urls.append(url)
            # The old API has no stored videos; the new API also supplies event-only entries.
            if "/api/v1/" in url or parse_qs(urlparse(url).query)["page"] == ["2"]:
                return {"media": []}
            return {"media": self.events, "event_purge_id": 500, "media_purge_id": 0}

        self.http_get = mock.AsyncMock(side_effect=get)
        self.jobs = queue.Queue()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, name, value in (
            (blink_events.api, "http_get", self.http_get),
            (blink_events.api, "request_sync_events", mock.AsyncMock(return_value=None)),
            (serve, "DOORBELL_EVENTS", []),
            (serve, "DOORBELL_SEEN_EVENTS", {}),
            (serve, "DOORBELL_RECORD_QUEUE", self.jobs),
        ):
            self.stack.enter_context(mock.patch.object(target, name, value))
        self.stack.enter_context(mock.patch.object(blink_events.time, "time", return_value=NOW.timestamp()))
        self.stack.enter_context(mock.patch.object(serve, "_sauvegarder_evenements_sonnette"))
        self.settings = dict(doorbell_auto_record=True, doorbell_auto_record_seconds=30)

    async def test_flux_v2_inclut_alertes_sans_video_et_date_requete_en_utc(self):
        with mock.patch.object(blink_events.api, "request_videos") as legacy_reader:
            response = await blink_events.request_event_media(self.blink, NOW.timestamp() - 120, page=1)
        legacy_reader.assert_not_called()
        self.assertEqual(response["media"], self.events)
        self.assertEqual(len(self.urls), 1)
        url = urlparse(self.urls[0])
        self.assertEqual(url.path, "/api/v2/accounts/42/media/changed")
        query = parse_qs(url.query)
        self.assertEqual(query["since"], ["2026-10-09T11:58:00Z"])
        self.assertEqual(query["page"], ["1"])
        self.assertEqual(blink_events.event_time(query["since"][0]).timestamp(), NOW.timestamp() - 120)

    async def test_mouvement_et_bouton_sans_cloud_planifient_enregistrement_une_fois(self):
        for _ in range(2):
            events = await serve._poll_doorbells_async(self.blink)
            serve._publier_evenements_sonnette(events, self.settings)
        self.assertEqual(len(serve.DOORBELL_EVENTS), 2)
        self.assertEqual(self.jobs.qsize(), 2)
        self.assertEqual({e["type"] for e in serve.DOORBELL_EVENTS}, {"motion", "ring"})
        for event in serve.DOORBELL_EVENTS:
            self.assertTrue(event["verified"])
            self.assertEqual(event["recording_status"], "pending")
            self.assertTrue(event["camera_key"].startswith("camera-"))
        self.assertEqual([parse_qs(urlparse(url).query)["page"] for url in self.urls],
                         [["1"], ["2"], ["1"], ["2"]])
        self.assertTrue(all("/api/v2/" in url for url in self.urls))

    async def test_v2_vide_est_valide_et_ne_declenche_pas_repli_v1(self):
        self.events = []
        self.assertEqual(await blink_events.poll(self.blink), [])
        self.assertEqual(len(self.urls), 1)
        self.assertIn("/api/v2/", self.urls[0])

    async def test_compte_ancien_se_replie_sur_v1_si_v2_indisponible(self):
        self.http_get.side_effect = [None, {"media": [dict(self.events[0], type="video", media="clip.mp4")]}]
        response = await blink_events.request_event_media(self.blink, NOW.timestamp() - 120, page=3)
        self.assertEqual(response["media"][0]["source"], "pir")
        urls = [call.args[1] for call in self.http_get.await_args_list]
        self.assertEqual([urlparse(url).path for url in urls],
                         ["/api/v2/accounts/42/media/changed", "/api/v1/accounts/42/media/changed"])
        self.assertEqual([parse_qs(urlparse(url).query)["page"] for url in urls], [["3"], ["3"]])
        self.assertEqual([parse_qs(urlparse(url).query)["since"] for url in urls],
                         [["2026-10-09T11:58:00Z"], ["2026-10-09T11:58:00Z"]])

    async def test_deux_inventaires_invalides_ne_sont_pas_un_flux_vide(self):
        self.http_get.side_effect = [None, {"message": "Unavailable"}]
        with self.assertRaisesRegex(RuntimeError, "aucun inventaire"):
            await blink_events.poll(self.blink)
        self.assertTrue(self.jobs.empty())

    async def test_erreur_reseau_remonte(self):
        self.http_get.side_effect = OSError("Blink connection lost")
        with self.assertRaisesRegex(OSError, "Blink connection lost"):
            await blink_events.request_event_media(self.blink, NOW.timestamp() - 120, page=1)

    async def test_evenements_live_heartbeat_et_anciens_ne_declenchent_pas_video(self):
        self.events += [event_only("liveview"), event_only("heartbeat"), event_only("pir", seconds_ago=3600)]
        events = await serve._poll_doorbells_async(self.blink)
        serve._publier_evenements_sonnette(events, self.settings)
        self.assertEqual(len(events), 2)
        self.assertEqual(self.jobs.qsize(), 2)


if __name__ == "__main__":
    unittest.main()
