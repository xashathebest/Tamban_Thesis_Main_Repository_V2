"""Exposure UI coalesces live updates and keeps controls in sync with readbacks."""
from test_sam_preview_ui import node


HARNESS = r'''
const fs=require("fs"), vm=require("vm");
const source=fs.readFileSync("frontend/app.js","utf8");
function include(name) {
  const start=source.indexOf(`function ${name}(`);
  if(start<0)throw new Error(`Missing ${name}`);
  const next=source.slice(start+1).search(/\n(?:async )?function /);
  const beginning=source.slice(start-6,start)==="async "?start-6:start;
  vm.runInThisContext(source.slice(beginning,next<0?source.length:start+1+next));
}
global.elements={};
for(const key of ["exposureMode","exposureEv","exposureValue","exposureReset","exposureSource","exposureStatus"])
  elements[key]={value:"0",textContent:"",disabled:false,classList:{toggle(){}}};
global.finiteNumber=value=>value==null||!Number.isFinite(Number(value))?null:Number(value);
global.cameraCalibrationStatus={available:true,locked:true,calibration_mode:false,exposure:{available:true,mode:"manual",ev:0,source:"software"}};
global.exposureTimer=null;global.exposurePending=null;global.exposureRequestInFlight=false;
global.exposureRefreshInFlight=false;global.exposureLastRefresh=0;global.exposureRevision=0;
global.timers=new Map();let timerId=0;
global.setTimeout=fn=>{const id=++timerId;timers.set(id,fn);return id;};
global.clearTimeout=id=>timers.delete(id);
global.fireTimers=()=>{const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());};
global.calls=[];
global.fetch=(path,options)=>new Promise(resolve=>calls.push({path,payload:options?.body?JSON.parse(options.body):null,resolve}));
global.flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
global.respond=(index,exposure,ok=true)=>calls[index].resolve({ok,json:async()=>({success:ok,camera:{...cameraCalibrationStatus,exposure},detail:ok?undefined:"Camera disconnected"})});
for(const name of ["exposureEvText","setExposureMessage","renderCameraExposure","refreshCameraExposure","queueCameraExposure","sendCameraExposure"])include(name);
global.renderCameraCalibration=status=>{cameraCalibrationStatus=status;renderCameraExposure(status);};
'''


def test_drag_updates_are_debounced_serialized_and_only_latest_pending_value_is_sent():
    actual = node(HARNESS + r'''
(async()=>{
queueCameraExposure({mode:"manual",ev:0.2},true);
queueCameraExposure({mode:"manual",ev:0.6},true);
const before=calls.length;fireTimers();
queueCameraExposure({mode:"manual",ev:1.1},true);
queueCameraExposure({mode:"manual",ev:1.7},true);fireTimers();
elements.exposureEv.value="1.7";elements.exposureValue.textContent="+1.7 EV";
const during=calls.length;
respond(0,{mode:"manual",ev:0.6,source:"software"});await flush();
const after=calls.length;
const whileNewerPending=elements.exposureValue.textContent;
respond(1,{mode:"manual",ev:1.7,source:"software"});await flush();
console.log(JSON.stringify({before,during,after,whileNewerPending,payloads:calls.map(call=>call.payload),paths:calls.map(call=>call.path),value:elements.exposureValue.textContent,busy:exposureRequestInFlight}));
})();
''')
    assert (actual["before"], actual["during"], actual["after"]) == (0, 1, 2)
    assert actual["payloads"] == [{"mode": "manual", "ev": 0.6}, {"mode": "manual", "ev": 1.7}]
    assert actual["paths"] == ["/api/camera/exposure", "/api/camera/exposure"]
    assert actual["whileNewerPending"] == "+1.7 EV"
    assert actual["value"] == "+1.7 EV" and not actual["busy"]


def test_reset_replaces_pending_slider_updates_and_does_not_restart_camera():
    actual = node(HARNESS + r'''
(async()=>{
queueCameraExposure({mode:"manual",ev:0.8});
queueCameraExposure({mode:"manual",ev:1.9},true);
queueCameraExposure({reset:true});
respond(0,{mode:"manual",ev:0.8,source:"software"});await flush();
respond(1,{mode:"auto",ev:0,source:"none"});await flush();
console.log(JSON.stringify({payloads:calls.map(call=>call.payload),paths:calls.map(call=>call.path),mode:elements.exposureMode.value,value:elements.exposureValue.textContent,disabled:elements.exposureEv.disabled,timers:timers.size}));
})();
''')
    assert actual["payloads"] == [{"mode": "manual", "ev": 0.8}, {"reset": True}]
    assert all(path == "/api/camera/exposure" for path in actual["paths"])
    assert actual["mode"] == "auto" and actual["value"] == "+0.0 EV"
    assert actual["disabled"] and actual["timers"] == 0


def test_locked_hardware_does_not_disable_manual_preview_and_offline_camera_disables_controls():
    actual = node(HARNESS + r'''
renderCameraExposure(cameraCalibrationStatus);
const live={mode:elements.exposureMode.disabled,slider:elements.exposureEv.disabled,reset:elements.exposureReset.disabled,message:elements.exposureStatus.textContent};
renderCameraExposure({...cameraCalibrationStatus,available:false});
console.log(JSON.stringify({live,offline:{mode:elements.exposureMode.disabled,slider:elements.exposureEv.disabled,reset:elements.exposureReset.disabled}}));
''')
    assert not any(actual["live"][key] for key in ("mode", "slider", "reset"))
    assert "original frames" in actual["live"]["message"]
    assert all(actual["offline"].values())


def test_rejected_request_releases_queue_and_shows_camera_error():
    actual = node(HARNESS + r'''
(async()=>{
queueCameraExposure({mode:"manual",ev:-1.0});respond(0,{},false);await flush();
console.log(JSON.stringify({busy:exposureRequestInFlight,message:elements.exposureStatus.textContent}));
})();
''')
    assert actual == {"busy": False, "message": "Camera disconnected"}


def test_stale_background_readback_cannot_overwrite_new_slider_choice():
    actual = node(HARNESS + r'''
(async()=>{
const refresh=refreshCameraExposure();
elements.exposureMode.value="manual";elements.exposureEv.value="1.4";
queueCameraExposure({mode:"manual",ev:1.4},true);
calls[0].resolve({ok:true,json:async()=>({available:true,exposure:{mode:"auto",ev:0,source:"none"}})});await refresh;
console.log(JSON.stringify({mode:elements.exposureMode.value,ev:elements.exposureEv.value,pending:exposurePending}));
})();
''')
    assert actual == {"mode": "manual", "ev": "1.4", "pending": {"mode": "manual", "ev": 1.4}}


def test_drawer_open_readback_cannot_overwrite_exposure_accepted_after_it_started():
    actual = node(HARNESS + r'''
global.loadCameraDevices=()=>{};global.setCameraCalibrationMessage=()=>{};
include("loadCameraCalibration");
(async()=>{
const loading=loadCameraCalibration();
queueCameraExposure({mode:"manual",ev:1.4});
respond(1,{mode:"manual",ev:1.4,source:"software"});await flush();
calls[0].resolve({ok:true,json:async()=>({available:true,exposure:{mode:"auto",ev:0,source:"none"}})});await loading;
console.log(JSON.stringify({mode:elements.exposureMode.value,ev:elements.exposureEv.value,status:cameraCalibrationStatus.exposure}));
})();
''')
    assert actual == {"mode": "manual", "ev": "1.4", "status": {"mode": "manual", "ev": 1.4, "source": "software"}}
