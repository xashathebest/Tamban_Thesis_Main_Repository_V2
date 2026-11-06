"""Capture workspace interaction contracts without a camera, cloud or browser."""
from pathlib import Path

from test_sam_preview_ui import node


ROOT = Path(__file__).resolve().parents[1]


HARNESS = r'''
const fs = require("fs"), vm = require("vm");
class Element {
  constructor() { this.value="";this.checked=false;this.disabled=false;this.hidden=false;this.textContent="";this.children=[];this.dataset={};this.attributes={};this.listeners={};this.open=false;this.isContentEditable=false;this.classList={add(){},remove(){}}; }
  addEventListener(name,fn) { (this.listeners[name]??=[]).push(fn); }
  async emit(name,event={}) { for(const fn of this.listeners[name]??[])await fn({target:this,preventDefault(){},...event}); }
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children=children;}
  setAttribute(name,value) {this.attributes[name]=value;}
  removeAttribute(name) {delete this.attributes[name];}
  getAttribute(name) {return this.attributes[name]??null;}
  hasAttribute(name) {return name in this.attributes;}
  closest() {return null;}
  showModal() {this.open=true;}
  close() {this.open=false;}
}
const nodes=new Map(),root=new Element(),documentListeners={},windowListeners={};
function el(name){if(!nodes.has(name))nodes.set(name,new Element());return nodes.get(name);}
root.querySelector=selector=>selector==="dialog[open]"?[...nodes.values()].find(value=>value.open)??null:el(selector.replace("#dc-",""));
global.document={body:{hasAttribute(){return false;}},hidden:false,querySelector:()=>root,createElement:()=>new Element(),createTextNode:text=>({textContent:text}),addEventListener:(name,fn)=>(documentListeners[name]??=[]).push(fn)};
global.setTimeout=()=>1;global.clearTimeout=()=>{};
global.confirmAnswer=true;global.confirmations=[];
global.window={addEventListener:(name,fn)=>(windowListeners[name]??=[]).push(fn),confirm:message=>{confirmations.push(message);return confirmAnswer;},open:()=>{}};
global.calls=[];global.deferSnapshot=false;global.releaseSnapshot=null;
global.state={camera:{state:"open",device_index:0,width:1280,height:720,backend:"synthetic",readbacks:{}},session_id:"session-one",manual_available:true,run:{state:"idle",captured:0,scheduled:0,skipped:0,late:0},stats:{frames:0,manual:0,reviewed:0,confirmed_specimens:0,backlog:0},drive:{connected:false}};
global.photos=[];global.failure=null;
global.driveState={connected:false,oauth_configured:false,destination_configured:true,can_upload:false,auto_sync:false,paused:false};
global.sessionMetadata={session_name:"Session one",provisional_grade:"Unknown",conveyor:"unknown",consent:false};
window.fetch=async(path,options={})=>{
  calls.push({path,method:options.method??"GET",headers:options.headers,body:options.body?JSON.parse(options.body):null});
  if(failure&&path.endsWith(failure.path))return {ok:false,status:failure.status,json:async()=>({detail:failure.message})};
  if(path.endsWith("/status")&&!path.includes("/drive/"))return {ok:true,json:async()=>structuredClone(state)};
  if(path.endsWith("/drive/status"))return {ok:true,json:async()=>structuredClone(driveState)};
  if(path.includes("/items?"))return {ok:true,json:async()=>({items:structuredClone(photos),total:photos.length})};
  if(path.endsWith("/sessions")&&(!options.method||options.method==="GET"))return {ok:true,json:async()=>({sessions:[{session_id:"session-one",metadata:sessionMetadata}]})};
  if(path.endsWith("/snapshot")){
    if(deferSnapshot)await new Promise(resolve=>releaseSnapshot=resolve);
    const id=`photo-${photos.length+1}`,item={image_id:id,filename:`${id}.jpg`,capture_mode:"manual",captured_utc:"2026-11-05T12:00:00Z",width:1280,height:720,sha256:"a".repeat(64),sync_status:"queued",metadata:{provisional_grade:"Unknown"},quality:{warnings:[]}};
    photos.unshift(item);state.stats.frames++;state.stats.manual++;return {ok:true,json:async()=>({item})};
  }
  if(path.endsWith("/drive/pause"))driveState.paused=true;
  if(path.endsWith("/drive/resume"))driveState.paused=false;
  if(path.endsWith("/drive/sync"))return {ok:true,json:async()=>({processed:2,synced:1,failed:1})};
  if(path.endsWith("/drive/test"))return {ok:true,json:async()=>({write_test_verified:true,test_file_id:"real-confirmed-test-id"})};
  if(path.endsWith("/drive/connect"))return {ok:true,json:async()=>({authorization_url:"https://accounts.google.com/o/oauth2/v2/auth?state=public-random-state"})};
  return {ok:true,json:async()=>({session_id:"session-one"})};
};
vm.runInThisContext(fs.readFileSync("frontend/capture.js","utf8"));
global.flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
global.ready=async()=>{window.TambanCapture.onView("capture");await flush();};
global.keyboard=async(event)=>{for(const fn of documentListeners.keydown??[])await fn({repeat:false,altKey:false,ctrlKey:false,metaKey:false,target:new Element(),preventDefault(){},...event});await flush();};
'''


