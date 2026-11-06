/* Saved-data analytics. Rendering and navigation never request inference. */
(() => {
'use strict';
const GRADES=['Class A','Class B','Class C','Rejected','Ungraded'];
const COLORS={'Class A':'#087664','Class B':'#175cba','Class C':'#b54d0a',Rejected:'#b52e40',Ungraded:'#546c7a'};
const NS='http://www.w3.org/2000/svg';
const DEFINITIONS=[
 ['grades','Fish grade distribution','Original final grades · select a category to inspect its fish','overview grades','doughnut'],
 ['activity','Inspection activity','Unique saved fish over time','overview','line'],
 ['coverage','Graded vs. Ungraded','Class A/B/C, Rejected and Ungraded remain distinct','grades','bars'],
 ['anatomy','Anatomical detection and association','Unique fish with recorded raw detections or assigned parts','evidence','bars'],
 ['reasons','Common Ungraded reasons','Recorded reasons only · one fish may have several reasons','grades evidence','bars'],
 ['performance','Session performance','AI processing FPS and camera preview FPS are separate measurements','performance','bars'],
 ['comparison','Session comparison','Unique fish by saved session in the selected scope','performance','stacked'],
 ['support','Detection confidence and grading support','Recorded evidence strength, not measured accuracy','evidence performance','bars'],
 ['part-quality','Average part quality scores','Recorded Head, Body and Tail quality support','evidence','bars'],
 ['color-trend','Colour measurement trend','Recorded whole-fish hue and yellow colour proxy over time','evidence','line'],
 ['decision-timing','Conveyor decision timing','Recorded decision latency and deadline outcomes','performance','bars']
];
const state={mounted:false,tab:'overview',sessions:[],data:null,scope:{session_id:'',start_date:'',end_date:''},mode:'',interval:'day',performance:'stage_ms',support:'detection_confidence',color:'mean_hue_deg',decision:'latency',comparisons:null,charts:new Map(),request:0,controller:null,onRecords:null,onSessions:null,loaded:false};
const $=id=>document.getElementById(id);
const number=value=>value===null||value===undefined||value===''||!Number.isFinite(Number(value))?null:Number(value);
const n=value=>Math.max(0,number(value)??0);
const fmt=value=>number(value)===null?'Not recorded':Number(value).toLocaleString(undefined,{maximumFractionDigits:1});
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e;}
function sv(tag,attrs,text){const e=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs||{}))e.setAttribute(k,String(v));if(text!==undefined)e.textContent=String(text);return e;}
function button(label,fn,cls){const b=el('button',cls||'button quiet',label);b.type='button';b.addEventListener('click',fn);return b;}
function status(text,error){const e=$('sa-status');if(e){e.textContent=text;e.classList.toggle('error',!!error);}}
function sessionLabel(s){return(s.started_at?new Date(s.started_at).toLocaleString(undefined,{dateStyle:'short',timeStyle:'short'}):'Saved session')+' · '+String(s.session_id||'').slice(-12);}
function icon(min){return'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="'+(min?'M3 8h5V3m8 0v5h5M8 21v-5H3m18 0h-5v5':'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5')+'"/></svg>';}
function options(){return'<option value="">All Sessions</option><option value="latest">Latest Session</option>'+state.sessions.map(s=>'<option value="'+esc(s.session_id)+'">'+esc(sessionLabel(s))+'</option>').join('')+'<option value="custom">Custom Date Range</option>';}
function mount(config){
 if(state.mounted)return;const target=config?.target||$('view-analytics');if(!target)return;
 state.onRecords=config?.onRecords;state.onSessions=config?.onSessions;
 target.innerHTML='<div class="session-workspace analytics-workspace ax-dashboard"><form id="sa-filters" class="ax-filterbar surface" aria-label="Analytics scope"><label>Inspection session<select id="sa-session">'+options()+'</select></label><label class="ax-date-label">From<input id="sa-start" type="date"></label><label class="ax-date-label">Through<input id="sa-end" type="date"></label><button type="submit" class="button primary">Apply</button><button type="button" id="sa-refresh" class="button quiet">Refresh</button><button type="button" id="sa-records" class="button quiet">View fish records</button></form><div class="ax-tabbar" role="tablist" aria-label="Analytics sections">'+[['overview','Overview'],['grades','Grade Analysis'],['evidence','Model Evidence'],['performance','Performance']].map(([id,label])=>'<button type="button" role="tab" id="sa-tab-'+id+'" data-analytics-tab="'+id+'" aria-selected="'+(id==='overview')+'" tabindex="'+(id==='overview'?0:-1)+'">'+label+'</button>').join('')+'</div><p class="sw-status ax-status" id="sa-status" role="status" aria-live="polite"></p><div id="sa-kpis" class="ax-kpis" aria-label="Saved inspection summary"></div><div class="ax-chart-grid" id="sa-chart-grid"></div></div>';
 for(const definition of DEFINITIONS)createChart(definition);
 $('sa-filters').addEventListener('submit',e=>{e.preventDefault();void applyScope();});
 $('sa-session').addEventListener('change',()=>{const custom=$('sa-session').value==='custom';$('sa-filters').classList.toggle('has-custom-dates',custom);if(custom)$('sa-start').focus();else{$('sa-start').value='';$('sa-end').value='';void applyScope();}});
 $('sa-refresh').addEventListener('click',()=>void refresh());$('sa-records').addEventListener('click',()=>void records({}));
 for(const tab of target.querySelectorAll('[data-analytics-tab]')){
  tab.addEventListener('click',()=>selectTab(tab.dataset.analyticsTab));
  tab.addEventListener('keydown',e=>{const tabs=[...target.querySelectorAll('[data-analytics-tab]')],i=tabs.indexOf(tab),next=e.key==='ArrowRight'?tabs[(i+1)%tabs.length]:e.key==='ArrowLeft'?tabs[(i+tabs.length-1)%tabs.length]:e.key==='Home'?tabs[0]:e.key==='End'?tabs.at(-1):null;if(next){e.preventDefault();next.focus();selectTab(next.dataset.analyticsTab);}});
 }
 document.addEventListener('fullscreenchange',syncFullscreen);
 document.addEventListener('keydown',e=>{const card=document.querySelector('.ax-chart-fullscreen-fallback');if(e.key==='Escape'&&card){e.preventDefault();e.stopImmediatePropagation();card.classList.remove('ax-chart-fullscreen-fallback');syncFullscreen();}},true);
 const updateFilterHeight=()=>target.querySelector('.ax-dashboard')?.style.setProperty('--analytics-filter-height',$('sa-filters').getBoundingClientRect().height+'px');
 if(typeof ResizeObserver==='function')new ResizeObserver(updateFilterHeight).observe($('sa-filters'));else window.addEventListener('resize',updateFilterHeight);
 let chartWidth=0;if(typeof ResizeObserver==='function')new ResizeObserver(entries=>{const width=entries[0]?.contentRect.width||0;if(Math.abs(width-chartWidth)>1){chartWidth=width;if(state.data)renderCharts();}}).observe($('sa-chart-grid'));updateFilterHeight();state.mounted=true;selectTab(state.tab);
}
function createChart([id,title,description,tabs,type]){
 const card=el('section','ax-chart surface');card.id='sa-chart-'+id;card.dataset.tabs=tabs;card.dataset.chart=id;card.setAttribute('aria-labelledby','sa-title-'+id);
 card.innerHTML='<header class="ax-chart-head"><div><h3 id="sa-title-'+id+'">'+esc(title)+'</h3><p>'+esc(description)+'</p></div><div class="ax-chart-actions"><button type="button" class="ax-export" data-chart-csv="'+id+'" title="Export chart data as CSV" aria-label="Export '+esc(title)+' as CSV">CSV</button><button type="button" class="ax-export" data-chart-png="'+id+'" title="Export graph as PNG" aria-label="Export '+esc(title)+' as PNG">PNG</button><button type="button" class="icon-button ax-expand" data-chart-fullscreen="'+id+'" title="Expand graph" aria-label="Expand '+esc(title)+'" aria-pressed="false">'+icon(false)+'</button></div></header><form class="ax-chart-context" aria-label="Fullscreen graph filters"><label>Session<select class="ax-context-session">'+options()+'</select></label><label>From<input type="date" class="ax-context-start"></label><label>Through<input type="date" class="ax-context-end"></label><button class="button primary" type="submit">Apply filters</button></form><div class="ax-local-controls"></div><div class="ax-chart-body" id="sa-'+id+'"></div><p class="ax-chart-note"></p>';
 $('sa-chart-grid').append(card);state.charts.set(id,{id,title,type,card,body:$('sa-'+id),rows:[],description});
 card.querySelector('[data-chart-fullscreen]').addEventListener('click',()=>void toggleFullscreen(id));card.querySelector('[data-chart-csv]').addEventListener('click',()=>exportCsv(id));card.querySelector('[data-chart-png]').addEventListener('click',()=>void exportPng(id));
 card.querySelector('.ax-chart-context').addEventListener('submit',e=>{e.preventDefault();$('sa-session').value=card.querySelector('.ax-context-session').value;$('sa-start').value=card.querySelector('.ax-context-start').value;$('sa-end').value=card.querySelector('.ax-context-end').value;void applyScope();});
 const controls=card.querySelector('.ax-local-controls');
 if(id==='activity'){controls.innerHTML='<label>Group by <select id="sa-interval"><option value="hour">Hourly</option><option value="day" selected>Daily</option><option value="week">Weekly</option><option value="month">Monthly</option></select></label>';$('sa-interval').addEventListener('change',()=>{state.interval=$('sa-interval').value;void load();});}
 if(id==='performance'){controls.innerHTML='<label>Measure <select id="sa-performance-mode"><option value="stage_ms">Processing stages (ms)</option><option value="ai_fps">AI processing FPS</option><option value="camera_fps">Camera preview FPS</option><option value="throughput">Fish per minute</option></select></label><span id="sa-performance-average"></span>';$('sa-performance-mode').addEventListener('change',()=>{state.performance=$('sa-performance-mode').value;renderCharts();});}
 if(id==='support'){controls.innerHTML='<label>Distribution <select id="sa-support-mode"><option value="detection_confidence">Model 1 detection confidence</option><option value="final_support">Final grading support</option><option value="averages">Average model support</option></select></label>';$('sa-support-mode').addEventListener('change',()=>{state.support=$('sa-support-mode').value;renderCharts();});}
 if(id==='color-trend'){controls.innerHTML='<label>Measure <select id="sa-color-mode"><option value="mean_hue_deg">Whole-fish hue (degrees)</option><option value="yellow_ratio_proxy">Yellow colour proxy (%)</option></select></label>';$('sa-color-mode').addEventListener('change',()=>{state.color=$('sa-color-mode').value;renderCharts();});}
 if(id==='decision-timing'){controls.innerHTML='<label>Measure <select id="sa-decision-mode"><option value="latency">First detection to decision (ms)</option><option value="deadlines">Decision deadline outcomes (fish)</option></select></label>';$('sa-decision-mode').addEventListener('change',()=>{state.decision=$('sa-decision-mode').value;renderCharts();});}
 if(id==='comparison')controls.innerHTML='<details class="ax-comparison-picker"><summary>Choose sessions</summary><div id="sa-comparison-sessions"></div></details>';
}
function selectTab(tab){state.tab=tab;for(const e of document.querySelectorAll('[data-analytics-tab]')){const active=e.dataset.analyticsTab===tab;e.setAttribute('aria-selected',String(active));e.tabIndex=active?0:-1;}for(const c of state.charts.values())c.card.classList.toggle('hidden',!c.card.dataset.tabs.split(' ').includes(tab));$('sa-kpis')?.classList.toggle('ax-kpis-compact',tab!=='overview');if(state.data)renderCharts();}
async function loadSessions(){
 const response=await fetch('/api/sessions?limit=1000',{cache:'no-store'}),data=await response.json();if(!response.ok)throw new Error(data.detail||'Saved sessions could not be loaded.');
 state.sessions=Array.isArray(data.items)?data.items:[];state.onSessions?.(state.sessions);const selected=$('sa-session').value;$('sa-session').innerHTML=options();$('sa-session').value=selected;
 for(const c of state.charts.values()){const s=c.card.querySelector('.ax-context-session');s.innerHTML=options();s.value=selected;}
}
async function applyScope(){
 const start=$('sa-start').value,end=$('sa-end').value;if(start&&end&&start>end){status('Choose an end date on or after the start date.',true);return;}
 state.mode=$('sa-session').value;state.scope={session_id:['','latest','custom'].includes(state.mode)?'':state.mode,start_date:start,end_date:end};await load();
}
function query(){const q=new URLSearchParams({range_name:state.mode==='latest'?'latest':state.scope.start_date||state.scope.end_date?'custom':'all',granularity:state.interval});for(const[k,v]of Object.entries(state.scope))if(v)q.set(k,v);return q;}
async function load(){
 const version=++state.request;state.controller?.abort();const controller=new AbortController();state.controller=controller;status('Loading saved inspection analytics…');$('sa-kpis')?.setAttribute('aria-busy','true');const timer=setTimeout(()=>controller.abort(),20000);
 try{const response=await fetch('/api/analytics?'+query(),{signal:controller.signal,cache:'no-store'}),data=await response.json();if(version!==state.request)return;if(!response.ok)throw new Error(data.detail||'Saved analytics could not be loaded.');state.data=data;state.loaded=true;state.resolvedScope={...state.scope,session_id:state.mode==='latest'?(data.analytics_v2?.scope?.session_id||state.sessions[0]?.session_id||''):state.scope.session_id};render(data);syncContexts();}
 catch(error){if(version===state.request)status(error.name==='AbortError'?'The saved-data request timed out. Refresh to retry.':error.message,true);}
 finally{clearTimeout(timer);if(version===state.request)$('sa-kpis')?.setAttribute('aria-busy','false');}
}
function syncContexts(){for(const c of state.charts.values()){c.card.querySelector('.ax-context-session').value=state.mode;c.card.querySelector('.ax-context-start').value=state.scope.start_date;c.card.querySelector('.ax-context-end').value=state.scope.end_date;}$('sa-filters')?.classList.toggle('has-custom-dates',state.mode==='custom'||!!(state.scope.start_date||state.scope.end_date));}
async function refresh(){try{await loadSessions();await applyScope();}catch(error){status(error.message,true);}}
async function onView(name){document.documentElement.classList.toggle('analytics-view-open',name==='analytics');document.body.classList.toggle('analytics-view-open',name==='analytics');if(name==='analytics'&&!state.loaded)await refresh();}
function render(data){
 state.data=data;const v2=data.analytics_v2||{},k=v2.kpis||{},grades=k.grade_distribution||data.grade_distribution||{},total=number(k.total_inspected??data.total_inspected)??GRADES.reduce((s,g)=>s+n(grades[g]),0),ungraded=number(k.ungraded_count??data.ungraded_count)??n(grades.Ungraded),graded=number(k.graded_count??data.graded_count)??Math.max(0,total-ungraded);
 const cards=[['Total inspected fish',total,'Unique saved fish',''],['Inspection sessions',k.session_count??data.session_activity_total,'Saved sessions in scope',''],['Graded fish',graded,total?fmt(graded/total*100)+'%':'No fish recorded',''],['Ungraded fish',ungraded,total?fmt(ungraded/total*100)+'%':'No fish recorded','Ungraded'],...GRADES.slice(0,4).map(g=>[g,n(grades[g]),'Original final grade',g])];
 $('sa-kpis').replaceChildren(...cards.map(([label,value,detail,grade])=>{const c=el('article','ax-kpi surface');if(grade)c.style.setProperty('--ax-grade',COLORS[grade]);c.append(el('span','',label),el('strong','',fmt(value)),el('small','',detail));return c;}));
 renderComparisonPicker();renderCharts();status(total?fmt(total)+' unique saved fish · '+(number(k.session_count)===null?'saved sessions':fmt(k.session_count)+' sessions')+' · select a chart category to inspect its records.':'No saved fish match this scope. Missing measurements remain “Not recorded”.');
}

