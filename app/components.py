"""Animated, self-contained widgets (plain HTML/canvas/SVG/JS, no CDN scripts, so they work offline).

hero()       neural-network banner with the five companies as glowing nodes + typing subtitle
kpi_cards()  count-up numbers with animated sparklines
rings()      animated progress rings (verification scores)
network()    draggable force-directed partnership graph with flowing signal particles
pipeline_html(), ticker_html(), chips_html()   pure HTML/CSS (styled by app/theme.py)
"""
import html as _html
import json

import streamlit as st
import streamlit.components.v1 as components

from app.theme import COMPANY_COLORS, GOOD, TICKER_COMPANY, WARN, logo_uri

REL_COLORS = {"investment": "#D4A24C", "supply": "#7FA85A", "cloud": "#5B8DEF",
              "distribution": "#B97AA6", "competition": "#C96B6B", "financing": "#8A7FCF"}

BASE_CSS = """@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;600;700&display=swap');
*{box-sizing:border-box}html,body{margin:0;height:100%;background:transparent;overflow:hidden;
font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;color:#E4E7EB}"""


def _js(obj):
    """JSON that is safe to drop inside a <script> tag."""
    return json.dumps(obj).replace("</", "<\\/")


def _render(page, height, auto=False):
    """st.iframe on current Streamlit; the older components.html call keeps older installs working.
    auto=True lets the frame grow to its content (cards that wrap on narrow screens)."""
    if hasattr(st, "iframe"):
        st.iframe(page, height="content" if auto else height)
    else:
        components.html(page, height=height, scrolling=False)


