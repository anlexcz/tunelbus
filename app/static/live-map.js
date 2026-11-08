(() => {
  function create(options={}){
    const state={map:null,route:null,markers:new Map(),routeSignature:null,userMoved:false,programmaticMove:false};
    const mapElementId=options.mapElementId||"map";
    const onLoadError=options.onLoadError||(()=>{});
    const esc=v=>String(v??"Neznámé vozidlo").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
    const mix=(a,b,t)=>a.map((v,i)=>Math.round(v+(b[i]-v)*Math.max(0,Math.min(1,t))));
    const color=d=>{if(d==null||d<=149)return"#fff";let c;if(d<200)c=mix([255,255,255],[247,198,137],(d-150)/50);else if(d<400)c=mix([247,198,137],[218,137,65],(d-200)/200);else if(d<440)c=mix([218,137,65],[225,137,130],(d-400)/40);else c=[207,100,94];return`rgb(${c.join(",")})`};
    const fmtDelay=v=>v==null?"—":`${v>=0?"+":"−"}${Math.abs(Math.round(v))} s`;

    function init(){if(!window.L){onLoadError();return}state.map=L.map(mapElementId,{scrollWheelZoom:false});L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",{subdomains:"abcd",maxZoom:20,attribution:"© <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors © <a href=\"https://carto.com/attributions\">CARTO</a>"}).addTo(state.map);state.map.on("movestart zoomstart",()=>{if(!state.programmaticMove)state.userMoved=true})}
    function tip(v){const status=v.completed?"spoj ukončen":v.freshness==="stale"?"starší data":"";return`<strong>${esc(v.vehicle_registration_number)}</strong><span>→ ${esc(v.headsign||"Neznámý směr")}</span><br>${status?status+"<br>":""}${v.completed?"Poslední zpoždění ":""}${fmtDelay(v.delay_actual)}<br><small>Poslední informace před ${v.age_seconds} s</small>`}
    function distance(a,b){const r=Math.PI/180,x=(b.lat-a.lat)*r,y=(b.lng-a.lng)*r;return 6371000*Math.sqrt(x*x+y*y)*Math.cos((a.lat+b.lat)*r/2)}
    function move(marker,target){const start=marker.getLatLng(),meters=distance(start,target);if(meters>3000){marker.setLatLng(target);return}const previous=marker._tunelAnimation;if(previous)cancelAnimationFrame(previous);const began=performance.now(),duration=850;function frame(t){const p=Math.min(1,(t-began)/duration),e=1-Math.pow(1-p,2);marker.setLatLng([start.lat+(target.lat-start.lat)*e,start.lng+(target.lng-start.lng)*e]);if(p<1)marker._tunelAnimation=requestAnimationFrame(frame)}marker._tunelAnimation=requestAnimationFrame(frame)}
    function renderVehicles(vs){if(!state.map)return;const alive=new Set;vs.forEach(v=>{alive.add(v.trip_id);const icon=L.divIcon({html:`<div class="bus-marker ${v.freshness==='stale'?'stale':''}" style="background:${color(v.delay_actual)}">🚍</div>`,className:"",iconSize:[38,38],iconAnchor:[19,19]});let m=state.markers.get(v.trip_id);if(!m){m=L.marker([v.latitude,v.longitude],{icon,keyboard:true}).addTo(state.map);state.markers.set(v.trip_id,m)}else{move(m,L.latLng(v.latitude,v.longitude));m.setIcon(icon)}m.bindTooltip(tip(v),{className:"bus-tooltip",direction:"top",offset:[0,-16]})});state.markers.forEach((m,k)=>{if(!alive.has(k)){if(m._tunelAnimation)cancelAnimationFrame(m._tunelAnimation);state.map.removeLayer(m);state.markers.delete(k)}})}
    function fit(bounds){if(state.userMoved||!bounds.isValid())return;state.programmaticMove=true;state.map.once("moveend",()=>{state.programmaticMove=false});const pad=window.innerWidth<600?[16,16]:[10,10];state.map.fitBounds(bounds,{padding:pad,maxZoom:15})}
    function renderRoute(data){if(!state.map)return;const shapes=Array.isArray(data?.shapes)?data.shapes:[];const signature=JSON.stringify(shapes.map(x=>[x.shape_id,x.points]));if(signature===state.routeSignature)return;state.routeSignature=signature;if(state.route){state.map.removeLayer(state.route);state.route=null}const lines=shapes.map(x=>x.points);if(lines.length){state.route=L.polyline(lines,{color:"#496b7a",weight:5,opacity:.82,lineJoin:"round"}).addTo(state.map);fit(state.route.getBounds())}}

    return {init,renderRoute,renderVehicles};
  }

  window.TunelbusLiveMap={create};
})();
