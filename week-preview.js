(() => {
'use strict';
const WEEK_URL = 'week-preview.json';
const DAYS = ['2026-11-02','2026-11-03','2026-11-04','2026-11-05','2026-11-06','2026-11-07','2026-11-08'];
const WEEKDAY = ['Ne','Po','Út','St','Čt','Pá','So'];
let dataset = null;
let selectedDay = '2026-11-07';
let replayMinute=12*60;
let replayTimer=null;
let replayFilter='all';
const txt = (el, value) => { if(el) el.textContent = value; };
const fmt = sec => sec === null || sec === undefined || !Number.isFinite(+sec) ? '—' : (sec<0?'−':'+') + Math.floor(Math.abs(Math.round(sec))/60) + ':' + String(Math.abs(Math.round(sec))%60).padStart(2,'0');
const dayName = date => { const d = new Date(date+'T12:00:00'); return WEEKDAY[d.getDay()]+' '+Number(date.slice(8))+'. '+Number(date.slice(5,7))+'. '+date.slice(0,4); };
const median = values => {const a=[...values].sort((x,y)=>x-y);return a.length?a.length%2?a[(a.length-1)/2]:(a[a.length/2-1]+a[a.length/2])/2:null;};
const stat = (page, index, value) => txt(document.querySelectorAll('#'+page+' .kpi-val')[index],value);
const urlForDay = day => '#day/'+day;
const alertBox = (message, kind='warning') => '<p class="week-alert '+kind+'">'+message+'</p>';
const isPartial = d => !dataset.days[d]?.complete;
function getTrips(day){return dataset.days[day]?.trips?.trips||[]}
function updatePublic(){
  const bars=document.getElementById('overview-week-bars');
  if(!bars||!dataset)return;
  bars.innerHTML=DAYS.map(d=>{
    const curr=dataset.days[d],v=curr.analytics.within_3_minutes;
    const label=WEEKDAY[new Date(d+'T12:00:00').getDay()];
    const partial=!curr.complete;
    return '<a class="overview-week-item'+(partial?' is-partial':'')+'" href="'+urlForDay(d)+'" aria-label="'+dayName(d)+', '+v+' % včas'+(partial?', neúplný den':'')+'"><span class="overview-week-value">'+v+' %'+(partial?'*':'')+'</span><span class="overview-week-track"><span class="overview-week-column" style="height:'+Math.max(2,Math.min(100,v))+'%"></span></span><span class="overview-week-label">'+label+'</span></a>';
  }).join('');
}

function minuteOf(v){const m=String(v||'').match(/^(\d+):(\d{2})/);return m?Number(m[1])*60+Number(m[2]):null;}
function hhmm(t){return String(Math.floor(t/60)%24).padStart(2,'0')+':'+String(t%60).padStart(2,'0');}
function summarize(values){const v=values.filter(x=>x!==null&&x!==undefined&&Number.isFinite(x));return v.length?median(v):null;}
function replayData(){
  const list=getTrips(selectedDay).filter(t=>minuteOf(t.scheduled_start)!==null).sort((a,b)=>minuteOf(a.scheduled_start)-minuteOf(b.scheduled_start));
  const started=list.filter(t=>minuteOf(t.scheduled_start)<=replayMinute);
  const hour=list.filter(t=>minuteOf(t.scheduled_start)>replayMinute-60&&minuteOf(t.scheduled_start)<=replayMinute);
  return {list,started,hour};
}
function updateReplay(){
  if(!dataset)return;
  const p=dataset.days[selectedDay],a=p.analytics,{list,started,hour}=replayData();
  const time=document.getElementById('replay-time');if(time)time.value=replayMinute;
  txt(document.getElementById('replay-clock'),hhmm(replayMinute));
  txt(document.getElementById('replay-started'),started.length+' / '+a.planned_trips);
  txt(document.getElementById('replay-hour'),hour.length);
  txt(document.getElementById('replay-median'),fmt(summarize(hour.map(t=>t.average_delay))));
  txt(document.getElementById('replay-vehicles'),a.vehicles);
  const graph=document.getElementById('replay-hours');
  if(graph){
    const buckets=Array.from({length:20},(_,i)=>({hour:i+4,values:[]}));
    for(const trip of list){
      const h=Math.floor(minuteOf(trip.scheduled_start)/60);
      const b=buckets.find(v=>v.hour===h);
      if(b&&trip.average_delay!==null&&Number.isFinite(trip.average_delay))b.values.push(trip.average_delay);
    }
    const vals=buckets.map(b=>summarize(b.values));
    const max=Math.max(180,...vals.filter(Number.isFinite).map(v=>Math.abs(v)));
    graph.innerHTML=buckets.map((b,i)=>{
      const v=vals[i];
      const height=v===null?0:Math.max(2,Math.round(Math.abs(v)/max*94));
      return '<div class="replay-hour-bar'+(Math.floor(replayMinute/60)===b.hour?' selected':'')+'" data-label="'+String(b.hour).padStart(2,'0')+'" title="'+String(b.hour).padStart(2,'0')+':00 · '+(v===null?'bez dat':fmt(v))+' · '+b.values.length+' spojů"><span style="height:'+height+'%"></span></div>';
    }).join('');
  }
  const dirs=document.getElementById('replay-directions');
  if(dirs){
    dirs.innerHTML=['Dejvická','Sídliště Čimice'].map(name=>{
      const trips=list.filter(t=>t.trip_headsign===name),usable=trips.map(t=>t.average_delay).filter(Number.isFinite);
      const pct=usable.length?Math.round(100*usable.filter(v=>v>=-60&&v<180).length/usable.length):null;
      return '<div class="replay-direction"><div class="replay-direction-top"><span>→ '+name+'</span><strong>'+(pct===null?'—':pct+' %')+'</strong></div><div class="replay-direction-meta">'+trips.length+' plánovaných spojů · typicky '+fmt(summarize(usable))+'</div><div class="replay-direction-track"><span style="width:'+(pct??0)+'%"></span></div></div>';
    }).join('');
  }
  const trips=document.getElementById('replay-trips');
  if(trips){
    const nearby=list.filter(t=>Math.abs(minuteOf(t.scheduled_start)-replayMinute)<=45&& (replayFilter==='all'||t.trip_headsign===replayFilter))
      .sort((a,b)=>Math.abs(minuteOf(a.scheduled_start)-replayMinute)-Math.abs(minuteOf(b.scheduled_start)-replayMinute)).slice(0,7)
      .sort((a,b)=>minuteOf(a.scheduled_start)-minuteOf(b.scheduled_start));
    trips.innerHTML=nearby.map(t=>'<div class="replay-trip-row"><time>'+String(t.scheduled_start).slice(0,5)+'</time><div><strong>→ '+(t.trip_headsign||'—')+'</strong><small>Vůz '+(t.vehicle_registration_number||'neuveden')+' · podle JŘ</small></div><span class="'+(t.average_delay===null?'unknown':'')+'" title="Reprezentativní odchylka spoje, ne zpoždění odjezdu">'+fmt(t.average_delay)+'</span></div>').join('')||'<p class="replay-explain">V okolí tohoto času nejsou plánované odjezdy.</p>';
  }
  const dist=document.getElementById('replay-dist');
  if(dist){
    const values=list.map(t=>t.average_delay).filter(Number.isFinite);
    const buckets=[['Předjetí',v=>v< -60],['Včas',v=>v>=-60&&v<180],['3–6 min',v=>v>=180&&v<=360],['6–10 min',v=>v>360&&v<=600],['Nad 10 min',v=>v>600]];
    dist.innerHTML=buckets.map(([name,check])=>{
      const count=values.filter(check).length,percent=values.length?Math.round(count/values.length*100):0;
      return '<div class="replay-distribution-row"><label>'+name+'</label><div class="replay-dist-track"><span style="width:'+percent+'%"></span></div><strong>'+percent+' %</strong></div>';
    }).join('');
  }
  txt(document.getElementById('replay-quality'),p.complete?'Statistiky dne vycházejí z archivních reprezentativních hodnot. Přesný zastávkový odjezd nemusí být potvrzený.':'Nedělní výřez končí před uzavřením provozního dne, výsledky jsou pouze orientační.');
}
function initReplay(){
  const slider=document.getElementById('replay-time');
  if(slider)slider.addEventListener('input',()=>{replayMinute=+slider.value;updateReplay();});
  const toggle=document.getElementById('replay-toggle');
  if(toggle)toggle.addEventListener('click',()=>{
    if(replayTimer){clearInterval(replayTimer);replayTimer=null;toggle.textContent='▶ Přehrát';toggle.setAttribute('aria-pressed','false');return;}
    toggle.textContent='Ⅱ Pozastavit';toggle.setAttribute('aria-pressed','true');
    replayTimer=setInterval(()=>{replayMinute+=5;if(replayMinute>1439)replayMinute=270;updateReplay();},1500);
  });
  document.querySelectorAll('[data-replay-filter]').forEach(btn=>btn.addEventListener('click',()=>{
    replayFilter=btn.dataset.replayFilter;
    document.querySelectorAll('[data-replay-filter]').forEach(x=>x.classList.toggle('active',x===btn));
    updateReplay();
  }));
}

function renderHistory(){
  const validDays=DAYS.filter(day=>!isPartial(day));
  const totals=validDays.flatMap(day=>getTrips(day).map(t=>t.average_delay).filter(v=>v!==null&&Number.isFinite(v)));
  const mean=totals.length?Math.round(totals.reduce((a,b)=>a+b,0)/totals.length):null;
  const m=median(totals);const sorted=[...totals].sort((a,b)=>a-b);
  const p90=sorted.length?sorted[Math.max(0,Math.ceil(sorted.length*.90)-1)]:null;
  const timely=totals.length?Math.round(100*totals.filter(v=>v>=-60&&v<180).length/totals.length):null;
  ['Průměr','Medián','P90','Včasnost'].forEach((_,i)=>stat('history',i,i===3?(timely===null?'—':timely+' %'):fmt([mean,m,p90][i])));
  const historySection=document.querySelector('#history .stack');
  if(historySection)historySection.innerHTML='<article class="panel"><h2 class="panel-title">Typické zpoždění podle dne</h2><div id="history-chart"></div></article><article class="panel"><h2 class="panel-title">Včasnost podle dne</h2><div id="hour-chart"></div></article>';
  chart('history-chart',DAYS.map(d=>dataset.days[d].analytics.median_delay),DAYS.map(d=>WEEKDAY[new Date(d+'T12:00:00').getDay()]+(isPartial(d)?'*':'')),true);
  chart('hour-chart',DAYS.map(d=>dataset.days[d].analytics.within_3_minutes||0),DAYS.map(d=>WEEKDAY[new Date(d+'T12:00:00').getDay()]+(isPartial(d)?'*':'')),true);
  const filters=document.querySelector('#history .filters');if(filters)filters.style.display='none';
  const k=document.querySelector('#history .kpis');if(k)k.style.display='grid';
  document.getElementById('days').innerHTML=DAYS.map(day=>{
    const p=dataset.days[day],a=p.analytics;
    return '<a class="dayrow" href="'+urlForDay(day)+'"><span class="grow"><div class="primaryline">'+dayName(day)+(p.complete?'':' · NEÚPLNÉ')+'</div><div class="secondaryline">'+p.source_captured_trips+' / '+a.planned_trips+' zachycených · '+p.source_observations.toLocaleString('cs-CZ')+' měření</div></span><b class="delay">'+fmt(a.median_delay)+'</b><span class="muted">›</span></a>';
  }).join('');
  let note=document.getElementById('week-history-note');
  if(!note){note=document.createElement('div');note.id='week-history-note';document.querySelector('#history .pagehead').after(note);}
  note.innerHTML=alertBox('Týdenní výsek: 2.–8. 11. 2026. Neděle je neúplná, proto do souhrnných metrik týdne nevstupuje. Všechny hodnoty zpoždění jsou prozatímní, dokud neproběhne rekonstrukce skutečných odjezdů.');
}
function renderDay(day){
  selectedDay=dataset.days[day]?day:'2026-11-07';
  const p=dataset.days[selectedDay],a=p.analytics;
  document.querySelector('#day .pagehead h1').textContent=dayName(selectedDay);
  stat('day',0,fmt(a.average_delay));stat('day',1,fmt(a.median_delay));stat('day',2,fmt(a.percentile_90));
  stat('day',3,p.source_captured_trips+' / '+a.planned_trips);
  const stack=document.querySelector('#day .stack');stack.innerHTML='<article class="panel"><h2 class="panel-title">Rozložení zpoždění spojů</h2><div id="day-chart"></div></article><article class="panel"><h2 class="panel-title">Kvalita dat</h2><div id="day-quality" class="quality-lines"></div></article>';
  const raw=getTrips(selectedDay);
  const buckets=[{label:'Předjetí',n:0},{label:'Včas',n:0},{label:'3–6 min',n:0},{label:'6–10 min',n:0},{label:'Nad 10 min',n:0}];
  raw.forEach(t=>{const v=t.average_delay;if(v===null||!Number.isFinite(v))return;const idx=v< -60?0:v<180?1:v<=360?2:v<=600?3:4;buckets[idx].n++});
  const valid=raw.filter(t=>Number.isFinite(t.average_delay)).length;
  document.getElementById('day-chart').innerHTML='<div class="week-bars">'+buckets.map(b=>'<div class="week-bar-row"><span>'+b.label+'</span><div class="week-bar-track"><div class="week-bar-fill" style="width:'+(valid?Math.round(b.n/valid*100):0)+'%"></div></div><b>'+b.n+'</b></div>').join('')+'</div>';
  document.getElementById('day-quality').innerHTML='<div class="quality-row"><span>Raw pozorování</span><strong>'+p.source_observations.toLocaleString('cs-CZ')+'</strong></div><div class="quality-row"><span>Zachycené spoje</span><strong>'+p.source_captured_trips+' / '+a.planned_trips+'</strong></div><div class="quality-row"><span>Různé zastávkové klíče</span><strong>'+(p.raw_diagnostics?.unique_trip_stop_id_keys??'—').toLocaleString('cs-CZ')+'</strong></div><div class="quality-row"><span>Rozdíly údajů nad 10 min</span><strong>'+(p.raw_diagnostics?.large_current_last_stop_difference_keys??'—')+'</strong></div><div class="quality-row"><span>Stav výřezu</span><strong>'+(p.complete?'Uzavřený':'Neúplný')+'</strong></div>'+alertBox('Rozdíl aktuálního zpoždění a posledního odjezdu není sám o sobě chyba. Včasnost je zatím převzatá z původní metodiky API, nikoliv z nově potvrzených odjezdů.');
  let note=document.getElementById('week-day-note');
  if(!note){note=document.createElement('div');note.id='week-day-note';document.querySelector('#day .pagehead').after(note)}
  note.innerHTML=isPartial(selectedDay)?alertBox('Neděle 8. 11.: nahraný export končí před půlnocí. Zachyceno 141 ze 142 plánovaných spojů. Není to kompletní provozní den.'):'';
  const filter=document.getElementById('trip-filter');filter.value='';
  const list=document.getElementById('trips');
  txt(document.getElementById('trips-count'),raw.length+' spojů');
  const paint=()=>{
    const q=filter.value.trim().toLowerCase();
    const found=raw.filter(t=>[t.scheduled_start,t.trip_headsign,t.vehicle_registration_number,t.trip_id].some(x=>String(x||'').toLowerCase().includes(q)));
    list.innerHTML=found.map(t=>{
      const known=t.average_delay!==null&&Number.isFinite(t.average_delay);
      const suffix=selectedDay==='2026-11-07'&&t.trip_id==='145_1320_261003'?' href="#trip"':'';
      const tag=suffix? 'a':'div';
      return '<'+tag+suffix+' class="triprow"><b style="min-width:52px">'+String(t.scheduled_start||'—').slice(0,5)+'</b><span class="grow"><div class="primaryline">'+(t.trip_headsign||'—')+'</div><div class="secondaryline">Vůz '+(t.vehicle_registration_number||'neznámý')+'</div></span><b class="delay">'+(known?fmt(t.average_delay):'—')+'</b></'+tag+'>';
    }).join('')||'<p class="empty">Žádné odpovídající spoje</p>';
  };
  filter.oninput=paint;paint();
  const exportBtn=document.getElementById('export-btn');
  exportBtn.onclick=()=>{
    const lines=['datum;trip_id;odjezd;cil;vozidlo;reprezentativni_zpozdeni_s;metodika_prozatimni',...raw.map(t=>[selectedDay,t.trip_id,t.scheduled_start,t.trip_headsign,t.vehicle_registration_number,t.average_delay,'ano'].map(v=>String(v??'')).join(';'))];
    const blob=new Blob(['\uFEFF'+lines.join('\n')],{type:'text/csv;charset=utf-8'});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='tunelbus-'+selectedDay+'-test.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  };
  updatePublic();
}
function display(){
  if(!dataset)return;
  const hash=decodeURIComponent(location.hash.slice(1));
  const dayMatch=hash.match(/^day\/(2026-11-0[2-8])$/);
  const page=dayMatch?'day':(['live','history','day','trip','about'].includes(hash)?hash:'live');
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===page));
  document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===(page==='day'||page==='trip'?'history':page==='live'?'live':page)));
  if(page!=='history'&&replayTimer){clearInterval(replayTimer);replayTimer=null;const toggle=document.getElementById('replay-toggle');if(toggle){toggle.textContent='▶ Přehrát';toggle.setAttribute('aria-pressed','false');}}
  if(page==='day')renderDay(dayMatch?dayMatch[1]:selectedDay);
  if(page==='live')updatePublic();
  if(page==='history'){renderHistory();updateReplay();}
  if(page==='trip'){document.querySelector('#trip .pagehead .eyebrow a').href=urlForDay('2026-11-07');}
  window.scrollTo(0,0);
  document.title=(page==='day'?dayName(selectedDay):page==='history'?'Historie týdne':page==='live'?'Přehled provozu':page==='trip'?'Detail spoje':'O projektu')+' | Tunelbus – test';
}
fetch(WEEK_URL,{cache:'no-store'})
 .then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()})
 .then(week=>{
  if(!week?.days||DAYS.some(d=>!week.days[d]))throw Error('Chybějící den v archivu');
  dataset=week;
  initReplay();
  document.querySelectorAll('.prototype').forEach(el=>el.textContent='TEST · 2.–8. 11. 2026');
  document.querySelector('#history .pagehead h1').textContent='Historie týdne';
  window.removeEventListener('hashchange',navigate);
  window.addEventListener('hashchange',display);
  display();
 })
 .catch(e=>{console.error('Week dataset:',e);const el=document.querySelector('.prototype');if(el)el.textContent='CHYBA DAT';});
})();
