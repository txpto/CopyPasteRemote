"""Self-contained admin dashboard (single HTML page, vanilla JS).

Served at ``GET /dashboard``. The page asks for the admin key once (kept in the
browser's sessionStorage) and then polls the protected ``/api/admin/*`` JSON
endpoints to show: who is connected, what each mailbox is sharing (origin and
destination), and overall service status.

No clipboard *contents* are ever exposed — the server only stores ciphertext and
metadata, so the dashboard shows metadata only.
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CopyPasteRemote — Dashboard</title>
<style>
  :root{
    --bg:#0f1220; --panel:#181c2e; --panel2:#1f2440; --line:#2a3050;
    --txt:#e7e9f3; --muted:#9aa0bd; --accent:#5b8cff; --green:#37c971; --grey:#6b7194;
    --red:#ff6b6b; --yellow:#ffce55;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--txt)}
  header{display:flex;align-items:center;gap:14px;padding:14px 20px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
  header h1{font-size:18px;margin:0;font-weight:600}
  header .ver{color:var(--muted);font-size:13px}
  header .spacer{flex:1}
  .pill{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;background:var(--panel2);font-size:13px;border:1px solid var(--line)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--grey);display:inline-block}
  .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
  .dot.off{background:var(--grey)}
  button{background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:7px 12px;cursor:pointer;font-size:13px}
  button:hover{border-color:var(--accent)}
  main{padding:20px;max-width:1200px;margin:0 auto;display:grid;gap:18px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .card .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .card .v{font-size:22px;font-weight:600;margin-top:6px}
  .card .s{color:var(--muted);font-size:12px;margin-top:4px}
  section{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  section h2{font-size:14px;margin:0;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--panel2);font-weight:600}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:10px 16px;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
  tr:last-child td{border-bottom:none}
  td.wrap{white-space:normal;max-width:380px;color:var(--muted)}
  .tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;background:var(--panel2);border:1px solid var(--line)}
  .tag.text{color:#9ec1ff}.tag.files{color:#ffd479}.tag.image{color:#a0e7a0}.tag.html{color:#d7a0ff}
  .muted{color:var(--muted)}
  .feed{max-height:360px;overflow:auto}
  .ev{display:flex;gap:10px;padding:8px 16px;border-bottom:1px solid var(--line);font-size:13px}
  .ev:last-child{border-bottom:none}
  .ev .t{color:var(--muted);min-width:64px;font-variant-numeric:tabular-nums}
  .empty{padding:18px 16px;color:var(--muted);font-size:13px}
  .err{margin:20px;padding:12px 16px;border:1px solid var(--red);border-radius:10px;color:#ffd0d0;background:#2a1620}
</style>
</head>
<body>
<header>
  <h1>CopyPasteRemote</h1><span class="ver" id="ver"></span>
  <span class="spacer"></span>
  <span class="pill"><span class="dot" id="connDot"></span><span id="connTxt">…</span></span>
  <button id="refreshBtn">Actualizar</button>
  <button id="logoutBtn">Cambiar clave</button>
</header>
<div id="err" class="err" style="display:none"></div>
<main>
  <div class="cards" id="cards"></div>

  <section>
    <h2>Máquinas del pool (estado del servicio cliente)</h2>
    <table>
      <thead><tr><th>Slot</th><th>Nombre</th><th>Estado</th><th>Habilitada</th><th>Último visto</th><th>Buzón</th></tr></thead>
      <tbody id="machines"></tbody>
    </table>
  </section>

  <section>
    <h2>Contenido compartido (buzones · origen → destino)</h2>
    <table>
      <thead><tr><th>Destino (buzón)</th><th>Origen</th><th>Tipo</th><th>Tamaño</th><th>Resumen</th><th>Actualizado</th></tr></thead>
      <tbody id="mailboxes"></tbody>
    </table>
  </section>

  <section>
    <h2>Actividad reciente</h2>
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
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }
function human(n){ n=Number(n||0); const u=["B","KB","MB","GB","TB"]; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++;} return (i===0? n+" B" : n.toFixed(1)+" "+u[i]); }
function ago(ts){ if(!ts) return "—"; const s=Math.max(0,(Date.now()/1000-ts)); if(s<60)return Math.floor(s)+"s"; if(s<3600)return Math.floor(s/60)+"m"; if(s<86400)return Math.floor(s/3600)+"h"; return Math.floor(s/86400)+"d"; }
function hms(ts){ const d=new Date(ts*1000); return d.toLocaleTimeString(); }
function dur(s){ s=Math.floor(s||0); const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60); return (d?d+"d ":"")+(h?h+"h ":"")+m+"m"; }

function setConn(ok){ const dot=document.getElementById("connDot"), t=document.getElementById("connTxt");
  dot.className="dot "+(ok?"on":"off"); t.textContent = ok? "servidor en línea":"sin conexión"; }

function renderCards(s){
  const c=document.getElementById("cards");
  const items=[
    ["Máquinas", s.machine_count, "registradas en el pool"],
    ["Conectadas", s.online_count, "clientes en línea ahora"],
    ["Buzones con contenido", s.clip_count, "esperando ser recogidos"],
    ["Uptime", dur(s.uptime_seconds), "desde el arranque"],
    ["Versión", s.version, "protocolo "+s.protocol],
    ["Backend cripto", s.crypto_backend, "pool: "+s.pool_id],
  ];
  c.innerHTML = items.map(it=>`<div class="card"><div class="k">${esc(it[0])}</div><div class="v">${esc(it[1])}</div><div class="s">${esc(it[2])}</div></div>`).join("");
}
function renderMachines(ms){
  const tb=document.getElementById("machines");
  if(!ms.length){ tb.innerHTML=`<tr><td colspan="6" class="empty">No hay máquinas registradas.</td></tr>`; return; }
  tb.innerHTML = ms.map(m=>`<tr>
     <td>${m.slot}</td><td>${esc(m.name)}</td>
     <td><span class="dot ${m.online?"on":"off"}"></span> ${m.online?"en línea":"offline"}</td>
     <td>${m.enabled?"sí":"<span class='muted'>no</span>"}</td>
     <td class="muted">${m.last_seen?ago(m.last_seen)+" atrás":"nunca"}</td>
     <td>${m.has_clip?"<span class='tag'>con contenido</span>":"<span class='muted'>vacío</span>"}</td></tr>`).join("");
}
function renderMailboxes(mb){
  const tb=document.getElementById("mailboxes");
  if(!mb.length){ tb.innerHTML=`<tr><td colspan="6" class="empty">Ningún buzón tiene contenido ahora mismo.</td></tr>`; return; }
  tb.innerHTML = mb.map(x=>`<tr>
     <td>#${x.slot} · ${esc(x.dest_name)}</td>
     <td>${x.from_id?("#"+x.from_id+" · "+esc(x.from_name||"")):"<span class='muted'>—</span>"}</td>
     <td><span class="tag ${esc(x.kind)}">${esc(x.kind)}</span></td>
     <td>${human(x.size)}</td>
     <td class="wrap">${esc(x.summary||"")}</td>
     <td class="muted">${ago(x.updated_at)} atrás</td></tr>`).join("");
}
function describe(e){
  switch(e.type){
    case "connect": return `🔌 <b>${esc(e.name)}</b> (slot ${e.slot}) se conectó`;
    case "disconnect": return `⏏️ <b>${esc(e.name)}</b> (slot ${e.slot}) se desconectó`;
    case "push": return `📤 <b>${esc(e.from_name)}</b> (#${e.from_id}) → buzón #${e.slot} <b>${esc(e.dest_name||"")}</b>: ${esc(e.summary||e.kind)}`;
    case "pull": return `📥 <b>${esc(e.by_name)}</b> (#${e.by}) recogió el buzón #${e.slot} <span class="muted">(${esc(e.kind)}, ${human(e.size)})</span>`;
    case "clear": return `🗑️ buzón #${e.slot} vaciado por <b>${esc(e.by_name)}</b>`;
    default: return esc(e.type);
  }
}
function renderFeed(evs){
  const f=document.getElementById("feed");
  if(!evs.length){ f.innerHTML=`<div class="empty">Sin actividad todavía.</div>`; return; }
  f.innerHTML = evs.slice().reverse().map(e=>`<div class="ev"><span class="t">${hms(e.ts)}</span><span>${describe(e)}</span></div>`).join("");
}

async function refresh(){
  try{
    const ov = await api("/api/admin/overview");
    setConn(true);
    document.getElementById("err").style.display="none";
    document.getElementById("ver").textContent = "v"+ov.server.version;
    renderCards(ov.server);
    renderMachines(ov.machines);
    renderMailboxes(ov.mailboxes);
    const act = await api("/api/admin/activity");
    renderFeed(act.events);
  }catch(e){
    setConn(false);
    const el=document.getElementById("err"); el.style.display="block"; el.textContent=e.message;
  }
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
