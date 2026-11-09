/* Tunelbus Overview: live API first; honest timestamped archived snapshot if cross-origin is blocked. */
(() => {
'use strict';
const API_BASE = location.hostname==='tunelbus.cz' ? '' : 'https://tunelbus.cz';
const INTERVAL=30000;
const MAX_FRESH_SECONDS=150;
let map=null;
let routeLayer=null;
let markerLayer=null;
let routeReady=false;
const $=id=>document.getElementById(id);
const fmt=s=>s===null||s===undefined||!Number.isFinite(Number(s))?'—':(s<0?'−':'+')+Math.floor(Math.abs(Math.round(s))/60)+':'+String(Math.abs(Math.round(s))%60).padStart(2,'0');
const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function set(id,val){const e=$(id);if(e)e.textContent=val;}
function parseTime(s){if(!s)return null;const v=new Date(s);return Number.isFinite(v.getTime())?v:null}
function asTime(d){return d?d.toLocaleTimeString('cs-CZ',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'}
function initMap(){
 if(map||!window.L||!$('live-route-map'))return;
 map=L.map('live-route-map',{scrollWheelZoom:false,zoomControl:true}).setView([50.1195,14.438],12);
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; OpenStreetMap contributors',maxZoom:19}).addTo(map);
 routeLayer=L.layerGroup().addTo(map);
 markerLayer=L.layerGroup().addTo(map);
}
function paintMap(route,vehicles,isArchive){
 initMap();if(!map)return;
 if(route?.available&&Array.isArray(route.shapes)){
  routeLayer.clearLayers();
  const bounds=[];
  for(const shape of route.shapes){
   const points=(shape.points||[]).filter(p=>Array.isArray(p)&&Number.isFinite(p[0])&&Number.isFinite(p[1]));
   if(points.length<2)continue;
   L.polyline(points,{color:'#005682',weight:4,opacity:.82,smoothFactor:1.1}).addTo(routeLayer);
   bounds.push(...points);
  }
  if(bounds.length&&!routeReady){map.fitBounds(L.latLngBounds(bounds),{padding:[20,20]});routeReady=true;}
 }
 markerLayer.clearLayers();
 for(const v of vehicles){
  const lat=Number(v.latitude),lon=Number(v.longitude);
  if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<49||lat>51||lon<13||lon>16)continue;
  const age=Number(v.age_seconds??999999);
  const stale=isArchive||age>MAX_FRESH_SECONDS;
  const number=escapeHtml(v.vehicle_registration_number||'?');
  const marker=L.marker([lat,lon],{icon:L.divIcon({className:'',html:'<div class="bus-map-marker'+(stale?' stale':'')+'">'+number+'</div>',iconSize:[45,29],iconAnchor:[22,14]})});
  marker.bindPopup('<strong>Vůz '+number+'</strong><p>Směr '+escapeHtml(v.headsign||'—')+'</p><p>Zpoždění: '+fmt(v.delay_actual)+'</p><p>'+ (stale?'Archivní / starší poloha':'Poslední známá poloha')+'</p>');
  marker.addTo(markerLayer);
 }
 set('live-map-label',isArchive?'Historický snímek GPS':vehicles.length+' posledních známých poloh');
 setTimeout(()=>map?.invalidateSize(),50);
}
function paint(data,isArchive){
 const a=data.summary||{},v=data.vehicles?.vehicles||[],r=data.route||{};
 const generated=parseTime(a.generated_at||data.captured_at);
 const age=generated?Math.max(0,Math.round((Date.now()-generated.getTime())/1000)):Infinity;
 const stale=isArchive||age>MAX_FRESH_SECONDS||!a.data_available;
 set('live-source-state',stale?'ARCHIVNÍ SNÍMEK':'ŽIVÁ DATA');
 set('live-source-time',generated?'Měření: '+asTime(generated):'Čas neznámý');
 const availability=$('live-availability');
 if(availability){availability.classList.toggle('live-stale',stale);
 availability.textContent=isArchive?'Testovací GitHub Pages: přímé čtení produkčního API není dostupné. Zobrazen poslední uložený skutečný snímek z '+(generated?.toLocaleString('cs-CZ')||'archivu')+'. Nejde o aktuální provoz.':
 !a.data_available?'Data o aktuálním provozu nejsou dostupná. Poslední pozorování nebylo potvrzeno.':
 stale?'Poslední data jsou '+age+' sekund stará. Aktuální provoz nelze spolehlivě potvrdit.':
 'Poslední měření je '+age+' sekund staré. Vozidla jsou zobrazena podle posledních známých GPS poloh.';}
 set('live-active',v.length);
 set('live-delay',fmt(a.current_delay_median));
 set('live-ontime',a.on_time_percentage===null||a.on_time_percentage===undefined?'—':a.on_time_percentage+' %');
 const st={stable:'Stabilní',improving:'Zlepšuje se',worsening:'Zhoršuje se',unknown:'Neznámý'};
 set('live-trend',st[a.trend_status]||'—');
 const list=$('live-vehicle-list');if(list){
 list.innerHTML=v.length?v.map(x=>{
 const age=Number(x.age_seconds||0),fresh=!stale&&age<=MAX_FRESH_SECONDS;
 return '<div class="live-vehicle"><span class="live-vehicle-number">'+escapeHtml(x.vehicle_registration_number||'?')+'</span><div><b>→ '+escapeHtml(x.headsign||'—')+'</b><small>'+escapeHtml(x.last_stop_name||'Poloha neznámá')+' · '+(fresh?'před '+age+' s':'poslední známé měření')+'</small></div><span class="live-vehicle-delay">'+fmt(x.delay_actual)+'</span></div>';
 }).join(''):'<p>V posledním dostupném měření nejsou aktivní autobusy.</p>';
 }
 set('live-vehicle-count',v.length+' vozů');
 paintMap(r,v,stale);
}
async function fetchJSON(url){const response=await fetch(url,{mode:'cors',cache:'no-store',signal:AbortSignal.timeout(8500)});if(!response.ok)throw Error('HTTP '+response.status);return response.json();}
let archiveLoaded=false;
async function loadLive(){
 try{
   const [summary,vehicles,route]=await Promise.all([fetchJSON(API_BASE+'/api/live/summary'),fetchJSON(API_BASE+'/api/live/vehicles'),routeReady?Promise.resolve(null):fetchJSON(API_BASE+'/api/live/route')]);
   paint({summary,vehicles,route},false);
 }catch(err){
   if(!archiveLoaded){
     archiveLoaded=true;
     try{const sample=await fetchJSON('live-snapshot-preview.json');paint(sample,true);}
     catch(error){const e=$('live-availability');if(e){e.classList.add('live-stale');e.textContent='Živá data ani archivní snímek se nepodařilo načíst.';}set('live-source-state','DATA NEDOSTUPNÁ');}
   }
   console.info('Preview live API not available:',err.message);
 }
}
function eventCard(ev){
 const link=typeof ev.url==='string'&&ev.url.startsWith('https://pid.cz/')?ev.url:null;
 return '<div class="pid-item"><strong>'+escapeHtml(ev.title||'Informace PID')+'</strong><span>'+escapeHtml(ev.type==='disruption'?'Mimořádnost PID':'Výluka PID')+'</span>'+(ev.valid_from?'<span>Od '+escapeHtml(ev.valid_from)+'</span>':'')+(link?'<a href="'+escapeHtml(link)+'" rel="noopener" target="_blank">Detail PID ↗</a>':'')+'</div>';
}
async function loadEvents(){
 const root=$('pid-events');if(!root)return;
 try{
  const data=await fetchJSON(API_BASE+'/api/pid/events?line=145');
  if(!data||!Array.isArray(data.events))throw Error('Invalid feed response');
  if(data.status==='unavailable')throw Error('RSS temporarily unavailable');
  root.innerHTML=data.events.length?data.events.map(eventCard).join(''):
   '<div class="pid-empty"><strong>PID v aktuálních zprávách neuvádí omezení linky 145.</strong><p>Vlastní diagnostika jízdních dob se vyhodnocuje samostatně.</p></div>';
  set('live-events-updated','PID · aktualizováno '+asTime(parseTime(data.fetched_at)));
 }catch(e){
  root.innerHTML='<div class="pid-empty"><strong>Oficiální události PID</strong><p>V testovacím náhledu nejsou nyní živé RSS zprávy dostupné. Ověř aktuální informace přímo u PID.</p><a href="https://pid.cz/feed/rss-vyluky/" target="_blank" rel="noopener">Výluky PID ↗</a><a href="https://pid.cz/feed/rss-mimoradnosti/" target="_blank" rel="noopener">Mimořádnosti PID ↗</a></div>';
 }
}
window.addEventListener('load',()=>{loadLive();loadEvents();setInterval(loadLive,INTERVAL);setInterval(loadEvents,120000);});
})();
