"""Execute the library editor's geometry, persistence, and asynchronous UI contracts."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const pure = require("./frontend/annotations.js");
class Element {
  constructor(){this.children=[];this.dataset={};this.style={};this.value="";this.checked=false;this.disabled=false;this.textContent="";this.events={};this.classes=new Set();this.classList={add:name=>this.classes.add(name),remove:name=>this.classes.delete(name),toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
  setAttribute(name,value){this[name]=value;}
  removeAttribute(name){delete this[name];}
  addEventListener(name,callback){this.events[name]=callback;}
  querySelectorAll(){return [];}
  replaceChildren(...children){this.children=children;}
  append(...children){this.children.push(...children);}
  scrollIntoView(){} focus(){} setPointerCapture(){}
  getScreenCTM(){return {inverse:()=>({})};}
}
const nodes=new Map(), drafts=new Map();
const doc={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElementNS:()=>new Element(),querySelectorAll:()=>[],addEventListener(){}};
const context={document:doc,window:{confirm:()=>true,addEventListener(){}},Headers,Blob,URL,crypto:require("crypto").webcrypto,console,setTimeout:()=>1,clearTimeout(){},localStorage:{getItem:key=>drafts.get(key)||null,setItem:(key,value)=>drafts.set(key,value),removeItem:key=>drafts.delete(key)},DOMPoint:class{constructor(x,y){this.x=x;this.y=y;}matrixTransform(){return this;}},fetch:async()=>{throw Error("Unexpected request");}};
const source=fs.readFileSync("frontend/annotations.js","utf8").replace("void initialize();","globalThis.editor={state,save,showHistory,finishDrawing,bindEvents,renderAnnotations,categories,editAnnotation,restoreEdit,resetEditHistory,reviewObject};");
vm.runInNewContext(source,context);const editor=context.editor,state=editor.state;
function image(version=2){return {image_id:"image-1",file_name:"fish.png",version,width:10,height:10,saved:true,status:"needs_review",review_status:"needs_review",categories:[{id:1,name:"Whole fish",kind:"whole_fish",active:true},{id:2,name:"Head",kind:"anatomy",active:true},{id:3,name:"Body",kind:"anatomy",active:true}],annotations:[{annotation_id:"fish-1",class_id:1,class_name:"Whole fish",fish_id:"fish-1",bbox:[0,0,10,10],segmentation:[[0,0,10,0,0,10]],status:"needs_review",source:"ai_generated"},{annotation_id:"head-1",class_id:2,class_name:"Head",fish_id:"fish-1",bbox:[0,0,4,4],segmentation:[[0,0,4,0,0,4]],status:"needs_review",source:"ai_generated"}]};}
state.image=image();state.liveImage=image();state.selectedAnnotation="head-1";
doc.getElementById("show-masks").checked=true;
'''


def run_node(script):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node.js is required for executable annotation library checks")
    result = subprocess.run([executable, "-e", HARNESS + "\n" + script], cwd=ROOT,
                            input="", capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_redrawing_updates_captured_annotation_even_after_sidebar_selection_changes():
    result = run_node(r'''
state.drawing={replace:"head-1",points:[1,1,4,1,1,4]};state.selectedAnnotation="fish-1";
editor.finishDrawing();console.log(JSON.stringify(state.image.annotations.map(ann=>ann.segmentation)));
''')
    assert result == [[[0, 0, 10, 0, 0, 10]], [[1, 1, 4, 1, 1, 4]]]


def test_rle_hit_testing_respects_holes_boundaries_and_disconnected_runs():
    result = run_node(r'''
const mask={size:[3,3],counts:[0,4,1,4]};console.log(JSON.stringify({inside:pure.maskContains(mask,.5,.5,3,3),hole:pure.maskContains(mask,1.5,1.5,3,3),outside:pure.maskContains(mask,3,0,3,3),polygon:pure.maskContains([[0,0,3,0,0,3]],.5,.5,3,3)}));
''')
    assert result == {"inside": True, "hole": False, "outside": False, "polygon": True}


def test_fish_association_requires_an_existing_active_whole_fish():
    result = run_node(r'''
let invalid;try{pure.fishAssociation(state.image.annotations[1],"made-up",state.image.annotations,state.image.categories);}catch(error){invalid=error.message;}
console.log(JSON.stringify({parent:pure.fishAssociation(state.image.annotations[1],"fish-1",state.image.annotations,state.image.categories),unassigned:pure.fishAssociation(state.image.annotations[1],"",state.image.annotations,state.image.categories),ownId:pure.fishAssociation(state.image.annotations[0],"anything",state.image.annotations,state.image.categories),invalid,kinds:editor.categories().map(category=>category.kind)}));
''')
    assert result["parent"] == result["ownId"] == "fish-1"
    assert result["unassigned"] is None
    assert "existing whole-fish" in result["invalid"]
    assert result["kinds"] == ["whole_fish", "anatomy", "anatomy"]


def test_slow_history_response_never_discards_newer_unsaved_edits():
    result = run_node(r'''
let release;context.fetch=async()=>{await new Promise(resolve=>release=resolve);return {ok:true,json:async()=>image(1)};};
(async()=>{const loading=editor.showHistory("1");const locked=doc.getElementById("class-editor").disabled;state.image.annotations[1].class_name="Fresh edit";state.editRevision++;state.dirty=true;release();await loading;console.log(JSON.stringify({locked,name:state.image.annotations[1].class_name,dirty:state.dirty,version:state.image.version,loading:state.historyLoading}));})();
''')
    assert result == {"locked": True, "name": "Fresh edit", "dirty": True, "version": 2, "loading": False}


def test_history_responses_apply_only_the_latest_selection():
    result = run_node(r'''
const releases=[];context.fetch=async url=>{await new Promise(resolve=>releases.push(resolve));return {ok:true,json:async()=>image(url.endsWith("=1")?1:3)};};
(async()=>{const first=editor.showHistory("1"),second=editor.showHistory("3");releases[1]();await second;releases[0]();await first;console.log(JSON.stringify({version:state.image.version,selected:doc.getElementById("history-select").value,loading:state.historyLoading}));})();
''')
    assert result == {"version": 3, "selected": "3", "loading": False}


def test_failed_autosave_preserves_unsaved_annotation_and_recovery_draft():
    result = run_node(r'''
context.fetch=async()=>({ok:false,status:503,json:async()=>({detail:"Disk unavailable"})});state.dirty=true;state.image.annotations[1].class_name="Edited head";
(async()=>{const saved=await editor.save();console.log(JSON.stringify({saved,dirty:state.dirty,name:state.image.annotations[1].class_name,indicator:doc.getElementById("save-state").textContent,draft:JSON.parse(drafts.get("sardinella.annotation.draft.image-1"))}));})();
''')
    assert not result["saved"] and result["dirty"]
    assert result["indicator"] == "Save Failed"
    assert result["draft"]["annotations"][1]["class_name"] == "Edited head"
    assert result["draft"]["base_version"] == 2


def test_edits_during_save_are_sent_again_using_the_confirmed_next_version():
    result = run_node(r'''
let release;const bodies=[];context.fetch=async(url,options)=>{if(url.endsWith("/summary"))return {ok:true,json:async()=>({})};if(url.endsWith("/history"))return {ok:true,json:async()=>({versions:[]})};const body=JSON.parse(options.body);bodies.push(body);if(bodies.length===1)await new Promise(resolve=>release=resolve);return {ok:true,json:async()=>({...image(body.base_version+1),annotations:body.annotations})};};
state.dirty=true;
(async()=>{const saving=editor.save();state.image.annotations[1].class_name="Newer edit";state.editRevision++;release();await saving;console.log(JSON.stringify({versions:bodies.map(body=>body.base_version),names:bodies.map(body=>body.annotations[1].class_name),dirty:state.dirty,version:state.image.version,draft:drafts.has("sardinella.annotation.draft.image-1")}));})();
''')
    assert result == {"versions": [2, 3], "names": ["Head", "Newer edit"], "dirty": False, "version": 4, "draft": False}


def test_invalid_vertex_edit_restores_the_original_mask_without_saving_it():
    result = run_node(r'''
editor.bindEvents();state.selectedAnnotation="fish-1";const svg=doc.getElementById("annotation-svg"),vertex={dataset:{ring:"0",vertex:"0"}},target={closest:selector=>selector==="[data-vertex]"?vertex:null};
svg.events.pointerdown({button:0,clientX:0,clientY:0,target,pointerId:1,preventDefault(){}});svg.events.pointermove({clientX:5,clientY:5});svg.events.pointerup({type:"pointerup"});console.log(JSON.stringify({mask:state.image.annotations[0].segmentation,dirty:state.dirty,message:doc.getElementById("notice").textContent}));
''')
    assert result["mask"] == [[0, 0, 10, 0, 0, 10]]
    assert not result["dirty"]
    assert "previous mask has been restored" in result["message"]


def test_undo_redo_preserves_server_version_and_unedited_fish_approval():
    result = run_node(r'''
state.image.annotations[0].status="approved";state.image.annotations[0].review_status="approved";
const peer=JSON.stringify(state.image.annotations[0]);editor.resetEditHistory();
editor.editAnnotation(state.image.annotations[1],{class_id:3,class_name:"Body"});
editor.restoreEdit("undo");const undone=state.image.annotations[1].class_name;
editor.restoreEdit("redo");console.log(JSON.stringify({undone,redone:state.image.annotations[1].class_name,peerPreserved:peer===JSON.stringify(state.image.annotations[0]),version:state.image.version,dirty:state.dirty,status:state.image.status}));
''')
    assert result == {"undone": "Head", "redone": "Body", "peerPreserved": True,
                      "version": 2, "dirty": True, "status": "edited"}


def test_individual_review_saves_only_selected_object_without_approving_image():
    result = run_node(r'''
const peer=JSON.stringify(state.image.annotations[0]),sent=[];
context.fetch=async(url,options)=>{if(url.endsWith("/summary"))return {ok:true,json:async()=>({})};if(url.endsWith("/history"))return {ok:true,json:async()=>({versions:[]})};const body=JSON.parse(options.body);sent.push(body);return {ok:true,json:async()=>({...JSON.parse(JSON.stringify(state.image)),version:body.base_version+1,saved:true,annotations:body.annotations})};};
(async()=>{const saved=await editor.reviewObject("approve");console.log(JSON.stringify({saved,selected:state.image.annotations[1].status,imageStatus:state.image.status,peerPreserved:peer===JSON.stringify(state.image.annotations[0]),sentVersion:sent[0].base_version,version:state.image.version,dirty:state.dirty}));})();
''')
    assert result == {"saved": True, "selected": "approved", "imageStatus": "edited",
                      "peerPreserved": True, "sentVersion": 2, "version": 3, "dirty": False}


def test_training_panel_bridge_cannot_mutate_editor_and_blocks_dirty_export():
    result = run_node(r'''
const bridge=context.window.annotationLibrary,snapshot=bridge.getCurrent();snapshot.annotations[0].class_name="external mutation";
const clean=bridge.canExport();state.dirty=true;console.log(JSON.stringify({clean,dirty:bridge.canExport(),name:state.image.annotations[0].class_name,selection:bridge.getSelection(),frozen:Object.isFrozen(bridge)}));
''')
    assert result == {"clean": True, "dirty": False, "name": "Whole fish", "selection": [], "frozen": True}


def test_viewer_colors_follow_the_canonical_class_configuration():
    result = run_node(r'''
console.log(JSON.stringify({custom:pure.classColor(2,[{id:2,color:"#12AB34"}]),fallback:pure.classColor(2),invalid:pure.classColor(2,[{id:2,color:"invalid style"}])}));
''')
    assert result["custom"] == "#12AB34"
    assert result["invalid"] == result["fallback"]