# --------------------------------------------------------------------------- hero
_HERO = r"""<!doctype html><html><head><meta charset="utf-8"><style>__BASE__
#hero{position:relative;height:100%;border-radius:22px;overflow:hidden;border:1px solid rgba(0,229,255,.24);
background:linear-gradient(120deg,rgba(0,229,255,.08),rgba(139,92,246,.13) 55%,rgba(255,61,203,.08)),rgba(6,9,19,.6)}
canvas{position:absolute;inset:0;width:100%;height:100%}.txt{position:relative;padding:24px 34px;pointer-events:none;z-index:2;max-width:62%}
.badge{display:inline-flex;align-items:center;gap:8px;padding:5px 12px;border-radius:999px;border:1px solid rgba(125,255,176,.4);
background:rgba(125,255,176,.08);color:#7DFFB0;font:600 11px 'JetBrains Mono',monospace;letter-spacing:1px}
.dot{width:8px;height:8px;border-radius:50%;background:#7DFFB0;box-shadow:0 0 10px #7DFFB0;animation:b 1.6s infinite}@keyframes b{50%{opacity:.25}}
h1{margin:12px 0 6px;font-size:clamp(24px,3.6vw,42px);line-height:1.08;font-weight:700;letter-spacing:-.8px;
background:linear-gradient(90deg,#fff 5%,#7DF9FF 50%,#C4A5FF 95%);-webkit-background-clip:text;color:transparent}
#sub{min-height:22px;color:#9FB3D1;font-size:15px}#sub::after{content:"\258D";color:#00E5FF;animation:b 1s infinite;margin-left:2px}
@media(max-width:700px){.txt{max-width:100%;padding:16px 18px 70px}h1{font-size:24px!important}#sub{font-size:13px}.badge{font-size:9.5px;letter-spacing:.5px}}
</style></head><body><div id="hero"><canvas id="c"></canvas><div class="txt"><div class="badge"><span class="dot"></span><span>__STATUS__</span></div>
<h1>__TITLE__</h1><div id="sub"></div></div></div><script>
const CFG=__CFG__;const cv=document.getElementById('c'),ctx=cv.getContext('2d');let W=0,H=0;const dpr=Math.min(window.devicePixelRatio||1,2);
function size(){const r=cv.getBoundingClientRect();W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}size();
new ResizeObserver(size).observe(cv);const mouse={x:-999,y:-999};const hero=document.getElementById('hero');
hero.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();mouse.x=e.clientX-r.left;mouse.y=e.clientY-r.top});
hero.addEventListener('mouseleave',()=>{mouse.x=mouse.y=-999});
const P=[];for(let i=0;i<78;i++)P.push({x:Math.random()*900,y:Math.random()*300,vx:(Math.random()-.5)*.35,vy:(Math.random()-.5)*.35,r:Math.random()*1.4+.6});
const C=CFG.companies.map((c,i)=>({...c,a:i/CFG.companies.length*Math.PI*2+.6,ph:Math.random()*6}));C.forEach(c=>{if(c.logo){c.img=new Image();c.img.src=c.logo}});const pulses=[];let last=0;
function pos(c,t){if(W<640){const k=C.indexOf(c);return{x:W*(.13+.185*k)+Math.sin(t/1700+c.ph)*5,y:H-34+Math.cos(t/2100+c.ph)*4}}const cx=W*.76,cy=H*.5,rx=Math.min(W*.2,190),ry=Math.min(H*.34,92);
const a=c.a+t/9000;return{x:cx+Math.cos(a)*rx+Math.sin(t/1700+c.ph)*10,y:cy+Math.sin(a)*ry+Math.cos(t/2100+c.ph)*8}}
function frame(t){ctx.clearRect(0,0,W,H);
for(const p of P){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;
const dx=p.x-mouse.x,dy=p.y-mouse.y,d=Math.hypot(dx,dy);if(d<120){p.x+=dx/d*1.4;p.y+=dy/d*1.4}}
ctx.lineWidth=1;for(let i=0;i<P.length;i++){for(let j=i+1;j<P.length;j++){const a=P[i],b=P[j],d=Math.hypot(a.x-b.x,a.y-b.y);
if(d<108){ctx.strokeStyle='rgba(0,229,255,'+(1-d/108)*.28+')';ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}}}
const cp=C.map(c=>pos(c,t));
cp.forEach((q,i)=>{for(const p of P){const d=Math.hypot(p.x-q.x,p.y-q.y);if(d<150){ctx.strokeStyle=C[i].color+Math.floor((1-d/150)*70).toString(16).padStart(2,'0');
ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke()}}});
if(t-last>650){last=t;const a=Math.floor(Math.random()*C.length);let b=Math.floor(Math.random()*C.length);if(a!==b)pulses.push({a,b,k:0,c:C[a].color})}
for(let i=pulses.length-1;i>=0;i--){const u=pulses[i];u.k+=.014;if(u.k>=1){pulses.splice(i,1);continue}
const A=cp[u.a],B=cp[u.b];ctx.strokeStyle=u.c+'44';ctx.beginPath();ctx.moveTo(A.x,A.y);ctx.lineTo(B.x,B.y);ctx.stroke();
const x=A.x+(B.x-A.x)*u.k,y=A.y+(B.y-A.y)*u.k;const g=ctx.createRadialGradient(x,y,0,x,y,12);g.addColorStop(0,u.c);g.addColorStop(1,'transparent');
ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,12,0,6.3);ctx.fill()}
ctx.fillStyle='rgba(180,230,255,.75)';for(const p of P){ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,6.3);ctx.fill()}
cp.forEach((q,i)=>{const c=C[i],g=ctx.createRadialGradient(q.x,q.y,0,q.x,q.y,46);g.addColorStop(0,c.color+'cc');g.addColorStop(1,'transparent');
ctx.fillStyle=g;ctx.beginPath();ctx.arc(q.x,q.y,46,0,6.3);ctx.fill();ctx.fillStyle='#070B14';ctx.beginPath();ctx.arc(q.x,q.y,20,0,6.3);ctx.fill();ctx.strokeStyle=c.color;ctx.lineWidth=2;ctx.shadowColor=c.color;ctx.shadowBlur=16;ctx.stroke();ctx.shadowBlur=0;if(c.img&&c.img.complete&&c.img.naturalWidth){ctx.drawImage(c.img,q.x-11,q.y-11,22,22)}else{ctx.fillStyle=c.color;ctx.beginPath();ctx.arc(q.x,q.y,6.5,0,6.3);ctx.fill()}
ctx.fillStyle='#fff';ctx.font='600 12px Space Grotesk,sans-serif';ctx.textAlign='center';ctx.fillText(c.name,q.x,q.y+37)});
requestAnimationFrame(frame)}requestAnimationFrame(frame);
const sub=document.getElementById('sub');let pi=0,ci=0,del=false;
(function type(){const s=CFG.phrases[pi];if(!del){ci++;sub.textContent=s.slice(0,ci);if(ci===s.length){del=true;return void setTimeout(type,1900)}setTimeout(type,30)}
else{ci--;sub.textContent=s.slice(0,ci);if(ci===0){del=false;pi=(pi+1)%CFG.phrases.length}setTimeout(type,14)}})();
</script></body></html>"""


