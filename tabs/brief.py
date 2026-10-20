"""Market Brief tab. Owner: Reid. A sourced synopsis: what is scheduled, what the companies guided, what moved, what was announced.
Every bullet carries citation chips; green = tier 1 (primary), amber = tier 2 (press). Nothing here is a forecast."""
import html
from datetime import date

import streamlit as st

from agents.brief import build_brief, load_brief
from app.theme import COMPANY_COLORS, GOOD, MUTED, TICKER_COMPANY, WARN, logo_uri
from rag.llm import have_key

NAMES = {"Google": "Alphabet / Google"}


def _chips(cites, evidence):
    out, seen = [], set()
    for c in cites:
        e = evidence.get(c, {})
        tier = e.get("tier", "1")
        if e.get("kind") == "news":
            label, url, tip = e.get("publisher", "press"), e.get("url", ""), e.get("title", "")
        else:
            label, url, tip = (e.get("source_id", "").split(",")[0] or {"week_ahead": "calendar"}.get(e.get("kind"), c)), "", e.get("text", "")
        if (label, url) in seen:
            continue  # several facts can share one source; show each source once
        seen.add((label, url))
        tag = "a" if url else "span"
        href = ' href="%s" target="_blank" rel="noopener"' % html.escape(url) if url else ""
        out.append('<%s class="chip t%s"%s title="%s"><span class="tag">tier %s</span>%s</%s>' % (
            tag, tier, href, html.escape(tip[:160]), tier, html.escape(label[:28]), tag))
    return '<div class="chips">%s</div>' % "".join(out)


def _bullets(bullets, evidence):
    if not bullets:
        return '<p style="color:%s">No evidence-checked bullets for this section.</p>' % MUTED
    items = "".join("<li style='margin:0 0 10px'>%s%s</li>" % (html.escape(b["text"]), _chips(b["cites"], evidence)) for b in bullets)
    return "<ul style='padding-left:18px;margin:8px 0 0'>%s</ul>" % items


def _merge_events(events):
    """One card per company, date and type: a model's input and output price changes share a card."""
    merged = {}
    for e in events:
        key = (e["company"], e["date"], e["type"])
        if key in merged:
            merged[key]["what"] += "; " + e["what"].split(": ", 1)[-1]
        else:
            merged[key] = dict(e)
    return sorted(merged.values(), key=lambda e: e["date"])


def _event_card(e):
    d = date.fromisoformat(e["date"])
    co = e["company"]
    logo = logo_uri(co)
    conf = e["status"] == "confirmed"
    badge = '<span class="chip t1">confirmed by the company</span>' if conf else '<span class="chip t2">press-reported, not confirmed by the company</span>'
    days = e["days_until"]
    when = "today" if days == 0 else "tomorrow" if days == 1 else "in %d days" % days
    return ('<div class="ev" style="--c:%s"><div class="evd"><b>%d</b><span>%s</span></div><div class="evt"><div class="evh">'
            '<img class="tl" src="%s"> <strong>%s</strong> <span class="count">%s</span></div><div class="evx">%s</div>%s</div></div>') % (
        COMPANY_COLORS.get(co, "#00E5FF"), d.day, d.strftime("%b").upper(), logo, html.escape(NAMES.get(co, co)), when,
        html.escape(e["what"]), badge)


def _guidance_card(rows):
    """Latest guided quarter + the track record, for companies that publish numeric guidance."""
    out = []
    for co in sorted({r["company"] for r in rows}):
        rs = [r for r in rows if r["company"] == co]
        latest = rs[-1]
        scored = [r for r in rs if "actual_musd" in r]
        lo, hi = latest["range_musd"]
        chips = "".join('<span class="chip %s" title="guided midpoint $%.1fB, reported $%.1fB">%s %+.1f%% vs midpoint</span>' % (
            "t1" if r["result"].startswith("above") else "t2", r["guided_mid_musd"] / 1000, r["actual_musd"] / 1000, r["period"], r["vs_midpoint_pct"]) for r in scored)
        out.append('<div class="insight"><h4>%s company guidance (its own words, not our forecast)</h4><p><img class="tl" src="%s" style="width:16px;vertical-align:-3px;margin-right:6px">'
                   '<b>%s</b> guided <b>%s</b> revenue to <b>$%.1fB</b> (range $%.1fB to $%.1fB), issued %s.</p><p style="margin-top:8px;color:%s">'
                   'Track record against its own guidance (reported vs midpoint):</p><div class="chips">%s</div></div>' % (
                       html.escape(co), logo_uri(co), html.escape(co), latest["period"], latest["guided_mid_musd"] / 1000, lo / 1000, hi / 1000,
                       latest["issued"], MUTED, chips or "<span class='chip'>no completed quarters yet</span>"))
    return "".join(out)


