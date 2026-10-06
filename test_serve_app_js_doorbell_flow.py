"""Parcours réels JS des alertes : navigation, identité et courses de rendu."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class DoorbellBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node indisponible")
        source = Path(__file__).with_name("serve_app.js").read_text(encoding="utf-8")
        names = ("trouverCleCamera", "ouvrirDirectCamera", "lancerEnregistrementDepuisAlerte",
                 "renderEvents", "afficherEnregistrementsSonnette", "montrerBandeauAlerte")
        cls.functions = "\n".join(re.search(
            rf"^(?:async )?function {name}\(.*?^\}}", source, re.M | re.S).group(0)
            for name in names)
        start = source.index('if ($("btnAlertHistory"))')
        cls.history = source[start:source.index('if ($("btnAlertWatch"))', start)]
        start = source.index('$("view").onchange =')
        cls.change = source[start:source.index('// Seule cette ligne de texte', start)]

    def run_js(self, scenario):
        script = r'''
const assert = require('node:assert/strict');
const scenario = process.argv[2];
const requests=[], starts=[], stops=[], sounds=[];
let loads=0, renders=0, generationEvenements=0;
let currentDoorbellEvent=null, pageClips=0, rafraichirVignettes=false;
let active=['backyard'];
const evenementsSonnetteAnnonces=new Set();
const elements={view:{value:'events'},list:{innerHTML:'initial', querySelectorAll:()=>[]},
                count:{},btnAlertHistory:{},doorbellAlertBanner:{},
                doorbellAlertTitle:{},doorbellAlertSubtitle:{},
                camera:{value:'',options:[{value:'Porte'}]}};
const $=id=>elements[id] || null;
const h=String, t=String, cssId=String;
const lireJSON=r=>r.json();
const nomsDirectsActifs=()=>active.slice();
const stopWatch=name=>{stops.push(name);active=active.filter(n=>n!==name);};
const render=()=>renders++;
const renderLive=()=>{};
const load=async()=>{loads++;};
const loadSystem=async()=>{};
const watchLive=(key,record)=>starts.push({key,record});
const playDoorbellChime=()=>sounds.push('ding');
const localStorage={getItem:()=>{throw Error('private');},setItem:()=>{throw Error('private');}};
let system={systems:[{cameras:[{name:'Porte',key:'first'},{name:'Porte',key:'second'}]}]};
let release;
let fetch=async(url,options)=>{requests.push({url,options});return {json:async()=>({events:[]})};};
''' + self.functions + self.history + self.change + r'''
(async()=>{
  if(scenario==='identity') {
    assert.equal(await trouverCleCamera({camera:'Porte',camera_key:'second'}),'second');
    assert.equal(await trouverCleCamera('Porte'),null);
    assert.equal(await trouverCleCamera('Unknown'),null);
    assert.equal(await trouverCleCamera({camera:'Porte',camera_key:'missing'}),null);
  } else if(scenario==='history') {
    elements.view.value='live';
    elements.btnAlertHistory.onclick();
    assert.deepEqual(stops,['backyard']);
    assert.equal(elements.view.value,'events');
  } else if(scenario==='recordings') {
    await afficherEnregistrementsSonnette({camera:'Porte'});
    assert.equal(loads,1);
    assert.deepEqual(stops,['backyard']);
    assert.equal(elements.view.value,'direct');
    assert.equal(elements.camera.value,'Porte');
  } else if(scenario==='same_name_recordings') {
    const events=[{id:'one',camera:'Porte',recording_path:'first/clip.mp4'},
                  {id:'two',camera:'Porte',recording_path:'second/clip.mp4'}];
    const button={dataset:{id:'two'}};
    elements.list.querySelectorAll=selector=>selector.includes('event-view-recordings')?[button]:[];
    fetch=async()=>({json:async()=>({events})});
    let selected;
    afficherEnregistrementsSonnette=evt=>{selected=evt;};
    await renderEvents();
    button.onclick();
    assert.equal(selected.id,'two');
    assert.equal(selected.recording_path,'second/clip.mp4');
  } else if(scenario==='record') {
    active=[];
    await lancerEnregistrementDepuisAlerte({camera:'Porte',camera_key:'second'});
    assert.deepEqual(starts,[{key:'second',record:true}]);
    assert.deepEqual(requests,[]); // Aucun armement global avant admission.
  } else if(scenario==='late_response') {
    fetch=()=>new Promise(resolve=>{release=resolve;});
    const pending=renderEvents();
    elements.view.value='live';elements.list.innerHTML='new video';
    release({json:async()=>({events:[]})});
    await pending;
    assert.equal(elements.list.innerHTML,'new video');
  } else if(scenario==='alert_once') {
    const evt={id:'ring-one',camera:'Porte',type:'ring',timestamp:new Date().toISOString()};
    const settings={doorbell_chime_enabled:true,doorbell_auto_record:true};
    montrerBandeauAlerte(evt,settings);
    montrerBandeauAlerte({...evt,id:'ring-two'},settings);
    montrerBandeauAlerte(evt,settings);
    assert.equal(sounds.length,2);
    assert.deepEqual(starts,[]); // L'auto-record appartient au serveur.
    assert.deepEqual(requests,[]);
  }
  process.stdout.write(JSON.stringify({ok:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run([self.node, "-", scenario], input=script, text=True,
                                capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_camera_renommee_ou_homonyme_utilise_identite_stable(self):
        self.run_js("identity")

    def test_historique_ferme_direct_avant_changement_vue(self):
        self.run_js("history")

    def test_raccourci_videos_recharge_inventaire(self):
        self.run_js("recordings")

    def test_raccourci_videos_associe_evenement_des_cameras_homonymes(self):
        self.run_js("same_name_recordings")

    def test_recording_associe_intention_a_camera_exacte(self):
        self.run_js("record")

    def test_reponse_historique_tardive_n_ecrase_pas_direct(self):
        self.run_js("late_response")

    def test_alerte_une_fois_et_aucun_auto_record_navigateur(self):
        self.run_js("alert_once")


if __name__ == "__main__":
    unittest.main()