function renderComparisonPicker(){
 const target=$('sa-comparison-sessions');if(!target)return;const sessions=state.data?.analytics_v2?.session_comparison||state.data?.session_activity||[];target.replaceChildren();
 for(const s of sessions){const label=el('label'),input=el('input');input.type='checkbox';input.value=s.session_id;input.checked=state.comparisons===null||state.comparisons.has(s.session_id);input.addEventListener('change',()=>{if(state.comparisons===null)state.comparisons=new Set(sessions.map(item=>item.session_id));if(input.checked)state.comparisons.add(input.value);else state.comparisons.delete(input.value);renderCharts();});label.append(input,document.createTextNode(sessionLabel(s)));target.append(label);}
 if(!sessions.length)target.append(el('p','','No saved sessions in this scope.'));
}
function renderCharts(){
 if(!state.data)return;const data=state.data,v2=data.analytics_v2||{},k=v2.kpis||{},dist=k.grade_distribution||data.grade_distribution||{},total=n(k.total_inspected??data.total_inspected);
 draw('grades',GRADES.map(g=>({label:g,value:n(dist[g]),color:COLORS[g],filter:{grade:g}})),'doughnut',{total});
 draw('activity',(v2.activity?.items||[]).map(item=>({label:item.bucket,value:number(item.fish_count),filter:state.interval==='hour'?null:bucketScope(item.bucket,state.interval),session_ids:item.session_ids||[]})),'line',{empty:'No timestamped fish records are available for this scope.'});
 draw('coverage',[{label:'Class A / B / C',value:GRADES.slice(0,3).reduce((s,g)=>s+n(dist[g]),0),color:COLORS['Class A'],filter:{grade:'accepted'}},{label:'Rejected',value:n(dist.Rejected),color:COLORS.Rejected,filter:{grade:'Rejected'}},{label:'Ungraded',value:n(dist.Ungraded),color:COLORS.Ungraded,filter:{grade:'Ungraded'}}],'bars');
 const anatomy=v2.anatomical_association||{},anatomyRows=[];
 for(const region of ['Head','Body','Tail']){const item=anatomy[region]||{};anatomyRows.push({label:region+' · fish with raw detection',value:number(item.raw_count),series:'Raw',color:'#95a9b5'},{label:region+' · fish with assigned evidence',value:number(item.assigned_count),series:'Assigned',color:'#137c92'});}
 for(const region of ['Head','Body','Tail'])anatomyRows.push({label:region+' · present recorded evidence',value:number(anatomy[region]?.present_fish_count??data.anatomical_evidence?.[region]?.count),series:'Present',color:'#175cba',filter:{evidence_region:region}});
 draw('anatomy',anatomyRows,'bars',{empty:'Raw detections and part assignment were not recorded in this selection.'});
 const reasons=v2.ungraded_reasons||data.ungraded_reasons||{};
 draw('reasons',Object.entries(reasons).sort((a,b)=>n(b[1])-n(a[1])).map(([code,value])=>({label:code.replaceAll('_',' '),value:n(value),code,color:COLORS.Ungraded,filter:{grade:'Ungraded',reason_code:code}})),'bars',{empty:'No Ungraded reason codes were recorded.'});
 const perf=v2.performance||{};
 if(state.performance==='ai_fps'||state.performance==='camera_fps')draw('performance',(perf[state.performance]||[]).map(item=>({label:item.timestamp,value:number(item.value),session_id:item.session_id,color:state.performance==='ai_fps'?'#137c92':'#7e8791',filter:{session_id:item.session_id}})),'line',{unit:'FPS',empty:(state.performance==='ai_fps'?'AI processing':'Camera preview')+' FPS samples were not saved.'});
 else if(state.performance==='throughput')draw('performance',(v2.session_comparison||[]).map(item=>({label:String(item.session_id).slice(-14),value:number(item.fish_per_minute),session_id:item.session_id,filter:{session_id:item.session_id}})),'bars',{unit:'fish/min',empty:'Saved active inspection durations are required to calculate fish per minute.'});
 else{const stages=perf.stage_ms||data.performance||{};draw('performance',[['Model 1','model1_inference_ms'],['Model 2','model2_inference_ms'],['Grading','grading_engine_ms'],['Tracking','tracking_ms'],['Colour analysis','hsv_processing_ms'],['Total processing','total_processing_ms']].map(([label,key])=>({label,value:number(stages[key])})),'bars',{unit:'ms',empty:'Processing stage durations were not recorded.'});}
 $('sa-performance-average').textContent='Average image: '+(number(perf.average_image_processing_time_ms)===null?'Not recorded':fmt(perf.average_image_processing_time_ms)+' ms')+' · Per fish: '+(number(perf.average_fish_processing_time_ms??data.average_processing_time_ms)===null?'Not recorded':fmt(perf.average_fish_processing_time_ms??data.average_processing_time_ms)+' ms');
 const sessions=(v2.session_comparison||data.session_activity||[]).filter(s=>state.comparisons===null||state.comparisons.has(s.session_id));
 draw('comparison',sessions.map(s=>({label:sessionLabel(s),value:number(s.fish_count??s.event_count),grades:s.grade_distribution||{},session_id:s.session_id,partial_scope:s.partial_scope,filter:{session_id:s.session_id}})),'stacked',{empty:'No saved sessions are selected for comparison.'});
 if(state.support==='averages')draw('support',[['Model 1 detection',data.average_detection_confidence],['Final grading support',data.average_final_support??data.average_grade_confidence],['Best Model 2 evidence',data.average_best_evidence_support],['Anatomical coverage',data.average_evidence_coverage]].map(([label,value])=>({label,value:number(value)})),'bars',{unit:'%',empty:'Model support averages were not recorded.'});
 else draw('support',number(perf.distribution_samples?.[state.support])===0?[]:(perf.distributions?.[state.support]||[]).map(item=>({label:item.label,value:n(item.count),min:item.min,max:item.max,color:state.support==='final_support'?'#175cba':'#137c92'})),'bars',{empty:'This confidence/support distribution was not recorded in the selected fish.'});
 const qualities=data.average_part_quality_scores||{};
 const qualityRows=[];for(const region of ['Head','Body','Tail']){const value=qualities[region];if(value&&typeof value==='object')for(const[grade,score]of Object.entries(value))qualityRows.push({label:region+' · '+grade,value:number(score),color:COLORS[grade]||'#137c92',filter:{evidence_region:region}});else qualityRows.push({label:region,value:number(value),filter:{evidence_region:region}});}
 draw('part-quality',qualityRows,'bars',{unit:'%',empty:'Part quality scores were not recorded.'});
 const trend=Array.isArray(data.color_trend)?data.color_trend:[];
 draw('color-trend',trend.map(item=>({label:item.timestamp||'',value:number(item[state.color]),color:state.color==='mean_hue_deg'?'#b54d0a':'#137c92'})),'line',{unit:state.color==='mean_hue_deg'?'degrees':'%',empty:'Colour trend measurements were not recorded.'});
 const deadlines=data.decision_deadline_status_counts||{};
 draw('decision-timing',state.decision==='latency'?[{label:'First detection to decision',value:number(data.average_first_detection_to_decision_ms)}]:Object.entries(deadlines).map(([code,value])=>({label:code.replaceAll('_',' '),value:number(value)})),'bars',{unit:state.decision==='latency'?'ms':'fish',empty:'Conveyor decision timing was not recorded.'});
 const timing=state.charts.get('decision-timing');if(timing)timing.card.querySelector('.ax-chart-note').textContent=(data.decision_timing_scope||'Recorded scope')+' · latency in ms; deadline outcomes in fish';
}
function bucketScope(bucket,interval){
 if(interval==='hour')return {};
 const date=new Date(bucket);if(Number.isNaN(date.getTime()))return{};const end=new Date(date);
 if(interval==='month')end.setUTCMonth(end.getUTCMonth()+1);else end.setUTCDate(end.getUTCDate()+(interval==='week'?7:1));end.setUTCDate(end.getUTCDate()-1);
 return{start_date:date.toISOString().slice(0,10),end_date:end.toISOString().slice(0,10)};
}
function baseSvg(title,width,fullHeight){const root=sv('svg',{viewBox:'0 0 760 300',class:'ax-chart-svg',role:'group','aria-label':title,preserveAspectRatio:'xMidYMid meet'});const logicalWidth=Math.max(300,Math.min(1000,width||760));root.dataset.logicalWidth=String(logicalWidth);if(fullHeight)root.dataset.fullHeight=String(Math.max(200,fullHeight*logicalWidth/Math.max(1,width)));root.append(sv('title',{},title));return root;}
function draw(id,rows,type,config){
 const chart=state.charts.get(id);if(!chart)return;const opts=config||{};chart.rows=rows;chart.type=type;chart.options=opts;chart.body.replaceChildren();
 const available=rows.filter(item=>number(item.value)!==null);chart.card.querySelector('.ax-chart-note').textContent=opts.unit?'Recorded values · '+opts.unit:'';
 if(!available.length||(type==='doughnut'&&!available.some(item=>n(item.value)>0))){chart.body.append(el('p','ax-empty',opts.empty||'No fish records in this scope.'));return;}
 const width=chart.body.clientWidth||chart.lastWidth||760;chart.lastWidth=width;const graphic=baseSvg(chart.title,width,chart.card.classList.contains('is-fullscreen')?chart.body.clientHeight-(type==='stacked'?40:0):0);chart.svg=graphic;if(type==='doughnut')doughnut(graphic,available,opts);else if(type==='line')line(graphic,available,opts);else bars(graphic,rows,type,opts);chart.body.append(graphic);
 const legend=el('div','ax-chart-legend');
 if(type==='stacked')for(const grade of GRADES){const b=button(grade,()=>void records({grade}),'ax-legend-button');b.style.setProperty('--ax-grade',COLORS[grade]);legend.append(b);}
 if(legend.children.length)chart.body.append(legend);
}
function bindPoint(element,item,label){
 element.append(sv('title',{},label));element.setAttribute('tabindex','0');element.setAttribute('role',item.filter?'button':'img');element.setAttribute('aria-label',label);
 if(item.filter){element.classList.add('ax-chart-selectable');element.addEventListener('click',event=>{event.stopPropagation();void records(item.filter);});element.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();void records(item.filter);}});}
}
function sizeGraphic(root,normalHeight){const width=Number(root.dataset.logicalWidth)||760,height=Number(root.dataset.fullHeight)||normalHeight;root.dataset.logicalHeight=String(height);root.setAttribute('viewBox','0 0 '+width+' '+height);root.style.height=height+'px';return width;}
function doughnut(root,rows,opts){
 const width=sizeGraphic(root,200),height=Number(root.dataset.logicalHeight),cx=width*.27,cy=height*.49,r=root.dataset.fullHeight?Math.min(width*.22,height*.35):Math.min(68,width*.17),stroke=Math.max(24,r*.43),total=rows.reduce((sum,item)=>sum+n(item.value),0);let angle=-Math.PI/2;
 for(const item of rows)if(n(item.value)>0){const arc=n(item.value)/Math.max(1,total)*Math.PI*2,end=angle+arc,x=cx+r*Math.cos(angle),y=cy+r*Math.sin(angle),x2=cx+r*Math.cos(end),y2=cy+r*Math.sin(end),path=arc>=Math.PI*2-.001?sv('circle',{cx,cy,r,fill:'none',stroke:item.color,'stroke-width':stroke}):sv('path',{d:'M '+x+' '+y+' A '+r+' '+r+' 0 '+(arc>Math.PI?1:0)+' 1 '+x2+' '+y2,fill:'none',stroke:item.color,'stroke-width':stroke});bindPoint(path,item,item.label+': '+fmt(item.value)+' fish, '+fmt(n(item.value)/total*100)+'%');root.append(path);angle=end;}
 root.append(sv('text',{x:cx,y:cy+3,'text-anchor':'middle',class:'ax-svg-total'},fmt(total)),sv('text',{x:cx,y:cy+23,'text-anchor':'middle',class:'ax-svg-muted'},'unique fish'));
 const legendStep=root.dataset.fullHeight?Math.min(65,(height-40)/5):33;let y=(height-legendStep*4)/2;for(const item of rows){const g=sv('g',{class:'ax-interactive-legend'}),left=width*.54;g.append(sv('rect',{x:left-4,y:y-20,width:width-left+1,height:30,rx:4,fill:'transparent','pointer-events':'all'}),sv('rect',{x:left,y:y-10,width:9,height:9,rx:2,fill:item.color}),sv('text',{x:left+15,y,class:'ax-svg-label'},item.label),sv('text',{x:width-7,y,'text-anchor':'end',class:'ax-svg-label'},fmt(item.value)+' / '+fmt(total?n(item.value)/total*100:0)+'%'));bindPoint(g,item,item.label+': '+fmt(item.value)+' fish, '+fmt(total?n(item.value)/total*100:0)+'%');root.append(g);y+=legendStep;}
}
function bars(root,rows,type,opts){
 const width=sizeGraphic(root,Math.max(170,rows.length*30+18)),height=Number(root.dataset.logicalHeight),step=root.dataset.fullHeight?(height-18)/Math.max(1,rows.length):30,barHeight=Math.min(28,step*.63),max=Math.max(1,...rows.map(item=>n(item.value))),labelWidth=Math.min(width*.43,Math.max(110,Math.max(...rows.map(item=>['Raw','Assigned','Present'].includes(item.series)?15:Math.min(36,item.label.length)))*6.3+10)),barLeft=labelWidth+5,barRight=width-96,barWidth=Math.max(30,barRight-barLeft),limit=Math.max(12,Math.floor(labelWidth/6.3));
 for(let i=0;i<rows.length;i++){const item=rows[i],y=root.dataset.fullHeight?9+i*step+(step-barHeight)/2:9+i*step,g=sv('g',{}),value=number(item.value);let name=item.label;
 if(['Raw','Assigned','Present'].includes(item.series))name=item.label.split(' \u00b7 ')[0]+' / '+item.series.toLowerCase();
 const label=name.length>limit?name.slice(0,limit-1)+'\u2026':name;
 g.append(sv('text',{x:2,y:y+14,class:'ax-svg-label'},label),sv('rect',{x:barLeft,y,width:barWidth,height:barHeight,rx:4,fill:'#edf2f5'}));
 if(type==='stacked'){let x=barLeft;for(const grade of GRADES){const segment=n(item.grades?.[grade])/max*barWidth;if(segment>0){const rect=sv('rect',{x,y,width:segment,height:barHeight,fill:COLORS[grade]});bindPoint(rect,{filter:{session_id:item.session_id,grade}},item.label+' / '+grade+': '+fmt(item.grades[grade]));g.append(rect);x+=segment;}}}
 else if(value!==null)g.append(sv('rect',{x:barLeft,y,width:Math.max(value>0?2:0,n(value)/max*barWidth),height:barHeight,rx:4,fill:item.color||'#137c92'}));
 const unit=item.unit||opts.unit;g.append(sv('text',{x:width-3,y:y+14,'text-anchor':'end',class:'ax-svg-label'},value===null?'Not recorded':fmt(value)+(unit?' '+unit:'')));bindPoint(g,item,item.label+': '+(value===null?'Not recorded':fmt(value)+(unit?' '+unit:'')));root.append(g);}
}
function timePositions(labels,left,right){
 const times=labels.map(value=>Date.parse(value)),valid=times.every(Number.isFinite),minimum=Math.min(...times),maximum=Math.max(...times);
 return labels.map((_value,index)=>valid&&maximum>minimum?left+(times[index]-minimum)/(maximum-minimum)*(right-left):labels.length===1?(left+right)/2:left+(right-left)*index/Math.max(1,labels.length-1));
}
function line(root,rows,opts){
 const width=sizeGraphic(root,220),height=Number(root.dataset.logicalHeight),max=Math.max(1,...rows.map(item=>n(item.value))),left=38,right=width-18,top=15,bottom=height-40;
 for(let tick=0;tick<=4;tick++){const y=bottom-(bottom-top)*tick/4;root.append(sv('line',{x1:left,y1:y,x2:right,y2:y,stroke:'#e1e9ee'}),sv('text',{x:left-7,y:y+4,'text-anchor':'end',class:'ax-svg-muted'},fmt(max*tick/4)));}
 const series=[...new Set(rows.map(item=>item.series||''))];
 for(const key of series){const items=rows.filter(item=>(item.series||'')===key),xs=timePositions(items.map(item=>item.label),left,right),points=items.map((item,i)=>({x:xs[i],y:bottom-n(item.value)/max*(bottom-top),item}));
 root.append(sv('polyline',{points:points.map(p=>p.x+','+p.y).join(' '),fill:'none',stroke:items[0]?.color||'#137c92','stroke-width':2.5}));
 const every=Math.max(1,Math.ceil(points.length/(width<450?3:5)));points.forEach((p,i)=>{const circle=sv('circle',{cx:p.x,cy:p.y,r:4,fill:p.item.color||'#137c92',stroke:'#fff','stroke-width':1.5});bindPoint(circle,p.item,(key?key+' / ':'')+p.item.label+': '+fmt(p.item.value)+(opts.unit?' '+opts.unit:' fish'));root.append(circle);if(key===series[0]&&(i%every===0||i===points.length-1))root.append(sv('text',{x:p.x,y:height-15,'text-anchor':i===0?'start':i===points.length-1?'end':'middle',class:'ax-svg-muted'},String(p.item.label).replace('T',' ').slice(0,state.interval==='hour'?16:10)));});}
}

