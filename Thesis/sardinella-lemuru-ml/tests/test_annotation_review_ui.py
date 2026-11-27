"""Executable JS review contracts, including canonical masks and save failures."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
const api = require("./frontend/annotation-review.js");
class Element {
  constructor(){this.children=[];this.dataset={};this.style={};this.value="";this.attributes={};this.events={};this.disabled=false;this.classes=new Set();this.classList={add:(name)=>this.classes.add(name),remove:(name)=>this.classes.delete(name),contains:(name)=>this.classes.has(name),toggle:(name,on)=>{if(on)this.classes.add(name);else this.classes.delete(name);}};}
  setAttribute(name,value){this.attributes[name]=value;}
  addEventListener(name,callback){this.events[name]=callback;}
  replaceChildren(...children){this.children=children;}
  append(...children){this.children.push(...children);}
  querySelectorAll(){return [];}
  closest(){return null;}
}
const nodes=new Map(), doc={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement:()=>new Element(),createElementNS:()=>new Element(),createTextNode:text=>({textContent:text}),events:{},addEventListener(name,callback){this.events[name]=callback;},querySelector:()=>null};
const r=new api.Review(doc);
r.classes=[[1,"Whole fish"],[2,"Head"],[3,"Body"]];r.classKinds={1:"whole_fish",2:"part",3:"part"};
r.item={image_id:"image-1",filename:"original.png",width:100,height:100,revision:4,annotations:[]};
const part={id:"head-1",class_id:2,class_name:"Head",kind:"part",fish_id:null,bbox:[10,10,40,40],mask:[[10,10],[40,10],[40,40],[10,40]],mask_complete:true,segmentation:{format:"rle",size:[100,100],counts:[1,5,9994]}};
r.annotations=[JSON.parse(JSON.stringify(part))];r.item.annotations=JSON.parse(JSON.stringify(r.annotations));r.selected=part.id;r.ready=true;r.startedAt=performance.now()-1250;
let calls=[],loadedNext=null;global.fetch=async(url,options)=>{calls.push({url,options,body:options?.body?JSON.parse(options.body):null});return {ok:true,json:async()=>({next_image_id:"image-2"})};};
r.loadQueue=async id=>{loadedNext=id;};
'''


def node(code):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node.js is needed to exercise the annotation review client")
    result = subprocess.run([executable, "-e", HARNESS + "\n" + code], cwd=ROOT,
                            input="", text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_approval_is_one_request_for_whole_set_and_advances_after_save():
    result = node(r'''
let release;global.fetch=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});await new Promise(resolve=>release=resolve);return {ok:true,json:async()=>({next_image_id:"image-2"})};};
(async()=>{const saving=r.review("approve");await r.review("approve");const busy=r.busy;release();await saving;console.log(JSON.stringify({calls,busy,loadedNext,ready:r.ready}));})();
''')
    assert len(result["calls"]) == 1
    assert result["busy"] and not result["ready"]
    assert result["loadedNext"] == "image-2"
    body = result["calls"][0]["body"]
    assert body["action"] == "approve" and body["revision"] == 4
    assert body["review_time_ms"] >= 1250
    assert "annotations" not in body


def test_class_only_edit_preserves_exact_complex_segmentation_and_unknown_parent():
    result = node(r'''
const complex={...part,id:"complex",mask:null,mask_complete:false,contours:[[[10,10],[80,10],[80,80],[10,80]],[[25,25],[40,25],[40,40],[25,40]]],segmentation:{format:"rle",size:[100,100],counts:[3,99,9898]}};
r.annotations=[complex];r.selected=complex.id;r.editing=true;r.el.class.value="3";r.el.fish.value="";r.updateSelected();
(async()=>{await r.review("edit");console.log(JSON.stringify(calls[0].body));})();
''')
    edited = result["annotations"][0]
    assert edited["class_name"] == "Body" and edited["class_id"] == 3
    assert edited["fish_id"] is None
    assert edited["segmentation"] == {"format": "rle", "size": [100, 100], "counts": [3, 99, 9898]}
    assert len(edited["contours"]) == 2 and edited["mask"] is None
    assert "mask_changed" not in edited


def test_mask_edit_explicitly_replaces_geometry_only_for_selected_object():
    result = node(r'''
r.annotations.push({...JSON.parse(JSON.stringify(part)),id:"body-2",class_id:3,class_name:"Body"});
r.editing=true;r.el.class.value="2";r.el.fish.value="";r.drawing={id:part.id,points:[[12,12],[42,12],[30,45]]};r.finishDrawing();
(async()=>{await r.review("edit");console.log(JSON.stringify(calls[0].body));})();
''')
    head, body = result["annotations"]
    assert head["mask_changed"] and head["mask"] == [[12, 12], [42, 12], [30, 45]]
    assert head["bbox"] == [12, 12, 42, 45]
    assert "mask_changed" not in body
    assert body["segmentation"]["counts"] == [1, 5, 9994]


def test_add_missing_part_and_remove_wrong_object_without_reprocessing():
    result = node(r'''
r.editing=true;r.el.class.value="3";r.el.fish.value="fish-owner";r.drawing={id:null,points:[[12,12],[50,12],[30,45]]};r.finishDrawing();
const added=r.annotations[1];r.selected=part.id;r.el.remove.events.click();
(async()=>{await r.review("edit");console.log(JSON.stringify({added,body:calls[0].body,calls:calls.length}));})();
''')
    assert result["added"]["class_name"] == "Body"
    assert result["added"]["fish_id"] == "fish-owner"
    assert result["added"]["mask_changed"]
    assert len(result["body"]["annotations"]) == 1 and result["calls"] == 1


def test_box_only_unmapped_and_empty_results_cannot_be_approved():
    result = node(r'''
(async()=>{r.annotations[0].mask=null;await r.review("approve");const missing=r.el.message.textContent;r.annotations=[{...part,class_id:999}];await r.review("approve");const mapping=r.el.message.textContent;r.annotations=[];await r.review("approve");console.log(JSON.stringify({missing,mapping,empty:r.el.message.textContent,calls:calls.length}));})();
''')
    assert "segmentation mask" in result["missing"]
    assert "class mapping" in result["mapping"]
    assert "at least one" in result["empty"]
    assert result["calls"] == 0


def test_decline_preserves_source_contract_without_sending_positive_labels():
    result = node(r'''
r.annotations=[];r.el.reason.value="  motion blur  ";r.editing=true;r.drawing={points:[]};
(async()=>{await r.review("decline");console.log(JSON.stringify({calls,loadedNext}));})();
''')
    assert result["calls"][0]["body"]["action"] == "decline"
    assert result["calls"][0]["body"]["reason"] == "motion blur"
    assert "annotations" not in result["calls"][0]["body"]
    assert result["loadedNext"] == "image-2"


def test_failed_save_keeps_unsaved_edits_and_never_advances():
    result = node(r'''
global.fetch=async()=>({ok:false,status:409,json:async()=>({detail:"Revision conflict"})});r.editing=true;r.annotations[0].class_name="Body";r.annotations[0].class_id=3;
(async()=>{await r.review("edit");console.log(JSON.stringify({annotations:r.annotations,image:r.item.image_id,editing:r.editing,busy:r.busy,loadedNext,message:r.el.message.textContent}));})();
''')
    assert result["editing"] and not result["busy"] and result["loadedNext"] is None
    assert result["annotations"][0]["class_name"] == "Body"
    assert result["image"] == "image-1" and "Revision conflict" in result["message"]


def test_keyboard_shortcuts_do_not_approve_when_editing_or_typing():
    result = node(r'''
let actions=[];r.review=action=>actions.push(action);const event=(key,typing=false)=>({key,target:{closest:()=>typing?{}:null},preventDefault(){}});
doc.events.keydown(event("a",true));r.editing=true;doc.events.keydown(event("a"));r.editing=false;doc.events.keydown(event("a"));doc.getElementById("view-review").classList.add("hidden");doc.events.keydown(event("d"));console.log(JSON.stringify(actions));
''')
    assert result == ["approve"]


def test_complex_masks_render_all_rings_with_holes_and_no_truncated_handles():
    result = node(r'''
r.annotations=[{...part,mask:null,mask_complete:false,contours:[[[10,10],[80,10],[80,80]],[[20,20],[30,20],[30,30]]]}];r.selected=part.id;r.editing=true;r.renderCanvas();console.log(JSON.stringify(r.el.canvas.children.map(node=>node.attributes)));
''')
    paths = [node for node in result if "d" in node]
    assert len(paths) == 1 and paths[0]["fill-rule"] == "evenodd"
    assert paths[0]["d"].count("M ") == 2
    assert not any("data-vertex" in node for node in result)


def test_native_coordinate_transform_and_boundary_validation():
    result = node(r'''
const svg={createSVGPoint:()=>({matrixTransform:()=>({x:150.257,y:-4})}),getScreenCTM:()=>({inverse:()=>({})})};
console.log(JSON.stringify({point:api.pointInImage(svg,{clientX:1,clientY:2},100,100),edge:api.nearestEdge(part.mask,[25,9]),mapping:api.classEntries({"2":"Head"}),valid:api.reviewProblem([part],r.classes,100,100),outside:api.reviewProblem([{...part,mask:[[0,0],[200,0],[0,10]]}],r.classes,100,100)}));
''')
    assert result["point"] == [100, 0]
    assert result["edge"] == 1 and result["mapping"] == [[2, "Head"]]
    assert result["valid"] is None and "outside" in result["outside"]


def test_tiny_disconnected_components_do_not_reject_or_truncate_canonical_masks():
    result = node(r'''
const item={...part,mask:null,mask_complete:false,contours:[[[10,10],[80,10],[80,80]],[[90,90]]],segmentation:{size:[100,100],counts:[1,99,9900]}};
console.log(JSON.stringify({valid:api.reviewProblem([item],r.classes,100,100),editable:api.editableMask(item),rings:api.rings(item)}));
''')
    assert result["valid"] is None and not result["editable"]
    assert result["rings"][1] == [[90, 90]]


def test_existing_grade_review_is_preserved_with_isolated_asset_hooks():
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'id="review-body"' in html and 'id="review-table-wrap"' in html
    assert 'id="annotation-review"' in html and 'id="annotation-canvas"' in html
    assert '/assets/annotation-review.js' in html and '/assets/annotation-review.css' in html
    for action in ("approve", "edit", "decline"):
        assert f'id="annotation-{action}"' in html