def hero(title, status, phrases, height=250, animated=False):
    """Page header. Static by default (title, status badge, subtitle, company row); animated=True brings back
    the neural-network banner."""
    if animated:
        cfg = {"companies": [{"name": n, "color": c, "logo": logo_uri(n)} for n, c in COMPANY_COLORS.items()], "phrases": phrases}
        page = (_HERO.replace("__BASE__", BASE_CSS).replace("__CFG__", _js(cfg))
                .replace("__TITLE__", _html.escape(title)).replace("__STATUS__", _html.escape(status)))
        _render(page, height)
        return
    kind = "demo" if "DEMO" in status.upper() else "live"
    cos = "".join('<span class="co"><img src="%s">%s</span>' % (logo_uri(n), _html.escape(n)) for n in COMPANY_COLORS)
    sub = _html.escape(phrases[0]) if phrases else ""
    st.markdown('<div class="hdr"><div><span class="badge %s">%s</span><h1>%s</h1><div class="sub">%s</div></div>'
                '<div class="cos">%s</div></div>' % (kind, _html.escape(status), _html.escape(title), sub, cos),
                unsafe_allow_html=True)


# --------------------------------------------------------------------------- KPI cards
_KPI = r"""<!doctype html><html><head><meta charset="utf-8"><style>__BASE__html,body{height:auto!important;overflow:visible!important}
#row{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;padding:4px}
.card{position:relative;overflow:hidden;border-radius:8px;padding:14px 16px 12px;border:1px solid #2A313B;border-top:3px solid var(--c);
background:linear-gradient(180deg,color-mix(in srgb,var(--c) 7%,#171C23) 0,#171C23 60%);
opacity:0;transform:translateY(8px);animation:up .45s cubic-bezier(.2,.8,.2,1) forwards;transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.35);border-color:#3A4452}
@keyframes up{to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.card{animation:none;opacity:1;transform:none}}
.lg{width:15px;height:15px;vertical-align:-3px;margin-right:7px}
.lab{font:600 11px 'Inter',sans-serif;letter-spacing:.8px;text-transform:uppercase;color:#8B95A5}
.val{font:600 28px 'Inter',sans-serif;font-variant-numeric:tabular-nums;margin:6px 0 2px;color:#E4E7EB}
.sub{font-size:12px;color:#8B95A5;min-height:16px}
.d{display:inline-block;padding:1px 6px;border-radius:4px;font:600 11px 'Inter',sans-serif;margin-right:6px}
.d.up{color:#3FB27F;background:rgba(63,178,127,.12)}.d.down{color:#E06C6C;background:rgba(224,108,108,.12)}
svg.sp{display:block;width:100%;height:34px;margin-top:8px}
.sp path.l{fill:none;stroke:var(--c);stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.sp path.a{fill:url(#g);opacity:0;animation:f .6s .5s forwards}@keyframes f{to{opacity:1}}
</style></head><body><div id="row"></div><script>
const items=__DATA__;const row=document.getElementById('row');
row.innerHTML=items.map((it,i)=>{let sp='';if(it.spark&&it.spark.length>1){const s=it.spark,mn=Math.min(...s),mx=Math.max(...s),rg=(mx-mn)||1;
const pts=s.map((v,k)=>[k/(s.length-1)*100,30-((v-mn)/rg)*26-2]);const d='M'+pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' L');
sp='<svg class="sp" viewBox="0 0 100 32" preserveAspectRatio="none"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+it.color+'" stop-opacity=".18"/><stop offset="1" stop-color="'+it.color+'" stop-opacity="0"/></linearGradient></defs><path class="a" d="'+d+' L100,32 L0,32Z"/><path class="l" d="'+d+'" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"><animate attributeName="stroke-dashoffset" from="1" to="0" dur=".9s" begin="'+(0.15+i*.06)+'s" fill="freeze"/></path></svg>'}
const dl=it.delta?'<span class="d '+(it.delta_up?'up':'down')+'">'+it.delta+'</span>':'';
return '<div class="card" style="--c:'+it.color+';animation-delay:'+(i*60)+'ms"><div class="lab">'+(it.logo?'<img class="lg" src="'+it.logo+'">':'')+it.label+'</div><div class="val"><span data-i="'+i+'">'+fmt(it,0)+'</span></div><div class="sub">'+dl+(it.sub||'')+'</div>'+sp+'</div>'}).join('');
function fmt(it,v){return (it.prefix||'')+v.toLocaleString(undefined,{minimumFractionDigits:it.decimals||0,maximumFractionDigits:it.decimals||0})+(it.suffix||'')}
const still=matchMedia('(prefers-reduced-motion: reduce)').matches,t0=performance.now();
function tick(now){let go=false;document.querySelectorAll('[data-i]').forEach(el=>{const i=+el.dataset.i,it=items[i];
const k=still?1:Math.min(1,Math.max(0,(now-t0-i*60)/700)),e=k===1?1:1-Math.pow(1-k,3);el.textContent=fmt(it,it.value*e);if(k<1)go=true});if(go)requestAnimationFrame(tick)}
requestAnimationFrame(tick);
</script></body></html>"""


