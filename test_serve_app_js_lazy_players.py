from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class TestsLecteursClipsLazy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = Path(__file__).with_name("serve_app.js").read_text(encoding="utf-8")
        match = re.search(
            r"^function preparerLecteursClips\(\) \{.*?^\}",
            source,
            re.MULTILINE | re.DOTALL,
        )
        if match is None:
            raise AssertionError("fonction introuvable : preparerLecteursClips")
        cls.fonction = match.group(0)

    def executer(self, actions: str) -> dict:
        script = r"""
(async () => {
const events = [];
const allVideos = [];
const observers = [];

class FakeVideo {
  constructor() {
    this.id = `video-${allVideos.length + 1}`;
    this.listeners = new Map();
    this.attrs = {};
    this.parent = null;
    this.paused = true;
    this.readyState = 0;
    this.currentTime = 0;
    this.loop = false;
    this.volume = 1;
    this.muted = false;
    this.playbackRate = 1;
    this.focusCount = 0;
    this.loadCount = 0;
    this.removed = false;
    this.srcHistory = [];
    this._src = '';
    Object.defineProperty(this, 'src', {
      get: () => this._src,
      set: (value) => {
        this._src = value;
        this.currentTime = 0;
        this.readyState = 0;
        this.srcHistory.push(value);
      },
    });
    allVideos.push(this);
  }

  addEventListener(name, callback, options = {}) {
    if (options.signal?.aborted) return;
    const callbacks = this.listeners.get(name) || [];
    const entry = { callback, once: Boolean(options.once), active: true, signal: options.signal };
    entry.remove = () => {
      if (!entry.active) return;
      entry.active = false;
      const current = this.listeners.get(name) || [];
      const index = current.indexOf(entry);
      if (index >= 0) current.splice(index, 1);
      entry.signal?.removeEventListener('abort', entry.remove);
    };
    if (entry.signal) entry.signal.addEventListener('abort', entry.remove, { once: true });
    callbacks.push(entry);
    this.listeners.set(name, callbacks);
  }

  removeEventListener(name, callback) {
    for (const entry of [...(this.listeners.get(name) || [])]) {
      if (entry.callback === callback) entry.remove();
    }
  }

  dispatch(name) {
    const callbacks = [...(this.listeners.get(name) || [])];
    for (const entry of callbacks) {
      if (!entry.active) continue;
      entry.callback({ type: name, target: this });
      if (entry.once) entry.remove();
    }
  }

  setAttribute(name, value) { this.attrs[name] = String(value); }

  removeAttribute(name) {
    if (name === 'src') this._src = '';
    if (name === 'poster') this.poster = '';
    delete this.attrs[name];
    events.push(`removeAttribute:${this.id}:${name}`);
  }

  pause() {
    this.paused = true;
    events.push(`pause:${this.id}`);
    this.dispatch('pause');
  }

  load() {
    this.loadCount += 1;
    events.push(`load:${this.id}`);
  }

  remove() {
    this.removed = true;
    if (this.parent) this.parent.removeChild(this);
    events.push(`remove:${this.id}`);
  }

  focus(options) {
    this.focusCount += 1;
    this.focusOptions = options;
    document.activeElement = this;
    events.push(`focus:${this.id}`);
  }

  closest(selector) {
    return this.parent ? this.parent.closest(selector) : null;
  }
}

class FakeZone {
  constructor(id) {
    this.id = id;
    this.className = 'clip-player';
    this.tabIndex = 0;
    this.dataset = { poster: `/thumb/${id}`, src: `/media/${id}` };
    this.attrs = { 'aria-label': `clip ${id}` };
    this.child = null;
  }

  append(video) {
    this.child = video;
    video.parent = this;
    video.removed = false;
  }

  removeChild(video) {
    if (this.child === video) this.child = null;
    video.parent = null;
  }

  contains(node) {
    return node === this || node === this.child;
  }

  closest(selector) {
    return selector === '.clip-player' ? this : null;
  }

  getAttribute(name) { return this.attrs[name] ?? null; }
}

class FakeList {
  constructor(zones) {
    this.zones = zones;
    this.listeners = new Map();
  }

  querySelectorAll(selector) {
    return selector === '.clip-player' ? this.zones : [];
  }

  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) || [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }

  removeEventListener(name, callback) {
    const callbacks = this.listeners.get(name) || [];
    const index = callbacks.indexOf(callback);
    if (index >= 0) callbacks.splice(index, 1);
  }

  dispatch(name, target) {
    for (const callback of [...(this.listeners.get(name) || [])]) {
      callback({ type: name, target });
    }
  }

  listenerCount(name) { return (this.listeners.get(name) || []).length; }
}

class FakeObserver {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.observed = [];
    this.pending = [];
    this.takenRecords = 0;
    this.disconnected = false;
    this.disconnectCount = 0;
    observers.push(this);
  }

  observe(zone) { this.observed.push(zone); }

  queue(zone, isIntersecting) {
    this.pending.push({ target: zone, isIntersecting });
  }

  disconnect() {
    this.disconnected = true;
    this.disconnectCount += 1;
  }

  emit(zone, isIntersecting) {
    if (!this.disconnected) this.callback([{ target: zone, isIntersecting }]);
  }

  flush() {
    if (this.pending.length) this.callback(this.pending.splice(0));
  }

  takeRecords() {
    const records = this.pending.splice(0);
    this.takenRecords += records.length;
    return records;
  }
}

const document = {
  activeElement: null,
  pictureInPictureElement: null,
  fullscreenElement: null,
  createElement(tag) {
    if (tag !== 'video') throw Error(`unexpected element: ${tag}`);
    return new FakeVideo();
  },
};
globalThis.document = document;
globalThis.IntersectionObserver = FakeObserver;
const zones = [new FakeZone('a'), new FakeZone('b')];
const zoneA = zones[0];
const zoneB = zones[1];
const list = new FakeList(zones);
const $ = (id) => id === 'list' ? list : null;
let nettoyerLecteursClips = () => {};

FONCTION

preparerLecteursClips();
const observer = observers[0];
const checkpoints = [];
const description = (zone) => {
  const video = zone.child;
  return {
    child: video ? video.id : null,
    tabIndex: zone.tabIndex,
    poster: video ? video.poster : null,
    paused: video ? video.paused : null,
    readyState: video ? video.readyState : null,
    currentTime: video ? video.currentTime : null,
    volume: video ? video.volume : null,
    muted: video ? video.muted : null,
    playbackRate: video ? video.playbackRate : null,
    loop: video ? video.loop : null,
  };
};
const mark = (name, zone = zoneA) => checkpoints.push({ name, state: description(zone) });

ACTIONS

await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  checkpoints,
  events,
  observer: {
    rootMargin: observer.options.rootMargin,
    observed: observer.observed.map((zone) => zone.id),
    disconnected: observer.disconnected,
    disconnectCount: observer.disconnectCount,
    pending: observer.pending.length,
    takenRecords: observer.takenRecords,
  },
  listeners: {
    focusin: list.listenerCount('focusin'),
    focusout: list.listenerCount('focusout'),
  },
  videos: allVideos.map((video) => ({
    id: video.id,
    srcHistory: video.srcHistory,
    poster: video.poster,
    preload: video.preload,
    controls: video.controls,
    playsInline: video.playsInline,
    loop: video.loop,
    ariaLabel: video.attrs['aria-label'] || null,
    focusCount: video.focusCount,
    loadCount: video.loadCount,
    removed: video.removed,
  })),
}));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
""".replace("FONCTION", self.fonction).replace("ACTIONS", actions)
        resultat = subprocess.run(
            [self.node, "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        if resultat.returncode != 0:
            raise AssertionError(resultat.stderr or resultat.stdout)
        return json.loads(resultat.stdout)

    @staticmethod
    def checkpoint(sortie: dict, name: str) -> dict:
        for checkpoint in sortie["checkpoints"]:
            if checkpoint["name"] == name:
                return checkpoint["state"]
        raise AssertionError(f"checkpoint absent : {name}")

    def test_entree_et_sortie_creent_puis_liberent_un_joueur_en_pause(self):
        sortie = self.executer("""
observer.emit(zoneA, true);
mark('entered');
observer.emit(zoneA, false);
mark('exited');
""")
        self.assertEqual(self.checkpoint(sortie, "entered")["child"], "video-1")
        self.assertIsNone(self.checkpoint(sortie, "exited")["child"])
        self.assertEqual(self.checkpoint(sortie, "exited")["tabIndex"], 0)
        self.assertEqual(sortie["observer"]["rootMargin"], "600px 0px")
        self.assertEqual(sortie["observer"]["observed"], ["a", "b"])
        self.assertEqual(sortie["videos"][0]["srcHistory"], ["/media/a"])
        self.assertEqual(self.checkpoint(sortie, "entered")["poster"], "/thumb/a")
        self.assertEqual(sortie["videos"][0]["poster"], "")
        self.assertEqual(sortie["videos"][0]["loadCount"], 1)
        self.assertTrue(sortie["videos"][0]["removed"])

    def test_lecture_active_protegee_jusqua_pause_puis_liberee(self):
        sortie = self.executer("""
observer.emit(zoneA, true);
const video = zoneA.child;
video.paused = false;
observer.emit(zoneA, false);
mark('while-playing');
video.pause();
mark('after-pause');
""")
        self.assertEqual(self.checkpoint(sortie, "while-playing")["child"], "video-1")
        self.assertIsNone(self.checkpoint(sortie, "after-pause")["child"])
        self.assertIn("pause:video-1", sortie["events"])
        self.assertIn("remove:video-1", sortie["events"])

    def test_focus_protege_le_joueur_puis_focusout_le_libere(self):
        sortie = self.executer("""
observer.emit(zoneA, true);
list.dispatch('focusin', zoneA);
const video = zoneA.child;
observer.emit(zoneA, false);
mark('focused-away');
document.activeElement = null;
list.dispatch('focusout', video);
await Promise.resolve();
mark('after-focusout');
""")
        self.assertEqual(self.checkpoint(sortie, "focused-away")["child"], "video-1")
        self.assertIsNone(self.checkpoint(sortie, "after-focusout")["child"])
        self.assertEqual(sortie["videos"][0]["focusCount"], 1)

    def test_position_et_reglages_sur_remontage_avant_metadata(self):
        sortie = self.executer("""
observer.emit(zoneA, true);
const first = zoneA.child;
first.readyState = 1;
first.currentTime = 42.25;
first.volume = 0.35;
first.muted = true;
first.playbackRate = 1.5;
observer.emit(zoneA, false);
observer.emit(zoneA, true);
mark('first-remount-before-metadata');
observer.emit(zoneA, false);
observer.emit(zoneA, true);
const second = zoneA.child;
mark('second-remount-before-metadata');
second.dispatch('loadedmetadata');
mark('second-remount-after-metadata');
""")
        first_remount = self.checkpoint(sortie, "first-remount-before-metadata")
        self.assertEqual(first_remount["child"], "video-1")
        self.assertEqual(first_remount["currentTime"], 0)
        self.assertEqual(first_remount["volume"], 0.35)
        self.assertTrue(first_remount["muted"])
        self.assertEqual(first_remount["playbackRate"], 1.5)
        second_remount = self.checkpoint(sortie, "second-remount-before-metadata")
        self.assertEqual(second_remount["child"], "video-1")
        self.assertEqual(second_remount["currentTime"], 0)
        after_metadata = self.checkpoint(sortie, "second-remount-after-metadata")
        self.assertEqual(after_metadata["currentTime"], 42.25)
        self.assertEqual(after_metadata["volume"], 0.35)
        self.assertTrue(after_metadata["muted"])
        self.assertEqual(after_metadata["playbackRate"], 1.5)

    def test_plein_ecran_et_image_dans_image_proteges_jusqua_sortie(self):
        for propriete, evenement in (("fullscreenElement", "fullscreenchange"),
                                     ("pictureInPictureElement", "leavepictureinpicture")):
            with self.subTest(propriete=propriete):
                sortie = self.executer(f"""
observer.emit(zoneA, true);
const video = zoneA.child;
document.{propriete} = video;
observer.emit(zoneA, false);
mark('protected');
document.{propriete} = null;
video.dispatch('{evenement}');
mark('released');
""")
                self.assertEqual(self.checkpoint(sortie, "protected")["child"], "video-1")
                self.assertIsNone(self.checkpoint(sortie, "released")["child"])

    def test_reutilisation_reinitialise_les_reglages_et_abort_le_metadata_ancien(self):
        sortie = self.executer("""
observer.emit(zoneA, true);
const first = zoneA.child;
first.readyState = 1;
first.currentTime = 19.5;
first.volume = 0.25;
first.muted = true;
first.playbackRate = 1.75;
first.loop = true;
observer.emit(zoneA, false);
observer.emit(zoneA, true);
const second = zoneA.child;
second.readyState = 1;
second.dispatch('loadedmetadata');
mark('reused-with-state');
observer.emit(zoneA, false);
observer.emit(zoneA, true);
observer.emit(zoneA, false);
observer.emit(zoneB, true);
const third = zoneB.child;
third.dispatch('loadedmetadata');
mark('reused-for-new-clip', zoneB);
""")
        reused = self.checkpoint(sortie, "reused-with-state")
        self.assertEqual(reused["child"], "video-1")
        self.assertEqual(reused["currentTime"], 19.5)
        self.assertEqual(reused["volume"], 0.25)
        self.assertTrue(reused["muted"])
        self.assertEqual(reused["playbackRate"], 1.75)
        self.assertTrue(reused["loop"])
        new_clip = self.checkpoint(sortie, "reused-for-new-clip")
        self.assertEqual(new_clip["child"], "video-1")
        self.assertEqual(new_clip["currentTime"], 0)
        self.assertEqual(new_clip["volume"], 1)
        self.assertFalse(new_clip["muted"])
        self.assertEqual(new_clip["playbackRate"], 1)
        self.assertFalse(new_clip["loop"])
        self.assertEqual(len(sortie["videos"]), 1)
        self.assertEqual(sortie["videos"][0]["srcHistory"], ["/media/a", "/media/a", "/media/a", "/media/b"])

    def test_nettoyage_deconnecte_observer_et_force_la_liberation(self):
        sortie = self.executer("""
observer.emit(zoneA, true);
observer.emit(zoneB, true);
zoneA.child.paused = false;
observer.queue(zoneA, true);
nettoyerLecteursClips();
mark('after-cleanup', zoneA);
mark('after-cleanup-b', zoneB);
observer.flush();
observer.emit(zoneA, true);
mark('after-stale-observer', zoneA);
""")
        self.assertIsNone(self.checkpoint(sortie, "after-cleanup")["child"])
        self.assertIsNone(self.checkpoint(sortie, "after-cleanup-b")["child"])
        self.assertIsNone(self.checkpoint(sortie, "after-stale-observer")["child"])
        self.assertTrue(sortie["observer"]["disconnected"])
        self.assertEqual(sortie["observer"]["disconnectCount"], 1)
        self.assertEqual(sortie["observer"]["pending"], 0)
        self.assertEqual(sortie["observer"]["takenRecords"], 1)
        self.assertEqual(sortie["listeners"], {"focusin": 0, "focusout": 0})
        self.assertGreaterEqual(sortie["events"].count("remove:video-1"), 1)
        self.assertGreaterEqual(sortie["events"].count("remove:video-2"), 1)


if __name__ == "__main__":
    unittest.main()
