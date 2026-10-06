"""Heartbeats/configurations exclus, événements explicites identifiés et dédoublés."""

import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

import blink_events


NOW = dt.datetime(2026, 10, 5, 12, tzinfo=dt.timezone.utc)
DOORBELL = {"id": 12, "network_id": 7, "name": "Porte", "enabled": True}


class EventParsingTests(unittest.TestCase):
    def event(self, **changes):
        entry = dict(id=101, network_id=7, device_id=12,
                     created_at=NOW.isoformat(), type="video", source="pir")
        entry.update(changes)
        return blink_events.normalize_event(entry, [DOORBELL], now=NOW.timestamp())

    def test_bouton_est_ring_meme_quand_detection_active(self):
        self.assertEqual(self.event(source="button")["type"], "ring")

    def test_mouvement_explicite_est_motion(self):
        self.assertEqual(self.event()["type"], "motion")

    def test_type_materiel_doorbell_ne_prouve_pas_un_appui(self):
        self.assertEqual(self.event(type="doorbell")["type"], "motion")
        self.assertIsNone(self.event(type="doorbell", source="heartbeat"))
        self.assertEqual(self.event(type="video", source="doorbell")["type"], "ring")

    def test_heartbeat_configuration_live_et_source_inconnue_sont_ignores(self):
        for source in ("heartbeat", "config", "liveview", "", "inconnu"):
            with self.subTest(source=source):
                self.assertIsNone(self.event(source=source, updated_at=NOW.isoformat(), enabled=True))
        self.assertIsNone(self.event(type="liveview", source="pir"))

    def test_dates_invalides_anciennes_ou_futures_sont_ignorees(self):
        for date in (None, "bad", "2026-10-05T12:00:00",
                     (NOW - dt.timedelta(minutes=10)).isoformat(),
                     (NOW + dt.timedelta(minutes=10)).isoformat()):
            with self.subTest(date=date):
                self.assertIsNone(self.event(created_at=date))

    def test_autre_camera_ou_reseau_est_ignore(self):
        self.assertIsNone(self.event(device_id=13))
        self.assertIsNone(self.event(network_id=8))

    def test_meme_evenement_reseau_et_media_partagent_identite(self):
        media = self.event()
        network = self.event(type="motion", source="", device_id=None, camera_id=12,
                             created_at="2026-10-05T12:00:00Z", id=202)
        self.assertEqual(media["source_event_id"], network["source_event_id"])


class EventPollingTests(unittest.IsolatedAsyncioTestCase):
    async def poll(self, network, media, home=None):
        blink = SimpleNamespace(homescreen=home or {"doorbells": [DOORBELL]},
                                get_homescreen=mock.AsyncMock())
        with mock.patch.object(blink_events.api, "request_sync_events", new=mock.AsyncMock(return_value=network)), \
             mock.patch.object(blink_events.api, "request_videos", new=mock.AsyncMock(side_effect=[media, {"media": []}])), \
             mock.patch.object(blink_events.time, "time", return_value=NOW.timestamp()):
            return await blink_events.poll(blink)

    async def test_mises_a_jour_horaires_et_armement_sans_evenement_ne_font_rien(self):
        for enabled in (False, True):
            home = {"doorbells": [dict(DOORBELL, enabled=enabled, updated_at=NOW.isoformat())]}
            self.assertEqual(await self.poll({"event": []}, {"media": []}, home), [])

    async def test_flux_reseau_et_cloud_ne_dupliquent_pas_un_mouvement(self):
        event = {"camera_id": 12, "type": "motion", "created_at": NOW.isoformat()}
        media = dict(event, camera_id=None, device_id=12, network_id=7, type="video", source="pir")
        events = await self.poll({"event": [event]}, {"media": [media]})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "motion")

    async def test_erreur_reseau_se_replie_sur_source_media_explicite(self):
        media = dict(camera_id=12, network_id=7, type="video", source="button",
                     created_at=NOW.isoformat())
        events = await self.poll(None, {"media": [media]})
        self.assertEqual(events[0]["type"], "ring")

    async def test_deux_inventaires_invalides_remontent_erreur(self):
        with self.assertRaisesRegex(RuntimeError, "aucun inventaire"):
            await self.poll(None, None)
