"""Saved-session identity, query scoping, and report integrity in the browser module."""
from test_sam_preview_ui import node


MODULE = r'''
const fs=require("fs"),vm=require("vm");
global.window={};global.document={getElementById:()=>null};
vm.runInThisContext(fs.readFileSync("frontend/session-workspace.js","utf8"));
const sessions=window.TambanSessions;
'''


def test_original_ai_grade_is_independent_of_operator_review_and_experimental_mask_status():
    actual = node(MODULE + r'''
const cases=[
{quality:"Class B",manual_override:true,manual_grade:"Class C",analysis:{final_grade:"Class B",segmentation:{ownership_status:"ambiguous"}}},
{analysis:{final_grade:"Class A",segmentation:{reliability:"review"}}},
{analysis:{final_grade:null,provisional_grade:"Class A"},manual_grade:"Class C"},
{quality:"unexpected",analysis:{final_grade:"Class A"}},
{quality:"Class C",analysis:{final_grade:"Class A"}},
{quality:"Class A",manual_grade:"Class A",analysis:{final_grade:"Class A",feature_fusion:{schema_version:"feature_fusion_v1",final_grade:"Class C"}}},
{quality:"Class A",analysis:{final_grade:"Class A",feature_fusion:{schema_version:"feature_fusion_v1",final_grade:null}}},
];console.log(JSON.stringify(cases.map(sessions.gradeOf)));
''')
    assert actual == ["Class B", "Class A", "Ungraded", "Class A", "Class A", "Class C", "Ungraded"]


def test_history_queries_scope_identity_to_saved_session_and_keep_filters_on_every_page():
    actual = node(MODULE + r'''
console.log(JSON.stringify(Object.fromEntries(sessions.historyQuery({session_id:"saved/one",page:3,page_size:25,track_id:7,grade:"Ungraded",verdict:"NEEDS_REVIEW",reason_code:"MISSING_HEAD",evidence_region:"Body"}))));
''')
    assert actual == {"range_name": "all", "page": "3", "page_size": "25", "session_id": "saved/one", "track_id": "7", "grade": "Ungraded", "verdict": "NEEDS_REVIEW", "reason_code": "MISSING_HEAD", "evidence_region": "Body"}


def test_date_range_uses_event_date_filtering_instead_of_live_current_session():
    actual = node(MODULE + r'''
console.log(JSON.stringify(Object.fromEntries(sessions.historyQuery({start_date:"2026-11-01",end_date:"2026-11-04",session_id:"old-run",grade:"graded"}))));
''')
    assert actual["range_name"] == "custom"
    assert actual["session_id"] == "old-run"
    assert actual["grade"] == "graded"
    assert actual["start_date"] == "2026-11-01" and actual["end_date"] == "2026-11-04"


def test_pdf_report_retains_two_same_fish_ids_from_different_sessions_and_does_not_invent_parts():
    actual = node(MODULE + r'''
const rows=[{track_id:7,session_id:"session-a",quality:"Class A",analysis:{final_grade:"Class A",part_results:{Body:{present:true},Head:{present:true}}}},{track_id:7,session_id:"session-b",quality:"Ungraded",analysis:{verdict_reason_code:"HEAD_UNASSIGNED"}}];
const html=sessions.reportHtml(rows,"Saved inspection",null);
console.log(JSON.stringify({both:html.includes("session-a")&&html.includes("session-b"),grade:html.includes("Fish #7 · Class A")&&html.includes("Fish #7 · Ungraded"),tailMissing:html.includes("Tail: not recorded"),reason:html.includes("HEAD_UNASSIGNED")}));
''')
    assert all(actual.values())


def test_report_escapes_saved_strings_including_analysis_and_does_not_execute_them():
    actual = node(MODULE + r'''
const html=sessions.reportHtml([{track_id:4,session_id:'<img src=x onerror="alert(1)">',quality:"Class B",analysis:{note:"<script>attack()</script>"}}],"<unsafe title>","a&b");
console.log(JSON.stringify({safe:!html.includes("<script>")&&!html.includes("<img src=x"),escaped:html.includes("&lt;script&gt;")&&html.includes("&lt;unsafe title&gt;")&&html.includes("a&amp;b")}));
''')
    assert actual == {"safe": True, "escaped": True}