def kpi_cards(items, height=190):
    """items: [{label, value, prefix, suffix, decimals, sub, delta, delta_up, spark:[...], color}]"""
    _render(_KPI.replace("__BASE__", BASE_CSS).replace("__DATA__", _js(items)), height, auto=True)


# --------------------------------------------------------------------------- rings
_RINGS = r"""<!doctype html><html><head><meta charset="utf-8"><style>__BASE__html,body{height:auto!important;overflow:visible!important}
#row{display:flex;flex-wrap:wrap;gap:14px;justify-content:space-around;padding:4px}
.r{flex:1;min-width:170px;text-align:center;padding:14px 8px;border-radius:8px;border:1px solid #2A313B;background:#171C23}
.dial{position:relative;width:112px;height:112px;margin:0 auto}
svg{display:block;width:112px;height:112px;transform:rotate(-90deg)}
.bg{fill:none;stroke:rgba(255,255,255,.08);stroke-width:8}.fg{fill:none;stroke:var(--c);stroke-width:8;stroke-linecap:butt}
.n{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
font:600 24px 'Inter',sans-serif;font-variant-numeric:tabular-nums;letter-spacing:-.5px;color:#E4E7EB}
.n.big{font-size:21px}.n small{font-size:.58em;font-weight:500;color:#8B95A5;margin-left:1px;align-self:center;transform:translateY(1px)}
.l{margin-top:12px;font:600 12px 'Inter',sans-serif;letter-spacing:.8px;text-transform:uppercase;color:#C3CAD4}
.s{font-size:11.5px;color:#8B95A5;margin-top:3px;padding:0 6px}
</style></head><body><div id="row"></div><script>
const items=__DATA__;const C=2*Math.PI*44,still=matchMedia('(prefers-reduced-motion: reduce)').matches;document.getElementById('row').innerHTML=items.map((it,i)=>{const end=C*(1-it.pct/100);return(
'<div class="r" style="--c:'+it.color+';animation-delay:'+(i*140)+'ms"><div class="dial"><svg viewBox="0 0 112 112"><circle class="bg" cx="56" cy="56" r="44"/><circle class="fg" cx="56" cy="56" r="44" stroke-dasharray="'+C+'" stroke-dashoffset="'+(still?end:C)+'" data-p="'+it.pct+'">'+(still?'':'<animate attributeName="stroke-dashoffset" from="'+C+'" to="'+end+'" dur="1.6s" begin="'+(.3+i*.14)+'s" fill="freeze" calcMode="spline" keySplines=".2 .8 .2 1" keyTimes="0;1"/>')+'</circle></svg>'+
'<div class="n'+(it.pct>=100?' big':'')+'"><span data-i="'+i+'">'+(still?it.pct:0)+'</span><small>%</small></div></div><div class="l">'+it.label+'</div><div class="s">'+(it.sub||'')+'</div></div>')}).join('');
const t0=performance.now();if(!still)(function tick(now){let go=false;document.querySelectorAll('[data-i]').forEach(el=>{const i=+el.dataset.i,k=Math.min(1,Math.max(0,(now-t0-300-i*140)/1600)),e=k===1?1:1-Math.pow(2,-10*k);
el.textContent=Math.round(items[i].pct*e);if(k<1)go=true});if(go)requestAnimationFrame(tick)})(t0);
</script></body></html>"""


