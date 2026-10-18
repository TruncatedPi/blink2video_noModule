"""Audio is muted initially, shared within a page and reset on navigation."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


def audio_source(source):
    start = source.index("let lectureMuette =")
    return source[start:source.index("// ── fin audio", start)]


class PlaybackAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node unavailable")
        cls.source = Path(__file__).with_name("serve_app.js").read_text(encoding="utf-8")
        cls.code = audio_source(cls.source)
        cls.navigation = cls.source[cls.source.index('$("view").onchange ='):
                                    cls.source.index("// Seule cette ligne de texte")]

    def run_js(self, scenario):
        script = r"""
const assert=require("node:assert/strict");
const videos=[];
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class Video {
  constructor() {
    this.isConnected=true;this._muted=false;this._volume=1;this.events={};
    this.defaultMuted=false;this.plays=0;this.blockOnce=false;this.failure=null;
    this.button={disabled:false,setAttribute(){}};
    videos.push(this);
  }
  addEventListener(name,callback){(this.events[name]||=[]).push(callback);}
  emit(name){for(const fn of this.events[name]||[])fn({target:this});}
  get muted(){return this._muted;}
  set muted(v){if(this._muted!==v){this._muted=v;queueMicrotask(()=>this.emit("volumechange"));}}
  get volume(){return this._volume;}
  set volume(v){if(this._volume!==v){this._volume=v;queueMicrotask(()=>this.emit("volumechange"));}}
  closest(){return this.live?{querySelector:()=>this.button}:null;}
  play(){this.plays++;if(this.failure)return Promise.reject(this.failure);
    if(this.blockOnce){this.blockOnce=false;return Promise.reject(Object.assign(new Error("blocked"),{name:"NotAllowedError"}));}
    return Promise.resolve();}
}
const document={querySelectorAll:()=>videos.filter(v=>v.isConnected)};
const list={querySelectorAll:()=>document.querySelectorAll(),scrollIntoView(){},querySelector:()=>null};
const view={value:"clips"};
const $=id=>id==="list"?list:id==="view"?view:{querySelector:()=>videos.at(-1)};
const h=String,t=String,cssId=String;
let system={camera_audio_enabled:true};
let pageClips=2,rafraichirVignettes=false;
const nomsDirectsActifs=()=>[],stopWatch=()=>{},render=()=>{},load=()=>{};
"""
        script += self.code + "\n" + self.navigation + "\n"
        script += r"""
(async()=>{
 const first=new Video();preparerAudioVideo(first);
 await tick();
 assert.equal(first.muted,true);
 assert.equal(first.defaultMuted,true);
 if(SCENARIO==="initial"){
   const second=new Video();preparerAudioVideo(second);await tick();
   assert.equal(second.muted,true);assert.equal(lectureMuette,true);
 } else {
   first.muted=false;await tick();
   assert.equal(lectureMuette,false);
   if(SCENARIO==="share"){
     const second=new Video();preparerAudioVideo(second);await tick();
     assert.equal(second.muted,false);
     second.muted=true;await tick();
     assert.equal(first.muted,true);assert.equal(lectureMuette,true);
   }else if(SCENARIO==="late-init"){
     const second=new Video();
     reinitialiserAudioPage();await tick();
     preparerAudioVideo(second);preparerAudioVideo(second);
     assert.equal(second.events.volumechange.length,1);
     second.muted=false;await tick();
     assert.equal(lectureMuette,false);assert.equal(first.muted,false);
   }else if(SCENARIO==="refresh"){
     first.isConnected=false;
     const replacement=new Video();preparerAudioListe();await tick();
     assert.equal(replacement.muted,false);
   }else if(SCENARIO==="navigation"){
     view.value="direct";view.onchange();await tick();
     assert.equal(first.muted,true);
     const next=new Video();preparerAudioVideo(next);await tick();
     assert.equal(next.muted,true);
   }else if(SCENARIO==="autoplay"){
     const blocked=new Video();blocked.live=true;blocked.blinkAudioDisponible=true;
     preparerAudioVideo(blocked);blocked.blockOnce=true;
     await lireVideo(blocked);await tick();
     assert.equal(blocked.muted,true);assert.equal(blocked.plays,2);
     assert.equal(blocked.button.textContent,"live.audio.listen");
     assert.equal(lectureMuette,false);
     const next=new Video();preparerAudioVideo(next);await tick();
     assert.equal(next.muted,false);
   }else if(SCENARIO==="detached"){
     reinitialiserAudioPage();first.isConnected=false;first.muted=false;await tick();
     assert.equal(lectureMuette,true);
   }else if(SCENARIO==="speaker"){
     first.live=true;first.blinkAudioDisponible=true;actualiserBoutonAudio(first);
     toggleAudio("Cam");await tick();assert.equal(first.muted,true);
     first.volume=0;await tick();toggleAudio("Cam");await tick();
     assert.equal(first.muted,false);assert.equal(first.volume,1);
     assert.equal(first.button.textContent,"live.audio.mute");
     first.blinkAudioDisponible=false;actualiserBoutonAudio(first);
     toggleAudio("Cam");assert.equal(first.muted,false);
     assert.equal(first.button.disabled,true);
     assert.equal(first.button.textContent,"live.audio.unavailable");
   }else if(SCENARIO==="volume"){
     first.volume=.4;await tick();const next=new Video();preparerAudioVideo(next);await tick();
     assert.equal(next.volume,.4);assert.equal(next.muted,false);
   }else if(SCENARIO==="failure"){
     first.failure=new Error("decode failed");
     await assert.rejects(lireVideo(first),/decode failed/);
     assert.equal(first.muted,false);
   }
 }
 console.log(JSON.stringify({ok:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
""".replace("SCENARIO", json.dumps(scenario))
        result = subprocess.run([self.node, "-"], input=script, text=True,
                                encoding="utf-8", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_initial_and_other_players_are_muted(self): self.run_js("initial")
    def test_unmute_and_remute_are_shared(self): self.run_js("share")
    def test_same_page_refresh_retains_preference(self): self.run_js("refresh")
    def test_switching_view_resets_to_muted(self): self.run_js("navigation")
    def test_autoplay_rejection_mutes_only_that_player(self): self.run_js("autoplay")
    def test_detached_player_event_cannot_unmute_new_page(self): self.run_js("detached")
    def test_live_speaker_and_missing_audio_status(self): self.run_js("speaker")
    def test_preference_reset_before_player_initialization_keeps_one_listener(self): self.run_js("late-init")
    def test_volume_is_shared_with_other_videos(self): self.run_js("volume")
    def test_media_error_is_not_misreported_as_autoplay_rejection(self): self.run_js("failure")


if __name__ == "__main__":
    unittest.main()