def _price_chip(brief, co):
    tick = next((t for t, c in TICKER_COMPANY.items() if c == co), None)
    m = next((x for x in brief.get("moves", []) if x["ticker"] == tick), None)
    if not m or m["chg_1d_pct"] is None:
        return ""
    up = m["chg_1d_pct"] >= 0
    return '<span class="chip" style="color:%s;border-color:%s">%s $%.2f &nbsp;%s%.2f%%</span>' % (
        GOOD if up else "#FF6B8A", GOOD if up else "#FF6B8A", tick, m["close"], "▲" if up else "▼", abs(m["chg_1d_pct"]))


def render(data, sample):
    st.subheader("Market Brief")
    brief = load_brief(sample)
    c1, c2 = st.columns([5, 1])
    if c2.button("Regenerate", key="brief_regen", disabled=not have_key(),
                 help="Rebuild the synopsis from the latest evidence (about 3 cents)." if have_key() else "Needs an OpenAI key: add one under AI access at the top."):
        with st.spinner("Checking every claim against its evidence..."):
            brief = build_brief(sample=sample)
        st.rerun()
    if brief is None:
        st.info("No brief yet. It is built during `python refresh.py`, or press Regenerate.")
        return
    ev = brief["evidence"]
    c1.caption(("Generated %s · evidence as of %s · %s · $%.3f · %d claims removed by the checker" % (
        brief["generated_at"], brief["as_of"], "AI-written, every number checked against its citation" if brief["llm"] else "facts only (no API key)",
        brief["cost_usd"], len(brief["dropped"]))).replace("$", "\\$"))
    st.markdown('<div class="insight" style="border-color:rgba(255,200,87,.45)"><h4 style="color:#FFC857">No predictions</h4><p>This brief only restates dated events, '
                'company-issued guidance and reported facts, each with its source. It does not forecast results.</p></div>', unsafe_allow_html=True)

    st.markdown("##### The week ahead")
    wk = brief["week_ahead"]
    if wk and "note" in wk[0]:
        st.markdown('<div class="insight"><h4>Nothing scheduled</h4><p>%s</p></div>' % html.escape(wk[0]["note"]), unsafe_allow_html=True)
    nxt = _merge_events([e for e in brief["next_events"] if "what" in e and e["type"] in ("earnings", "price_change", "promo_end")])
    if nxt:
        st.markdown("<div class='evrow'>%s</div>" % "".join(_event_card(e) for e in nxt[:6]), unsafe_allow_html=True)
    if brief["guidance"]:
        st.markdown(_guidance_card(brief["guidance"]), unsafe_allow_html=True)

    if brief["overall"]:
        st.markdown("##### Across the five")
        st.markdown('<div class="insight">%s</div>' % _bullets(brief["overall"], ev), unsafe_allow_html=True)

    st.markdown("##### Company synopses")
    cols = st.columns(2)
    for i, (co, c) in enumerate(brief["companies"].items()):
        with cols[i % 2]:
            st.markdown('<div class="insight" style="border-color:%s55"><h4 style="color:%s"><img class="tl" src="%s" style="width:18px;height:18px;vertical-align:-3px;margin-right:8px">%s</h4>'
                        '<div style="margin-bottom:4px;color:%s">%s</div>%s%s</div>' % (
                            COMPANY_COLORS[co], COMPANY_COLORS[co], logo_uri(co), html.escape(NAMES.get(co, co).upper()), MUTED,
                            html.escape(c["headline"]), _price_chip(brief, co), _bullets(c["bullets"], ev)), unsafe_allow_html=True)
            heads = brief["headlines"].get(co, [])
            if heads:
                with st.expander("Latest headlines (%d)" % len(heads)):
                    for h in heads:
                        st.markdown("%s `tier %s` [%s](%s) · %s · %s" % (h["date"], h["tier"], h["title"].replace("[", "(").replace("]", ")"), h["url"], h["publisher"], h["source_id"]))
    if brief["dropped"]:
        with st.expander("Claims the checker removed (%d)" % len(brief["dropped"])):
            st.caption("Shown for transparency: each was removed because a citation was missing or a number was not in the cited evidence.")
            for d in brief["dropped"]:
                st.markdown("- **%s**: %s _(because: %s)_" % (d["where"], d["text"], d["why"]))