def rings(items, height=250):
    """items: [{label, pct (0-100), sub, color}]"""
    _render(_RINGS.replace("__BASE__", BASE_CSS).replace("__DATA__", _js(items)), height, auto=True)


# --------------------------------------------------------------------------- network
_NET = r"""<!doctype html><html><head><meta charset="utf-8"><style>__BASE__
#w{position:relative;height:100%;border-radius:8px;overflow:hidden;border:1px solid #2A313B;background:#171C23}
canvas{width:100%;height:100%;display:block;cursor:grab}canvas:active{cursor:grabbing}
#lg{position:absolute;left:14px;top:12px;display:flex;flex-wrap:wrap;gap:6px 14px;font:600 11px 'Inter',sans-serif;letter-spacing:.6px;text-transform:uppercase;pointer-events:none}
#lg span{display:flex;align-items:center;gap:6px;color:#C3CAD4}#lg i{width:14px;height:3px;border-radius:2px;display:block}
#tip{position:absolute;pointer-events:none;max-width:290px;padding:9px 12px;border-radius:6px;font-size:12.5px;line-height:1.45;color:#E4E7EB;
background:#0F1318;border:1px solid #2A313B;opacity:0;transition:opacity .15s}
#tip b{color:#E4E7EB}#hint{position:absolute;right:14px;bottom:10px;font:11px 'Inter',sans-serif;color:#6B7586}
</style></head><body><div id="w"><canvas id="c"></canvas><div id="lg"></div><div id="tip"></div><div id="hint">drag nodes · hover for sources</div></div><script>
const D=__DATA__;const cv=document.getElementById('c'),ctx=cv.getContext('2d'),tip=document.getElementById('tip');let W=0,H=0;const dpr=Math.min(devicePixelRatio||1,2);
function size(){const r=cv.getBoundingClientRect();W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}size();new ResizeObserver(size).observe(cv);
document.getElementById('lg').innerHTML=Object.entries(D.rel).map(([k,c])=>'<span><i style="background:'+c+'"></i>'+k+'</span>').join('');
const nodes={};D.edges.forEach(e=>{for(const n of [e.from,e.to])if(!nodes[n])nodes[n]={id:n,x:0,y:0,vx:0,vy:0,deg:0,core:D.core.includes(n)};nodes[e.from].deg++;nodes[e.to].deg++});
const N=Object.values(nodes);N.forEach(n=>{n.r=(n.core?19:8)+Math.sqrt(n.deg)*2.4;n.col=D.colors[n.id]||'#8FA3C0';if(D.logos[n.id]){n.img=new Image();n.img.src=D.logos[n.id]}});
let drag=null,hover=null,hoverEdge=null,mx=0,my=0,placed=false;
// lay out once the frame has a real size (it is 0x0 while its tab is hidden): the big five on an inner ring,
// every partner on an outer ring next to the company it is linked to, so the physics starts untangled
function seed(){const cx=W/2,cy=H/2,R=Math.min(W,H),core=N.filter(n=>n.core),rest=N.filter(n=>!n.core);
core.forEach((n,i)=>{const a=i/core.length*Math.PI*2-Math.PI/2;n.a=a;n.x=cx+Math.cos(a)*R*.18;n.y=cy+Math.sin(a)*R*.18});
rest.forEach(n=>{const e=D.edges.find(e=>(e.from===n.id&&nodes[e.to].core)||(e.to===n.id&&nodes[e.from].core));n.a=e?nodes[e.from===n.id?e.to:e.from].a:0});
rest.sort((p,q)=>p.a-q.a).forEach((n,i)=>{const a=(i+.5)/rest.length*Math.PI*2-Math.PI/2;n.x=cx+Math.cos(a)*W*.4;n.y=cy+Math.sin(a)*H*.38});
N.forEach(n=>{n.vx=n.vy=0});placed=true}
function physics(){if(W<50||H<50)return;if(!placed)seed();
for(let i=0;i<N.length;i++){const a=N[i];for(let j=i+1;j<N.length;j++){const b=N[j];let dx=a.x-b.x,dy=a.y-b.y;if(Math.abs(dx)+Math.abs(dy)<.5){dx=Math.random()-.5;dy=Math.random()-.5}
let d2=Math.max(dx*dx+dy*dy,60),d=Math.sqrt(d2),f=(4200*(1+N.length/14))/d2;dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;
const gap=a.r+b.r+26;if(d<gap){const push=(gap-d)*.25;a.x+=dx*push;a.y+=dy*push;b.x-=dx*push;b.y-=dy*push}}
a.vx+=(W/2-a.x)*.0016;a.vy+=(H/2-a.y)*.0021}
D.edges.forEach(e=>{const a=nodes[e.from],b=nodes[e.to];let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-(150+a.r+b.r))*.011;dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f});
N.forEach(n=>{if(n===drag)return;n.vx*=.85;n.vy*=.85;n.x+=n.vx;n.y+=n.vy;n.x=Math.max(n.r+8,Math.min(W-n.r-8,n.x));n.y=Math.max(n.r+30,Math.min(H-n.r-22,n.y))})}
function seg(px,py,x1,y1,x2,y2){const dx=x2-x1,dy=y2-y1,l=dx*dx+dy*dy||1;let t=Math.max(0,Math.min(1,((px-x1)*dx+(py-y1)*dy)/l));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy))}
function arrow(x,y,ang,col,s){ctx.fillStyle=col;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-s*Math.cos(ang-.45),y-s*Math.sin(ang-.45));ctx.lineTo(x-s*Math.cos(ang+.45),y-s*Math.sin(ang+.45));ctx.fill()}
function frame(t){physics();ctx.clearRect(0,0,W,H);
if(!D.edges.length){ctx.fillStyle='#5E7190';ctx.font='15px Space Grotesk,sans-serif';ctx.textAlign='center';ctx.fillText('No partnership data yet',W/2,H/2);return requestAnimationFrame(frame)}
D.edges.forEach((e,k)=>{const a=nodes[e.from],b=nodes[e.to],col=D.rel[e.type]||'#8FA3C0',on=!hover||hover===a||hover===b||hoverEdge===e;
const ang=Math.atan2(b.y-a.y,b.x-a.x),x1=a.x+Math.cos(ang)*a.r,y1=a.y+Math.sin(ang)*a.r,x2=b.x-Math.cos(ang)*(b.r+3),y2=b.y-Math.sin(ang)*(b.r+3);
ctx.globalAlpha=on?1:.1;ctx.strokeStyle=col;ctx.lineWidth=(hoverEdge===e?3:1.6)+(e.amount?Math.min(2.5,Math.log10(e.amount)/4):0);ctx.setLineDash(e.type==='competition'?[6,6]:[]);
ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.setLineDash([]);
if(e.type!=='competition'){arrow(x2,y2,ang,col,9)}
ctx.globalAlpha=1});
N.forEach(n=>{const on=!hover||hover===n||D.edges.some(e=>(e.from===hover.id||e.to===hover.id)&&(e.from===n.id||e.to===n.id));ctx.globalAlpha=on?1:.18;
ctx.fillStyle='#0F1318';ctx.strokeStyle=n.col;ctx.lineWidth=n===hover?3:2;ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,6.3);ctx.fill();ctx.stroke();
if(n.img&&n.img.complete&&n.img.naturalWidth){const w=n.r*1.15;ctx.drawImage(n.img,n.x-w/2,n.y-w/2,w,w)}else{ctx.fillStyle=n.col;ctx.beginPath();ctx.arc(n.x,n.y,n.r*.42,0,6.3);ctx.fill()}
ctx.fillStyle='#E4E7EB';ctx.font=(n.core?'600 13px':'500 11.5px')+' Inter,sans-serif';ctx.textAlign='center';ctx.fillText(n.id.length>15?n.id.slice(0,14)+'\u2026':n.id,n.x,n.y+n.r+15);ctx.globalAlpha=1});
requestAnimationFrame(frame)}requestAnimationFrame(frame);
function show(html,x,y){tip.innerHTML=html;tip.style.opacity=1;tip.style.left=Math.min(W-300,x+16)+'px';tip.style.top=Math.min(H-110,y+16)+'px'}
cv.addEventListener('mousemove',ev=>{const r=cv.getBoundingClientRect();mx=ev.clientX-r.left;my=ev.clientY-r.top;
if(drag){drag.x=mx;drag.y=my;drag.vx=drag.vy=0;return}
hover=N.find(n=>Math.hypot(n.x-mx,n.y-my)<n.r+4)||null;hoverEdge=null;
if(hover){const rel=D.edges.filter(e=>e.from===hover.id||e.to===hover.id);show('<b>'+hover.id+'</b><br>'+rel.length+' relationship'+(rel.length>1?'s':'')+'<br>'+rel.map(e=>'• '+e.from+' → '+e.to+' ('+e.type+')').join('<br>'),mx,my)}
else{for(const e of D.edges){const a=nodes[e.from],b=nodes[e.to];if(seg(mx,my,a.x,a.y,b.x,b.y)<7){hoverEdge=e;break}}
if(hoverEdge){const e=hoverEdge;show('<b>'+e.from+' → '+e.to+'</b> · '+e.type+(e.amount?' · $'+Number(e.amount).toLocaleString():'')+'<br>'+e.desc+'<br><span style="color:#8FA3C0">source '+e.source+' · confidence '+e.confidence+'</span>',mx,my)}else tip.style.opacity=0}});
cv.addEventListener('mousedown',()=>{if(hover)drag=hover});window.addEventListener('mouseup',()=>{drag=null});cv.addEventListener('mouseleave',()=>{hover=null;hoverEdge=null;tip.style.opacity=0;drag=null});
</script></body></html>"""


