"""Professional look: global CSS (flat slate surfaces, quiet borders, underline tabs), a Plotly template,
and one color per company so every chart agrees. Call apply() once at the top of the app."""
import base64
import functools
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

COMPANY_COLORS = {
    "Google": "#5B8DEF", "OpenAI": "#3FA88A", "Anthropic": "#D2805E", "Nvidia": "#8BAE4E", "Apple": "#A3ADBD",
}
TICKER_COMPANY = {"GOOGL": "Google", "NVDA": "Nvidia", "AAPL": "Apple"}
ACCENT, VIOLET, PINK = "#4C8BF5", "#8A7FCF", "#C27BA0"
GOOD, WARN, BAD, MUTED = "#3FB27F", "#D4A24C", "#E06C6C", "#8B95A5"
BG, SURFACE, BORDER, TEXT = "#0F1318", "#171C23", "#2A313B", "#E4E7EB"
FONT = "'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"


LOGO_DIR = Path(__file__).resolve().parent / "assets" / "logos"
LOGO_FILES = {"Google": "google", "OpenAI": "openai", "Anthropic": "anthropic", "Nvidia": "nvidia", "Apple": "apple"}


@functools.lru_cache(maxsize=None)
def logo_uri(company, color=None):
    """data: URI of the company's logo (Simple Icons, CC0 files; the marks belong to their owners and are used only to
    identify the companies), tinted with its brand color. '' if there is no logo."""
    f = LOGO_DIR / (LOGO_FILES.get(company, "_") + ".svg")
    if not f.exists():
        return ""
    svg = f.read_text(encoding="utf-8").replace("<svg ", '<svg fill="%s" ' % (color or COMPANY_COLORS.get(company, "#FFFFFF")), 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return "rgba(%d,%d,%d,%s)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--acc:#4C8BF5;--good:#3FB27F;--warn:#D4A24C;--bad:#E06C6C;--muted:#8B95A5;
  --bg:#0F1318;--surface:#171C23;--border:#2A313B;--text:#E4E7EB}
html,body,[class*="css"],.stApp{font-family:'Inter',ui-sans-serif,system-ui,sans-serif}
.stApp{background:linear-gradient(180deg,#131922 0,var(--bg) 420px)}

@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}

header[data-testid="stHeader"]{background:transparent}
#MainMenu,footer{visibility:hidden}
.block-container{padding-top:1.4rem;max-width:1280px}
h1,h2,h3{letter-spacing:-.2px;color:var(--text);font-weight:600}
h3{display:flex;align-items:center;gap:10px}
h3::before{content:"";width:4px;height:18px;border-radius:2px;background:var(--acc);flex:none}

/* tabs: underline that slides (Streamlit's own highlight bar), panels fade in on every switch */
[data-testid="stTabs"] [role="tablist"]{gap:4px!important;border-bottom:1px solid var(--border)!important;flex-wrap:wrap}
[data-testid="stTabs"] [role="tab"]{padding:8px 14px!important;height:auto!important;color:var(--muted)!important;font-weight:500;
  background:transparent!important;border-radius:6px 6px 0 0;transition:color .2s ease,background-color .2s ease}
[data-testid="stTabs"] [role="tab"]:hover{color:var(--text)!important;background:rgba(255,255,255,.04)!important}
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{color:var(--text)!important;font-weight:600}
[data-testid="stTabs"] [role="tab"] *{color:inherit!important}
[data-baseweb="tab-highlight"]{background-color:var(--acc)!important;transition:left .3s cubic-bezier(.2,.8,.2,1),width .3s cubic-bezier(.2,.8,.2,1)!important}
[data-testid="stTabs"] [role="tabpanel"]:not([hidden]){animation:rise .35s cubic-bezier(.2,.8,.2,1) both}

/* metric cards */
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 16px;
  transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease}
[data-testid="stMetric"]:hover{border-color:#3A4452;transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.35)}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;color:var(--text)}
[data-testid="stMetricLabel"]{color:var(--muted)}

/* accent color for selected controls even if .streamlit/config.toml is not picked up (it is read from the launch folder) */
[data-testid="stSegmentedControl"] button[aria-pressed="true"],[data-testid="stSegmentedControl"] [aria-checked="true"],
[data-testid="stBaseButton-segmented_controlActive"]{background:rgba(76,139,245,.14)!important;border-color:var(--acc)!important;color:var(--text)!important}
[data-testid="stSegmentedControl"] button{border-color:var(--border)!important}

[data-baseweb="tag"]{background:rgba(76,139,245,.14)!important;border:1px solid rgba(76,139,245,.35)!important;border-radius:4px!important}
[data-baseweb="tag"] *{color:var(--text)!important}

/* buttons, inputs, expanders */
.stButton>button,[data-testid="stBaseButton-secondary"]{border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);transition:border-color .2s ease,background-color .2s ease}
.stButton>button:hover,[data-testid="stBaseButton-secondary"]:hover{border-color:var(--acc);color:var(--text)}
.stButton>button[kind="primary"],[data-testid="stBaseButton-primary"]{background:var(--acc);border:0;color:#fff;font-weight:600}
[data-testid="stExpander"]{border:1px solid var(--border);border-radius:8px;background:var(--surface)}
.stButton>button[kind="primary"]:hover,[data-testid="stBaseButton-primary"]:hover{background:#5E98F7;color:#fff}

/* modal dialogs only (Add a source). Popovers also use role="dialog" but are placed with a transform,
   so an animation on them would pin them to the top-left corner: never target bare [role="dialog"]. */
[data-testid="stDialog"] [role="dialog"],[role="dialog"][data-testid="stDialog"]{background:var(--surface)!important;border:1px solid var(--border);
  border-radius:10px;box-shadow:0 18px 48px rgba(0,0,0,.45);animation:rise .25s cubic-bezier(.2,.8,.2,1) both}
/* fields in dialogs and popovers: Streamlit draws them in the same color as the panel, so give them a well and a border */
:is([data-testid="stDialog"],[data-testid="stPopoverBody"]) :is([data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"],[data-testid="stFileUploaderDropzone"]){
  background:var(--bg)!important;border:1px solid var(--border)!important;border-radius:6px!important;transition:border-color .2s ease}
:is([data-testid="stDialog"],[data-testid="stPopoverBody"]) :is([data-baseweb="input"],[data-baseweb="textarea"]) *{background:transparent!important}
:is([data-testid="stDialog"],[data-testid="stPopoverBody"]) :is([data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"]):focus-within{border-color:var(--acc)!important}
:is([data-testid="stDialog"],[data-testid="stPopoverBody"]) [data-testid="stWidgetLabel"] p{color:#C3CAD4;font-size:13px;font-weight:500}
:is([data-testid="stDialog"],[data-testid="stPopoverBody"]) :is(input,textarea)::placeholder{color:#5F6978!important}
.formsec{font:600 11px 'Inter',sans-serif;letter-spacing:1px;text-transform:uppercase;color:var(--acc);margin:18px 0 0;
  padding-bottom:6px;border-bottom:1px solid var(--border)}
[data-testid="stDataFrame"]{border-radius:8px;overflow:hidden;border:1px solid var(--border)}
[data-testid="stChatInput"]{border-radius:8px;border:1px solid var(--border)}
[data-testid="stChatInput"]:focus-within{border-color:var(--acc)}

/* chat bubbles */
[data-testid="stChatMessage"]{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 16px}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]){border-left:3px solid var(--acc)}

/* page header */
.hdr{position:relative;overflow:hidden;border:1px solid var(--border);border-radius:10px;padding:22px 24px 20px;margin-bottom:6px;
  background:linear-gradient(135deg,#1B2230 0%,var(--surface) 60%);box-shadow:0 8px 24px rgba(0,0,0,.25);
  display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between;animation:fade .5s ease both}
.hdr::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;
  background:linear-gradient(90deg,#5B8DEF 0 20%,#3FA88A 20% 40%,#D2805E 40% 60%,#8BAE4E 60% 80%,#A3ADBD 80% 100%)}
.hdr .co{transition:color .2s ease}.hdr .co:hover{color:var(--text)}
.hdr h1{margin:8px 0 4px;font-size:28px;font-weight:700;letter-spacing:-.4px;color:var(--text);padding:0}
.hdr .sub{color:var(--muted);font-size:14.5px}
.hdr .badge{display:inline-block;padding:3px 10px;border-radius:4px;font:600 11px 'Inter',sans-serif;letter-spacing:.6px;
  border:1px solid var(--border);color:var(--muted)}
.hdr .badge.live{color:var(--good);border-color:rgba(63,178,127,.45)}
.hdr .badge.demo{color:var(--warn);border-color:rgba(212,162,76,.45)}
.hdr .cos{display:flex;flex-wrap:wrap;gap:14px}
.hdr .co{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px}
.hdr .co img{width:16px;height:16px}

/* agent pipeline */
.pipe{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 10px}
.pipe .node{padding:5px 12px;border-radius:4px;border:1px solid var(--border);color:#6B7586;font:600 11.5px 'Inter',sans-serif;letter-spacing:.8px;text-transform:uppercase}
.pipe .node.done{color:var(--good);border-color:rgba(63,178,127,.45)}
.pipe .node.active{color:var(--text);border-color:var(--acc);background:rgba(76,139,245,.12)}
.pipe .node.skip{opacity:.35;text-decoration:line-through}
.pipe .arrow{color:#4A5363;font-size:12px}

/* citation chips */
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 2px}
.chip{display:inline-flex;gap:7px;align-items:center;padding:4px 10px;border-radius:4px;font:500 12px 'JetBrains Mono',monospace;border:1px solid var(--border);background:var(--surface);color:var(--text);text-decoration:none;transition:border-color .2s ease}
.chip:hover{border-color:var(--acc)}
.chip.t1{border-color:rgba(63,178,127,.5);color:var(--good)}
.chip.t2{border-color:rgba(212,162,76,.5);color:var(--warn)}
.chip .tag{opacity:.7}

/* ticker: a static row of quotes */
.ticker{overflow-x:auto;white-space:nowrap;border-block:1px solid var(--border);padding:8px 0;margin:10px 0 14px}
.ticker-track{display:inline-block}
.tk{display:inline-block;margin:0 22px 0 0;font:500 13px 'JetBrains Mono',monospace;color:var(--muted)}
.tk b{color:var(--text);margin-right:8px}.tk img.tl{width:14px;height:14px;vertical-align:-2px;margin-right:7px}.tk.up .chg{color:var(--good)}.tk.down .chg{color:var(--bad)}
.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--good);margin-right:8px}

/* loading placeholder */
.shimmer{height:14px;border-radius:4px;margin:8px 0;background:var(--surface)}
.evrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:6px 0 14px}
.ev{display:flex;gap:14px;align-items:stretch;border:1px solid var(--border);border-left:3px solid var(--c);border-radius:8px;padding:12px 14px;background:var(--surface);
  transition:transform .2s ease,box-shadow .2s ease}
.ev:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.35)}
.evd{min-width:58px;text-align:center;border-right:1px solid var(--border);padding-right:12px;display:flex;flex-direction:column;justify-content:center}
.evd b{font:700 26px 'Inter',sans-serif;color:var(--text);line-height:1}.evd span{font:600 11px 'Inter';letter-spacing:1px;color:var(--muted);margin-top:4px}
img.tl{max-width:26px;max-height:26px}.evh img.tl{width:18px;height:18px;vertical-align:-3px;margin-right:4px}.evh strong{color:var(--text)}.evh .count{margin-left:8px;font:600 11px 'Inter';color:var(--muted);border:1px solid var(--border);border-radius:4px;padding:1px 7px}
.evx{color:#C3CAD4;margin:5px 0 8px;font-size:13.5px}
.insight{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;margin:6px 0}
.insight h4{margin:0 0 6px;font-size:12px;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}
.insight p{margin:0;color:#D0D5DC;line-height:1.55}

@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
</style>
"""


def _template():
    grid = "rgba(255,255,255,0.06)"
    axis = dict(gridcolor=grid, zerolinecolor="rgba(255,255,255,0.12)", linecolor="rgba(255,255,255,0.15)",
                tickcolor="rgba(255,255,255,0.15)", automargin=True)
    return go.layout.Template(layout=go.Layout(
        font=dict(family=FONT, color="#C3CAD4", size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=[ACCENT, GOOD, WARN, VIOLET, PINK, "#5B8DEF", "#D2805E"],
        xaxis=axis, yaxis=axis,
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)", orientation="h", y=1.08, x=0),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER, font=dict(family=FONT, color=TEXT)),
        margin=dict(l=10, r=10, t=50, b=10), title=dict(font=dict(size=16)),
        updatemenus=[dict(type="buttons", bgcolor=SURFACE, bordercolor=BORDER,
                          font=dict(color=TEXT), pad=dict(t=0, r=10))],
        sliders=[dict(bgcolor="rgba(255,255,255,0.08)", bordercolor=BORDER,
                      font=dict(color="#C3CAD4"), activebgcolor=ACCENT, tickcolor="rgba(255,255,255,0.3)")],
    ))


pio.templates["professional"] = _template()
pio.templates.default = "professional"


def apply():
    """Inject the global stylesheet. Call once per page run, before drawing anything."""
    st.markdown(CSS, unsafe_allow_html=True)


def chart(fig, height=None, key=None):
    """Show a Plotly figure with the dashboard template (Streamlit's own theme would override it)."""
    # explicit layout values beat both the template and Streamlit's own theme injection
    fig.update_layout(template="professional", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family=FONT, color="#C3CAD4", size=13))
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, theme=None, key=key,
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
