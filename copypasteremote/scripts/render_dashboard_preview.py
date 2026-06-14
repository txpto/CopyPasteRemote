"""Render the dashboard UI to a PNG using Playwright + a stubbed backend.

It writes the real DASHBOARD_HTML to a temp file and intercepts window.prompt /
window.fetch so the page renders representative demo data with no server.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cpr_server.dashboard import DASHBOARD_HTML  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/images/dashboard.png"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

html_path = "/tmp/cpr_dash_preview.html"
with open(html_path, "w", encoding="utf-8") as fh:
    fh.write(DASHBOARD_HTML)

INIT = r"""
window.prompt = () => "demo-admin-key";
const now = Date.now()/1000;
const overview = {
  server: {app:"CopyPasteRemote", version:"1.0.0", protocol:"1.0",
    uptime_seconds: 9*3600+12*60, started_at: now-33120, crypto_backend:"cryptography",
    pool_id:"default", pool_key_fp:"7YLVlbFf", slot_ttl_seconds:86400,
    max_payload_bytes:2147483648, machine_count:4, online_count:3, clip_count:2},
  machines: [
    {slot:1, name:"PC-Casa", enabled:true, online:true, last_seen:now-28, created_at:now-200000, has_clip:false},
    {slot:2, name:"PC-Oficina", enabled:true, online:true, last_seen:now-4, created_at:now-200000, has_clip:true},
    {slot:3, name:"Portatil-Viajes", enabled:true, online:true, last_seen:now-2, created_at:now-90000, has_clip:false},
    {slot:4, name:"Servidor-Lab", enabled:true, online:false, last_seen:now-5400, created_at:now-90000, has_clip:true}
  ],
  mailboxes: [
    {slot:2, dest_name:"PC-Oficina", from_id:1, from_name:"PC-Casa", kind:"text", size:1234,
     summary:"text (1.2 KB)", updated_at:now-4, inline:true},
    {slot:4, dest_name:"Servidor-Lab", from_id:3, from_name:"Portatil-Viajes", kind:"files", size:5*1024*1024,
     summary:"3 files, 1 folder (5.0 MB)", updated_at:now-120, inline:false}
  ]
};
const activity = {last_seq:7, events:[
  {seq:1, ts:now-300, type:"connect", slot:1, name:"PC-Casa"},
  {seq:2, ts:now-280, type:"connect", slot:2, name:"PC-Oficina"},
  {seq:3, ts:now-200, type:"push", from_id:1, from_name:"PC-Casa", slot:2, dest_name:"PC-Oficina", kind:"text", size:1234, summary:"text (1.2 KB)"},
  {seq:4, ts:now-160, type:"pull", by:2, by_name:"PC-Oficina", slot:2, kind:"text", size:1234},
  {seq:5, ts:now-90, type:"connect", slot:3, name:"Portatil-Viajes"},
  {seq:6, ts:now-120, type:"push", from_id:3, from_name:"Portatil-Viajes", slot:4, dest_name:"Servidor-Lab", kind:"files", size:5242880, summary:"3 files, 1 folder (5.0 MB)"},
  {seq:7, ts:now-30, type:"disconnect", slot:4, name:"Servidor-Lab"}
]};
window.fetch = async (url) => ({
  ok:true, status:200,
  json: async () => (String(url).indexOf("activity")>=0 ? activity : overview)
});
"""

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1180, "height": 1000}, device_scale_factor=2)
    page.add_init_script(INIT)
    page.goto("file://" + html_path)
    page.wait_for_timeout(800)
    page.screenshot(path=OUT, full_page=True)
    browser.close()
print("wrote", OUT)