def network(edges, height=560):
    """edges: dicts with from_company/to_company/relationship_type/description/amount_usd/source_id/confidence."""
    clean = []
    for e in edges:
        amt = e.get("amount_usd")
        clean.append({"from": e["from_company"], "to": e["to_company"], "type": e["relationship_type"],
                      "desc": e["description"], "amount": None if amt in (None, "") or amt != amt else float(amt),
                      "source": e["source_id"], "confidence": e["confidence"]})
    data = {"edges": clean, "colors": COMPANY_COLORS, "rel": REL_COLORS, "core": list(COMPANY_COLORS),
            "logos": {c: logo_uri(c) for c in COMPANY_COLORS}}
    _render(_NET.replace("__BASE__", BASE_CSS).replace("__DATA__", _js(data)), height)


# --------------------------------------------------------------------------- pure HTML bits
PIPE_NODES = [("supervisor", "Supervisor"), ("rag", "Researcher"), ("analyst", "Analyst"), ("verify", "Verifier"), ("write", "Writer")]


def pipeline_html(states):
    """states: {node: 'pending'|'active'|'done'|'skip'} -> the animated agent pipeline."""
    parts = []
    for i, (key, label) in enumerate(PIPE_NODES):
        parts.append('<span class="node %s">%s</span>' % (states.get(key, "pending"), label))
        if i < len(PIPE_NODES) - 1:
            parts.append('<span class="arrow">&#9654;</span>')
    return '<div class="pipe">%s</div>' % "".join(parts)