function recordScope(filters,scope){
 const selected={...scope},applied={...(filters||{})};
 if(applied.start_date){selected.start_date=selected.start_date&&selected.start_date>applied.start_date?selected.start_date:applied.start_date;selected.end_date=selected.end_date&&selected.end_date<applied.end_date?selected.end_date:applied.end_date;delete applied.start_date;delete applied.end_date;}
 return {scope:selected,filters:applied};
}
async function records(filters){
 const card=document.fullscreenElement?.classList.contains('ax-chart')?document.fullscreenElement:document.querySelector('.ax-chart-fullscreen-fallback');if(card)await toggleFullscreen(card.dataset.chart);
 const result=recordScope(filters,state.resolvedScope||state.scope);state.onRecords?.(result.filters,result.scope);
}
async function toggleFullscreen(id){
 const card=state.charts.get(id)?.card;if(!card)return;if(document.fullscreenElement===card){await document.exitFullscreen();return;}if(card.classList.contains('ax-chart-fullscreen-fallback')){card.classList.remove('ax-chart-fullscreen-fallback');syncFullscreen();return;}
 syncContexts();try{if(card.requestFullscreen)await card.requestFullscreen();else throw new Error('Fullscreen unavailable');}catch(_){card.classList.add('ax-chart-fullscreen-fallback');}syncFullscreen();
}
function syncFullscreen(){for(const c of state.charts.values()){const full=document.fullscreenElement===c.card||c.card.classList.contains('ax-chart-fullscreen-fallback');c.card.classList.toggle('is-fullscreen',full);const control=c.card.querySelector('[data-chart-fullscreen]');control.innerHTML=icon(full);control.setAttribute('aria-pressed',String(full));control.setAttribute('aria-label',(full?'Minimize ':'Expand ')+c.title);control.title=full?'Exit graph fullscreen':'Expand graph';}document.body.classList.toggle('analytics-fullscreen-open',!!document.querySelector('.ax-chart-fullscreen-fallback'));if(state.data)renderCharts();}
function download(blob,filename){const url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function exportCsv(id){
 const c=state.charts.get(id);if(!c)return;const rows=c.rows.map(item=>({label:item.label,value:number(item.value),series:item.series||'',session_id:item.session_id||'',grade_distribution:item.grades?JSON.stringify(item.grades):'',scope_session:(state.resolvedScope||state.scope).session_id,start_date:state.scope.start_date,end_date:state.scope.end_date,unit:item.unit||c.options?.unit||'fish'})),keys=['label','value','series','session_id','grade_distribution','scope_session','start_date','end_date','unit'],cell=value=>'"'+String(value??'').replaceAll('"','""')+'"';
 download(new Blob([keys.join(',')+'\r\n'+rows.map(row=>keys.map(key=>cell(row[key])).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),'tamban_'+id+'.csv');
}
async function exportPng(id){
 const c=state.charts.get(id),graphic=c?.body.querySelector('svg');if(!graphic){status('This chart has no recorded data to export.',true);return;}
 try{
 const copy=graphic.cloneNode(true);copy.querySelectorAll('text').forEach(text=>{text.setAttribute('font-family','Arial, sans-serif');text.setAttribute('font-size',text.classList.contains('ax-svg-total')?'30':'12');text.setAttribute('fill','#173047');});
 const source=new XMLSerializer().serializeToString(copy),drawing='<svg xmlns="'+NS+'" width="1400" height="850"><rect width="1400" height="850" fill="white"/><text x="36" y="40" font-family="Arial" font-size="24" fill="#173047">'+esc(c.title)+'</text><text x="36" y="67" font-family="Arial" font-size="13" fill="#546c7a">'+esc(scopeLabel())+'</text><svg x="25" y="95" width="1350" height="710" viewBox="'+graphic.getAttribute('viewBox')+'">'+source.replace(/^<svg[^>]*>/,'').replace(/<\/svg>$/,'')+'</svg></svg>';
 const image=new Image(),url=URL.createObjectURL(new Blob([drawing],{type:'image/svg+xml'}));await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=url;});const canvas=document.createElement('canvas');canvas.width=1400;canvas.height=850;canvas.getContext('2d').drawImage(image,0,0);URL.revokeObjectURL(url);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('PNG could not be created.');download(blob,'tamban_'+id+'.png');
 }catch(error){status('Chart PNG could not be exported. '+(error.message||''),true);}
}
function scopeLabel(){const s=state.resolvedScope||state.scope;return(s.session_id?'Session '+s.session_id:'All saved sessions')+(s.start_date?' · from '+s.start_date:'')+(s.end_date?' through '+s.end_date:'');}
window.TambanAnalytics={mount,onView,refresh,selectTab,toggleFullscreen,exportCsv,exportPng,getScope:()=>({...state.resolvedScope||state.scope}),getSessions:()=>state.sessions,render,getState:()=>({tab:state.tab,mode:state.mode,scope:{...state.scope},interval:state.interval}),bucketScope,recordScope,timePositions};
})();

