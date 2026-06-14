"""Self-contained admin dashboard (single HTML page, vanilla JS).

Served at ``GET /dashboard``. The page asks for the admin key once (kept in the
browser's sessionStorage) and then polls the protected ``/api/admin/*`` JSON
endpoints to show: who is connected, what each mailbox is sharing (origin and
destination), and overall service status.

No clipboard *contents* are ever exposed — the server only stores ciphertext and
metadata, so the dashboard shows metadata only.

UI: light "Material Design 3 x Apple" theme (frosted header, soft elevated cards,
tonal status pills and payload chips). Read-only monitoring — the data contract,
endpoints, key handling and 3s polling are unchanged.
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CopyPasteRemote — Dashboard</title>
<style>
  *{box-sizing:border-box}
  html,body{margin:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,system-ui,sans-serif;-webkit-font-smoothing:antialiased;color:#1a1c28;min-height:100vh;
    background:radial-gradient(1000px 540px at 100% -8%, rgba(79,107,237,.10), transparent 56%), radial-gradient(760px 520px at -8% 112%, rgba(22,160,106,.07), transparent 55%), #eef1f8}

  header{display:flex;align-items:center;gap:14px;padding:13px 26px;position:sticky;top:0;z-index:20;
    background:rgba(255,255,255,.70);backdrop-filter:blur(22px) saturate(180%);-webkit-backdrop-filter:blur(22px) saturate(180%);border-bottom:1px solid rgba(20,23,40,.07)}
  header h1{font-size:18px;margin:0;font-weight:600;letter-spacing:-.02em}
  .ver{font-size:12px;color:#6b7088;background:rgba(118,124,150,.11);padding:3px 9px;border-radius:8px;font-weight:600}
  .spacer{flex:1}
  .pill{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;background:#eef0f5;color:#6b7088;font-size:13px;font-weight:600}
  .pill.ok{background:#e3f6ec;color:#0e6b45}
  .dot{width:8px;height:8px;border-radius:50%;background:#b0b5c7;display:inline-block}
  .dot.on{background:#16a06a;animation:pulse 2.4s infinite}
  .dot.off{background:#b0b5c7}
  .btn{display:inline-flex;align-items:center;gap:8px;border:none;border-radius:12px;padding:9px 17px;font-size:13.5px;font-weight:600;cursor:pointer;font-family:inherit;transition:filter .15s,background .15s,transform .1s}
  .btn-primary{background:#4f6bed;color:#fff;box-shadow:0 3px 10px rgba(79,107,237,.30)}
  .btn-primary:hover{filter:brightness(1.07)}
  .btn-primary:active{transform:scale(.96)}
  .btn-soft{background:rgba(118,124,150,.11);color:#3a3f52}
  .btn-soft:hover{background:rgba(118,124,150,.19)}
  .spin{display:inline-block;font-size:15px}
  .btn.is-loading .spin{animation:spin .8s linear infinite}

  main{padding:26px 24px 48px;max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:22px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px}
  .card{background:#fff;border-radius:20px;padding:18px 20px;border:1px solid rgba(20,23,40,.035);box-shadow:0 1px 2px rgba(20,23,40,.04),0 12px 30px rgba(20,23,40,.05)}
  .card .k{font-size:11.5px;font-weight:600;color:#7a8096;text-transform:uppercase;letter-spacing:.05em}
  .card .vrow{display:flex;align-items:baseline;gap:9px;margin-top:11px;flex-wrap:wrap}
  .card .v{font-weight:600;letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums;font-size:30px;color:#1a1c28}
  .card .v.sm{font-size:24px}
  .card .v.xs{font-size:18px;letter-spacing:-.01em}
  .card .v.accent{color:#4f6bed}
  .card .chip{font-size:12px;font-weight:600;color:#0e6b45;background:#e3f6ec;padding:2px 9px;border-radius:7px}
  .card .s{font-size:12.5px;color:#9095a7;margin-top:8px}

  section{background:#fff;border-radius:22px;border:1px solid rgba(20,23,40,.035);overflow:hidden;box-shadow:0 1px 2px rgba(20,23,40,.04),0 14px 34px rgba(20,23,40,.05)}
  .sec-head{display:flex;align-items:center;gap:10px;padding:16px 22px;border-bottom:1px solid rgba(20,23,40,.06)}
  .sec-head h2{font-size:15px;font-weight:600;margin:0;letter-spacing:-.01em}
  .sec-sub{font-size:12.5px;color:#9095a7}
  .meta-chip{font-size:11.5px;color:#9095a7;background:rgba(118,124,150,.10);padding:3px 10px;border-radius:7px}
  .sec-scroll{overflow-x:auto}

  table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:720px}
  thead th{text-align:left;padding:11px 22px;background:#f8f9fd;font-size:11px;font-weight:600;color:#8a8fa3;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
  tbody td{padding:13px 22px;border-top:1px solid rgba(20,23,40,.05);white-space:nowrap;vertical-align:middle}
  tbody tr{transition:background .12s}
  tbody tr:hover{background:rgba(79,107,237,.045)}
  td.num{color:#9095a7;font-variant-numeric:tabular-nums}
  td.name{font-weight:500;color:#23263a}
  td.sub{color:#5a5f72}
  td.wrap{white-space:normal;color:#9095a7;max-width:340px}
  .empty{padding:26px 22px;text-align:center;color:#9095a7;font-size:13.5px}

  .status{display:inline-flex;align-items:center;gap:7px;padding:4px 11px 4px 9px;border-radius:999px;font-size:12.5px;font-weight:600}
  .status.on{background:#e3f6ec;color:#0e6b45}
  .status.off{background:#eef0f5;color:#6b7088}
  .status .d{width:8px;height:8px;border-radius:50%}
  .status.on .d{background:#16a06a;animation:pulse 2.4s infinite}
  .status.off .d{background:#b0b5c7}

  .chip2{display:inline-block;padding:3px 10px;border-radius:8px;font-size:12px;font-weight:600}
  .chip2.green{background:#e3f6ec;color:#0e6b45}
  .chip2.grey{background:#eef0f5;color:#6b7088}
  .chip2.amber{background:#fff4dd;color:#9a6a12}
  .muted{color:#9aa0b5}

  .tag{display:inline-block;padding:3px 10px;border-radius:8px;font-size:12px;font-weight:600;background:#eef0f5;color:#6b7088}
  .tag.text{background:#e7eeff;color:#2e5bd6}
  .tag.files{background:#fff1d6;color:#9a6a12}
  .tag.image{background:#def3e2;color:#2c7a43}
  .tag.html{background:#f1e6ff;color:#7a45c7}

  .feed{max-height:360px;overflow:auto}
  .ev{display:flex;align-items:flex-start;gap:12px;padding:11px 22px;border-top:1px solid rgba(20,23,40,.045);transition:background .12s}
  .ev:first-child{border-top:none}
  .ev:hover{background:rgba(79,107,237,.04)}
  .ev-ic{flex-shrink:0;width:30px;height:30px;border-radius:9px;background:#f2f4fb;display:flex;align-items:center;justify-content:center;font-size:15px}
  .ev-bd{flex:1;min-width:0}
  .ev-msg{font-size:13.5px;color:#2a2e3d;line-height:1.45}
  .ev-ts{font-size:11.5px;color:#9aa0b5;font-variant-numeric:tabular-nums;margin-top:2px;font-family:ui-monospace,Menlo,Consolas,monospace}

  .err{max-width:1180px;margin:18px auto 0;padding:13px 18px;border:1px solid rgba(229,84,75,.35);border-radius:14px;color:#b3261e;background:#fdeceb;font-size:13.5px;font-weight:500}

  .sec-scroll::-webkit-scrollbar,.feed::-webkit-scrollbar{width:10px;height:10px}
  .sec-scroll::-webkit-scrollbar-thumb,.feed::-webkit-scrollbar-thumb{background:rgba(20,23,40,.14);border-radius:99px;border:3px solid transparent;background-clip:padding-box}

  @keyframes spin{to{transform:rotate(360deg)}}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(22,160,106,.42)}70%{box-shadow:0 0 0 7px rgba(22,160,106,0)}100%{box-shadow:0 0 0 0 rgba(22,160,106,0)}}
  @media (prefers-reduced-motion: reduce){*{animation:none!important}}
</style>
</head>
<body>
<header>
  <h1>CopyPasteRemote</h1><span class="ver" id="ver"></span>
  <span class="spacer"></span>
  <span class="pill" id="connPill"><span class="dot" id="connDot"></span><span id="connTxt">…</span></span>
  <button class="btn btn-primary" id="refreshBtn"><span class="spin" id="refreshSpin">↻</span>Actualizar</button>
  <button class="btn btn-soft" id="logoutBtn">Cambiar clave</button>
</header>
<div id="err" class="err" style="display:none"></div>
<main>
  <div class="cards" id="cards"></div>

  <section>
    <div class="sec-head"><h2>Máquinas del pool</h2><span class="sec-sub">estado del servicio cliente</span></div>
    <div class="sec-scroll">
      <table>
        <thead><tr><th>Slot</th><th>Nombre</th><th>Estado</th><th>Habilitada</th><th>Último visto</th><th>Buzón</th></tr></thead>
        <tbody id="machines"></tbody>
      </table>
    </div>
  </section>

  <section>
    <div class="sec-head"><h2>Contenido compartido</h2><span class="sec-sub">buzones · origen → destino</span><span class="spacer"></span><span class="meta-chip">solo metadatos · nunca el contenido</span></div>
    <div class="sec-scroll">
      <table>
        <thead><tr><th>Destino (buzón)</th><th>Origen</th><th>Tipo</th><th>Tamaño</th><th>Resumen</th><th>Actualizado</th></tr></thead>
        <tbody id="mailboxes"></tbody>
      </table>
    </div>
  </section>

  <section>
    <div class="sec-head"><h2>Actividad reciente</h2></div>
    <div class="feed" id="feed"></div>
  </section>
</main>

<script>
const KEY_NAME = "cpr_admin_key";
function getKey(force){
  let k = sessionStorage.getItem(KEY_NAME);
  if(!k || force){
    k = prompt("Introduce la clave de administración (admin_api_key):") || "";
    sessionStorage.setItem(KEY_NAME, k);
  }
  return k;
}
async function api(path){
  const r = await fetch(path, {headers:{"X-Admin-Key":getKey(false)}});
  if(r.status===401||r.status===403){ sessionStorage.removeItem(KEY_NAME); throw new Error("Clave de administración inválida"); }
  if(!r.ok){ throw new Error("HTTP "+r.status+" en "+path); }
  return r.json();
}

/* ---- rendering ---- */
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }
function human(n){ n=Number(n||0); const u=["B","KB","MB","GB","TB"]; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++;} return (i===0? n+" B" : n.toFixed(1)+" "+u[i]); }
function ago(ts){ if(!ts) return "—"; const s=Math.max(0,(Date.now()/1000-ts)); if(s<60)return Math.floor(s)+"s"; if(s<3600)return Math.floor(s/60)+"m"; if(s<86400)return Math.floor(s/3600)+"h"; return Math.floor(s/86400)+"d"; }
function hms(ts){ const d=new Date(ts*1000); return d.toLocaleTimeString(); }
function dur(s){ s=Math.floor(s||0); const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60); return (d?d+"d ":"")+(h?h+"h ":"")+m+"m"; }

function setConn(ok){ document.getElementById("connPill").className="pill"+(ok?" ok":""); document.getElementById("connDot").className="dot "+(ok?"on":"off"); document.getElementById("connTxt").textContent=ok?"servidor en línea":"sin conexión"; }

function renderCards(s){
  const c=document.getElementById("cards");
  const items=[
    ["Máquinas", s.machine_count, "registradas en el pool", "", ""],
    ["Conectadas", s.online_count, "clientes en línea ahora", "accent", s.online_count+" / "+s.machine_count],
    ["Buzones con contenido", s.clip_count, "esperando ser recogidos", "", ""],
    ["Uptime", dur(s.uptime_seconds), "desde el arranque", "sm", ""],
    ["Versión", s.version, "protocolo "+s.protocol, "sm", ""],
    ["Backend cripto", s.crypto_backend, "pool · "+s.pool_id, "xs", ""]
  ];
  c.innerHTML=items.map(it=>`<div class="card"><div class="k">${esc(it[0])}</div><div class="vrow"><span class="v ${it[3]}">${esc(it[1])}</span>${it[4]?`<span class="chip">${esc(it[4])}</span>`:""}</div><div class="s">${esc(it[2])}</div></div>`).join("");
}
function renderMachines(ms){
  const tb=document.getElementById("machines");
  if(!ms.length){ tb.innerHTML=`<tr><td colspan="6" class="empty">No hay máquinas registradas.</td></tr>`; return; }
  tb.innerHTML=ms.map(m=>`<tr>
    <td class="num">${m.slot}</td>
    <td class="name">${esc(m.name)}</td>
    <td><span class="status ${m.online?"on":"off"}"><span class="d"></span>${m.online?"en línea":"offline"}</span></td>
    <td>${m.enabled?'<span class="chip2 green">sí</span>':'<span class="chip2 grey">no</span>'}</td>
    <td class="num">${m.last_seen?ago(m.last_seen)+" atrás":"nunca"}</td>
    <td>${m.has_clip?'<span class="chip2 amber">con contenido</span>':'<span class="muted">vacío</span>'}</td>
  </tr>`).join("");
}
function renderMailboxes(mb){
  const tb=document.getElementById("mailboxes");
  if(!mb.length){ tb.innerHTML=`<tr><td colspan="6" class="empty">Ningún buzón tiene contenido ahora mismo.</td></tr>`; return; }
  tb.innerHTML=mb.map(x=>`<tr>
    <td class="name">#${x.slot} · ${esc(x.dest_name)}</td>
    <td class="sub">${x.from_id?("#"+x.from_id+" · "+esc(x.from_name||"")):'<span class="muted">—</span>'}</td>
    <td><span class="tag ${esc(x.kind)}">${esc(x.kind)}</span></td>
    <td class="sub">${human(x.size)}</td>
    <td class="wrap">${esc(x.summary||"")}</td>
    <td class="num">${ago(x.updated_at)} atrás</td>
  </tr>`).join("");
}
function iconFor(t){ return ({connect:"🔌",disconnect:"⏏️",push:"📤",pull:"📥",clear:"🗑️"})[t]||"•"; }
function describe(e){
  switch(e.type){
    case "connect": return `<b>${esc(e.name)}</b> (slot ${e.slot}) se conectó`;
    case "disconnect": return `<b>${esc(e.name)}</b> (slot ${e.slot}) se desconectó`;
    case "push": return `<b>${esc(e.from_name)}</b> (#${e.from_id}) → buzón #${e.slot} <b>${esc(e.dest_name||"")}</b>: ${esc(e.summary||e.kind)}`;
    case "pull": return `<b>${esc(e.by_name)}</b> (#${e.by}) recogió el buzón #${e.slot} <span class="muted">(${esc(e.kind)}, ${human(e.size)})</span>`;
    case "clear": return `buzón #${e.slot} vaciado por <b>${esc(e.by_name)}</b>`;
    default: return esc(e.type);
  }
}
function renderFeed(evs){
  const f=document.getElementById("feed");
  if(!evs.length){ f.innerHTML=`<div class="empty">Sin actividad todavía.</div>`; return; }
  f.innerHTML=evs.slice().reverse().map(e=>`<div class="ev"><span class="ev-ic">${iconFor(e.type)}</span><div class="ev-bd"><div class="ev-msg">${describe(e)}</div><div class="ev-ts">${hms(e.ts)}</div></div></div>`).join("");
}

async function refresh(){
  const btn=document.getElementById("refreshBtn"); btn.classList.add("is-loading");
  try{
    const ov=await api("/api/admin/overview");
    setConn(true);
    document.getElementById("err").style.display="none";
    document.getElementById("ver").textContent="v"+ov.server.version;
    renderCards(ov.server); renderMachines(ov.machines); renderMailboxes(ov.mailboxes);
    const act=await api("/api/admin/activity"); renderFeed(act.events);
  }catch(e){
    setConn(false);
    const el=document.getElementById("err"); el.style.display="block"; el.textContent=e.message;
  }finally{ setTimeout(()=>btn.classList.remove("is-loading"),400); }
}
document.getElementById("refreshBtn").onclick=refresh;
document.getElementById("logoutBtn").onclick=()=>{ getKey(true); refresh(); };
getKey(false);
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