def ticker_html(rows, status=None):
    """rows: [{sym, price, chg}] (chg in %). status: optional (kind, label) line above the quotes; kind "live" adds a pulsing dot."""
    def one(r):
        cls = "up" if r["chg"] >= 0 else "down"
        arrow = "&#9650;" if r["chg"] >= 0 else "&#9660;"
        logo = logo_uri(TICKER_COMPANY.get(r["sym"], ""))
        img = '<img class="tl" src="%s">' % logo if logo else ""
        return '<span class="tk %s">%s<b>%s</b>$%s <span class="chg">%s %+.2f%%</span></span>' % (
            cls, img, _html.escape(r["sym"]), format(r["price"], ",.2f"), arrow, r["chg"])
    track = "".join(one(r) for r in rows) if rows else '<span class="tk">awaiting market data</span>'
    badge = ""
    if status:
        kind, label = status
        badge = '<div class="tk-status %s">%s%s</div>' % (
            _html.escape(kind), '<span class="live-dot"></span>' if kind == "live" else "", _html.escape(label))
    return '<div class="ticker">%s<div class="ticker-track">%s</div></div>' % (badge, track)


def chips_html(citations):
    """Clickable citation chips; green = tier 1 (primary), amber = tier 2 (press)."""
    out = []
    for c in citations:
        out.append('<a class="chip t%s" href="%s" target="_blank" rel="noopener" title="%s"><span class="tag">%s</span>%s<span class="tag">tier %s</span></a>' % (
            _html.escape(str(c["tier"])), _html.escape(c["url"]), _html.escape(c["title"]), _html.escape(c["tag"]),
            _html.escape(c["source_id"]), _html.escape(str(c["tier"]))))
    return '<div class="chips">%s</div>' % "".join(out)