def test_manual_click_saves_once_without_automatic_timer_and_two_clicks_have_distinct_ids():
    actual = node(HARNESS + r'''
(async()=>{await ready();await el("snapshot").emit("click");await flush();await el("snapshot").emit("click");await flush();console.log(JSON.stringify({snapshots:calls.filter(c=>c.path.endsWith("/snapshot")),auto:calls.filter(c=>c.path.endsWith("/session/start")).length,ids:photos.map(p=>p.image_id),manual:el("count-manual").textContent,message:el("feedback").textContent}));})();
''')
    assert len(actual["snapshots"]) == 2
    assert all(call["headers"]["X-Capture-Request"] == "1" for call in actual["snapshots"])
    assert actual["auto"] == 0 and len(set(actual["ids"])) == 2
    assert actual["manual"] == "2"
    assert "Saved locally" in actual["message"] and "Queued" in actual["message"]


def test_inflight_manual_clicks_are_serialized_and_typing_or_dialog_shortcuts_are_ignored():
    actual = node(HARNESS + r'''
(async()=>{await ready();deferSnapshot=true;await el("snapshot").emit("click");await el("snapshot").emit("click");await flush();const during=calls.filter(c=>c.path.endsWith("/snapshot")).length;releaseSnapshot();await flush();deferSnapshot=false;const field=new Element();field.closest=()=>({tagName:"INPUT"});await keyboard({code:"Space",target:field});el("viewer").open=true;await keyboard({code:"Space"});el("viewer").open=false;await keyboard({code:"Space",repeat:true});await keyboard({code:"Space"});console.log(JSON.stringify({during,snapshots:calls.filter(c=>c.path.endsWith("/snapshot")).length}));})();
''')
    assert actual == {"during": 1, "snapshots": 2}


def test_camera_conflict_is_honest_and_never_calls_inspection_or_camera_settings():
    actual = node(HARNESS + r'''
(async()=>{state.camera.state="closed";state.manual_available=false;await ready();el("device").value="0";el("width").value="1920";el("height").value="1080";el("backend").value="dshow";failure={path:"/camera/start",status:409,message:"Camera in use — stop inspection manually or choose a different camera"};await el("camera-open").emit("click");await flush();console.log(JSON.stringify({disabled:el("snapshot").disabled,message:el("feedback").textContent,paths:calls.map(c=>c.path)}));})();
''')
    assert actual["disabled"]
    assert "stop inspection manually" in actual["message"]
    assert all(path.startswith("/api/capture/") for path in actual["paths"])


def test_countdown_interval_duration_and_count_remain_distinct_and_metadata_uses_boolean_consent():
    actual = node(HARNESS + r'''
(async()=>{await ready();el("countdown").value="10";el("interval").value="1";el("duration").value="5";el("target").value="25";await el("run-start").emit("click");el("consent").checked=true;el("session-name").value="Source coded session";await el("save-metadata").emit("click");console.log(JSON.stringify({run:calls.find(c=>c.path.endsWith("/session/start")).body,metadata:calls.find(c=>c.method==="PATCH"&&c.path.endsWith("/metadata")).body.metadata}));})();
''')
    assert actual["run"] == {"session_id": "session-one", "countdown": 10, "interval": 1, "duration": 5, "target_count": 25}
    assert actual["metadata"]["consent"] is True
    assert actual["metadata"]["session_name"] == "Source coded session"


def test_active_navigation_can_be_cancelled_and_never_stops_collection_automatically():
    actual = node(HARNESS + r'''
(async()=>{state.run.state="running";await ready();confirmAnswer=false;const cancelled=window.TambanCapture.canNavigate("history");confirmAnswer=true;const accepted=window.TambanCapture.canNavigate("history");window.TambanCapture.onView("history");console.log(JSON.stringify({cancelled,accepted,stops:calls.filter(c=>c.path.endsWith("/session/stop")||c.path.endsWith("/camera/stop")).length}));})();
''')
    assert actual == {"cancelled": False, "accepted": True, "stops": 0}


def test_drive_disconnected_controls_are_disabled_and_verified_results_are_not_canned_success():
    actual = node(HARNESS + r'''
(async()=>{await ready();const disconnected={connect:el("drive-connect").disabled,sync:el("drive-sync").disabled,auto:el("drive-auto").disabled};driveState={connected:true,oauth_configured:true,destination_configured:true,can_upload:true,auto_sync:false,paused:false};window.TambanCapture.onView("capture");await flush();await el("drive-sync").emit("click");const result=el("drive-feedback").textContent;const failed=el("drive-feedback").dataset.error;await el("drive-pause").emit("click");const pauseLabel=el("drive-pause").textContent;await el("drive-pause").emit("click");await el("drive-write-test").emit("click");console.log(JSON.stringify({disconnected,result,failed,pauseLabel,paths:calls.map(c=>c.path),test:el("drive-feedback").textContent}));})();
''')
    assert all(actual["disconnected"].values())
    assert "synced: 1" in actual["result"] and "failed: 1" in actual["result"] and actual["failed"] == "true"
    assert actual["pauseLabel"] == "Resume sync"
    assert "/api/capture/drive/resume" in actual["paths"]
    assert "real-confirmed-test-id" in actual["test"]


def test_capture_shell_keeps_standalone_free_of_inspection_bootstrap_and_secrets():
    standalone = (ROOT / "frontend/capture-only.html").read_text(encoding="utf-8")
    main = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    source = (ROOT / "frontend/capture.js").read_text(encoding="utf-8")
    assert "data-capture-root" in standalone and "data-capture-root" in main
    assert "capture.js" in standalone and "app.js" not in standalone
    assert 'data-view="capture"' in main
    assert "localStorage" not in source and "sessionStorage" not in source
    assert "/api/video-feed" not in source and "/api/inspection" not in source
    assert 'id="dc-grid" hidden aria-hidden="true"' in source
    assert 'id="dc-sound-toggle">' in source and 'id="dc-flash-toggle">' in source
