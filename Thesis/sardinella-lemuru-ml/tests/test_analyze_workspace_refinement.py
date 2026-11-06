"""Analyze Media layout follows selection and completion without changing evidence."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for Analyze Media state checks")
    harness = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync('frontend/app.js','utf8');
function include(name){
 const start=source.indexOf(`function ${name}(`);
 if(start<0)throw new Error(`Missing function ${name}`);
 const next=source.slice(start+1).search(/\n(?:async )?function /);
 vm.runInThisContext(source.slice(start,next<0?source.length:start+1+next));
}
'''
    output = subprocess.run([node, "-e", harness + script], cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def test_workspace_state_distinguishes_preview_processing_and_completed_zero_fish():
    states = run_node(r'''
include('uploadWorkspaceState');
const media={name:'fish.png'};
const cases=[
 [null,false,'',[]],
 [media,false,'',[]],
 [media,true,'',[]],
 [media,false,'upload:completed',[]],
 [media,false,'upload:completed',[{id:1,quality:'Class A'}]],
 [{name:'replacement.png'},false,'',[]],
 [null,false,'',[]]
];
const output=cases.map(([file,busy,scope,rows])=>{
 global.selectedUpload=file;global.uploadInFlight=busy;
 global.resultDatasets={upload:{scope,rows,metadata:{}}};
 return uploadWorkspaceState();
});
console.log(JSON.stringify(output));
''')
    assert states == [
        {"hasMedia": False, "hasResults": False, "processing": False},
        {"hasMedia": True, "hasResults": False, "processing": False},
        {"hasMedia": True, "hasResults": False, "processing": True},
        {"hasMedia": True, "hasResults": True, "processing": False},
        {"hasMedia": True, "hasResults": True, "processing": False},
        {"hasMedia": True, "hasResults": False, "processing": False},
        {"hasMedia": False, "hasResults": False, "processing": False},
    ]


def test_layout_restores_completed_results_and_preserves_resized_split_and_grades():
    output = run_node(r'''
include('uploadWorkspaceState');include('syncUploadWorkspaceLayout');
class Element{
 constructor(){
  this.classes=new Set();this.attrs={};this.inert=false;this.hidden=false;this.dataset={};
  this.classList={toggle:(name,force)=>{if(force===undefined)force=!this.classes.has(name);force?this.classes.add(name):this.classes.delete(name);return force;},
   contains:name=>this.classes.has(name),add:(...names)=>names.forEach(name=>this.classes.add(name)),remove:(...names)=>names.forEach(name=>this.classes.delete(name))};
  this.style={values:{'--viewer-share':'76%'},setProperty:(name,value)=>{this.style.values[name]=value;}};
 }
 setAttribute(name,value){this.attrs[name]=String(value);}
 getAttribute(name){return this.attrs[name]??null;}
 querySelector(selector){return selector==='.upload-inspection-layout'?layout:null;}
}
const workspace=new Element(),layout=new Element(),results=new Element(),splitter=new Element();
global.elements={uploadWorkspace:workspace};
global.$=id=>({'upload-workspace':workspace,'upload-workspace-results':results,'upload-workspace-splitter':splitter}[id]||null);
global.document={getElementById:$};
global.requestAnimationFrame=callback=>callback();
global.refreshFishInspectionLayout=()=>{};
global.fetch=()=>{throw new Error('Layout changes must reuse cached evidence');};
const cases=[
 {file:{name:'fish.png'},busy:false,scope:''},
 {file:{name:'fish.png'},busy:true,scope:''},
 {file:{name:'fish.png'},busy:false,scope:'upload:complete'},
 {file:{name:'replacement.png'},busy:false,scope:''},
 {file:null,busy:false,scope:''},
 {file:{name:'fish.png'},busy:false,scope:'upload:cached'}
];
const snapshots=cases.map(test=>{
 global.selectedUpload=test.file;global.uploadInFlight=test.busy;
 global.resultDatasets={upload:{scope:test.scope,rows:[],metadata:{final_grade:'Class A',evidence:'cached'}}};
 const before=JSON.stringify(resultDatasets);
 syncUploadWorkspaceLayout();
 return {media:workspace.classes.has('has-media'),results:workspace.classes.has('has-results'),
  processing:workspace.classes.has('is-processing'),splitResults:layout.classes.has('has-upload-results'),
  hidden:results.getAttribute('aria-hidden'),inert:results.inert,
  split:layout.style.values['--viewer-share'],evidenceUnchanged:before===JSON.stringify(resultDatasets)};
});
console.log(JSON.stringify(snapshots));
''')
    expected = [(True, False, False), (True, False, True), (True, True, False),
                (True, False, False), (False, False, False), (True, True, False)]
    for snapshot, (media, results, processing) in zip(output, expected, strict=True):
        assert snapshot["media"] is media
        assert snapshot["results"] is snapshot["splitResults"] is results
        assert snapshot["processing"] is processing
        assert snapshot["hidden"] == str(not results).lower()
        assert snapshot["inert"] is not results
        assert snapshot["split"] == "76%"
        assert snapshot["evidenceUnchanged"]


def test_upload_file_sizes_are_compact_and_never_display_invalid_numbers():
    sizes = run_node(r'''
include('uploadFileSize');
console.log(JSON.stringify([0,1,5120,1048576,3145728,-1,NaN,Infinity].map(uploadFileSize)));
''')
    assert "KB" in sizes[2]
    assert "MB" in sizes[3]
    assert "MB" in sizes[4]
    assert all(isinstance(size, str) and not any(word in size for word in ("NaN", "Infinity", "undefined")) for size in sizes)


def test_mount_completed_zero_fish_results_keeps_the_existing_dashboard_and_exports():
    output = run_node(r'''
include('mountResultsDashboard');
let placeholderHidden=false,resultsHidden=true,parent='home',syncCalls=0;
const dashboard={exports:['CSV','PDF'],gradeGroups:['Class A','Class B','Class C','Rejected','Ungraded']};
global.elements={resultsDashboard:dashboard,uploadResults:{
 append:item=>{if(item!==dashboard)throw new Error('Dashboard was replaced');parent='upload';},
 classList:{toggle:(name,value)=>{if(name==='hidden')resultsHidden=value;}}
}};
global.document={getElementById:()=>({classList:{toggle:(name,value)=>{if(name==='hidden')placeholderHidden=value;}}})};
global.resultsHomeAnchor={after:item=>{if(item!==dashboard)throw new Error('Dashboard was replaced');parent='home';}};
global.syncUploadWorkspaceLayout=()=>syncCalls++;
global.resultDatasets={upload:{scope:'',rows:[],metadata:{}}};
mountResultsDashboard(true);
const before={placeholderHidden,resultsHidden,parent};
resultDatasets.upload.scope='upload:complete-zero-fish';
mountResultsDashboard(true);
const complete={placeholderHidden,resultsHidden,parent};
mountResultsDashboard(false);
console.log(JSON.stringify({before,complete,parent,syncCalls,dashboard}));
''')
    assert output["before"] == {"placeholderHidden": False, "resultsHidden": True, "parent": "upload"}
    assert output["complete"] == {"placeholderHidden": True, "resultsHidden": False, "parent": "upload"}
    assert output["parent"] == "home"
    assert output["syncCalls"] == 3
    assert output["dashboard"]["exports"] == ["CSV", "PDF"]
    assert len(output["dashboard"]["gradeGroups"]) == 5
