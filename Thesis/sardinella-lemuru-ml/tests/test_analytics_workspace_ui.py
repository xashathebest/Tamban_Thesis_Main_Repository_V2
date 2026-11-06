"""Analytics drill-down scopes retain saved-session identity and date limits."""
from test_sam_preview_ui import node

MODULE = r'''
const fs=require("fs"),vm=require("vm");
global.window={};global.document={getElementById:()=>null};
vm.runInThisContext(fs.readFileSync("frontend/analytics-workspace.js","utf8"));
const analytics=window.TambanAnalytics;
'''

def test_month_and_week_chart_buckets_use_real_calendar_boundaries():
    actual=node(MODULE+r'''
console.log(JSON.stringify({
 month:analytics.bucketScope("2024-02-01","month"),
 week:analytics.bucketScope("2026-11-02","week"),
 day:analytics.bucketScope("2026-11-05","day"),
 missing:analytics.bucketScope("not-a-date","day")
}));
''')
    assert actual["month"] == {"start_date":"2024-02-01","end_date":"2024-02-29"}
    assert actual["week"] == {"start_date":"2026-11-02","end_date":"2026-11-08"}
    assert actual["day"] == {"start_date":"2026-11-05","end_date":"2026-11-05"}
    assert actual["missing"] == {}

def test_chart_drilldown_does_not_broaden_selected_dates_or_lose_session():
    actual=node(MODULE+r'''
const scope={session_id:"saved-run-7",start_date:"2026-11-04",end_date:"2026-11-06"};
const filters={grade:"Ungraded",reason_code:"MISSING_HEAD",start_date:"2026-11-02",end_date:"2026-11-08"};
console.log(JSON.stringify({result:analytics.recordScope(filters,scope),scope,filters}));
''')
    assert actual["result"] == {
        "scope":{"session_id":"saved-run-7","start_date":"2026-11-04","end_date":"2026-11-06"},
        "filters":{"grade":"Ungraded","reason_code":"MISSING_HEAD"},
    }
    assert actual["scope"]["start_date"] == "2026-11-04"
    assert actual["filters"]["start_date"] == "2026-11-02"

def test_a_bucket_narrows_all_session_scope_and_preserves_grade_filter():
    actual=node(MODULE+r'''
console.log(JSON.stringify(analytics.recordScope(
 {grade:"Rejected",start_date:"2026-11-05",end_date:"2026-11-05"},
 {session_id:"",start_date:"",end_date:""})));
''')
    assert actual == {
        "scope":{"session_id":"","start_date":"2026-11-05","end_date":"2026-11-05"},
        "filters":{"grade":"Rejected"},
    }

def test_accepted_history_filter_remains_exclusive_of_rejected():
    actual=node(r'''
const fs=require("fs"),vm=require("vm");
global.window={};global.document={getElementById:()=>null};
vm.runInThisContext(fs.readFileSync("frontend/session-workspace.js","utf8"));
console.log(JSON.stringify(Object.fromEntries(window.TambanSessions.historyQuery(
 {session_id:"saved-run",grade:"accepted",page:2}))));
''')
    assert actual["grade"] == "accepted"
    assert actual["session_id"] == "saved-run"
    assert actual["page"] == "2"


def test_chart_time_positions_preserve_real_gaps_between_recorded_samples():
    actual=node(MODULE+r'''
console.log(JSON.stringify({
 times:analytics.timePositions(["2026-11-05T00:00:00Z","2026-11-05T00:00:10Z","2026-11-06T00:00:00Z"],0,86400),
 categories:analytics.timePositions(["a","b","c"],0,100),
 single:analytics.timePositions(["2026-11-05"],0,100)
}));
''')
    assert actual["times"] == [0,10,86400]
    assert actual["categories"] == [0,50,100]
    assert actual["single"] == [50]

