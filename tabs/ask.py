"""Ask the Analyst tab. Owner: Reid. A live chat: the agent pipeline lights up as each specialist
finishes, the answer streams in token by token, and every claim comes with clickable source chips."""
import time

import pandas as pd
import streamlit as st

from app import components
from rag import config
from rag.llm import TRACKER, have_key

SUGGESTIONS = [
    "What results should I expect from these companies next week?",
    "What drove Nvidia's revenue growth last quarter?",
    "Compare revenue growth across Google, Nvidia and Apple.",
    "Can I trust these revenue numbers? Verify them.",
]
SPECIALISTS = ["rag", "analyst", "verify"]
USER_AVATAR, BOT_AVATAR = ":material/person:", ":material/auto_awesome:"


def _md(text):
    """Escape $ so dollar amounts are not rendered as LaTeX math."""
    return text.replace("$", "\\$")


def _states(route=None, done=(), active=None):
    s = {"supervisor": "pending", "rag": "pending", "analyst": "pending", "verify": "pending", "write": "pending"}
    if route is not None:
        for k in SPECIALISTS:
            s[k] = "pending" if k in route else "skip"
    for k in done:
        s[k] = "done"
    if active:
        s[active] = "active"
    return s


def _next_active(states):
    for k in SPECIALISTS + ["write"]:
        if states[k] == "pending":
            return k
    return None


def _details(msg):
    """Chips, warnings and the expandable evidence under an answer."""
    if msg.get("citations"):
        st.markdown(components.chips_html(msg["citations"]), unsafe_allow_html=True)
    for w in msg.get("warnings", []):
        st.warning(w)
    if msg.get("analysis"):
        with st.expander("Computed from the data tables"):
            for name, rows in msg["analysis"].items():
                st.markdown("**%s**" % name)
                st.dataframe(pd.DataFrame(rows))
    if msg.get("verification"):
        with st.expander("Verifier findings"):
            st.write(msg["verification"]["summary"])
            st.dataframe(pd.DataFrame(msg["verification"]["findings"]))
    if msg.get("citations"):
        with st.expander("Passages behind the citations"):
            for c in msg["citations"]:
                st.markdown("**[%s]** %s · `%s` · tier %s · %s" % (c["tag"], c["title"], c["source_id"], c["tier"], c["published_date"]))
                st.caption(c["text"][:500] + ("..." if len(c["text"]) > 500 else ""))
    if msg.get("trace"):
        with st.expander("Agent trace"):
            for line in msg["trace"]:
                st.text(line)


def _answer_live(question, sample):
    """Run the agents with a live pipeline + streaming text. Returns the message dict to store."""
    from agents.graph import ask_stream

    before = TRACKER.total
    pipe, body = st.empty(), st.empty()
    states = _states(active="supervisor")
    pipe.markdown(components.pipeline_html(states), unsafe_allow_html=True)
    body.markdown('<div class="shimmer" style="width:92%"></div><div class="shimmer" style="width:76%"></div>'
                  '<div class="shimmer" style="width:58%"></div>', unsafe_allow_html=True)
    text, final = "", None
    try:
        for ev in ask_stream(question, sample=sample):
            if ev["type"] == "step":
                node, route = ev["node"], ev["state"].get("route")
                states = _states(route, done=[k for k, v in states.items() if v == "done"] + [node])
                states[node] = "done"
                nxt = _next_active(states)
                if nxt:
                    states[nxt] = "active"
                pipe.markdown(components.pipeline_html(states), unsafe_allow_html=True)
                time.sleep(0.12)  # lets the eye follow the hand-off
            elif ev["type"] == "write_start":
                states["write"] = "active"
                pipe.markdown(components.pipeline_html(states), unsafe_allow_html=True)
            elif ev["type"] == "token":
                text += ev["text"]
                body.markdown(_md(text) + " ▌")
            elif ev["type"] == "final":
                final = ev["state"]
    except Exception as e:  # budget cap, network, API error: show it, keep the app alive
        pipe.empty()
        body.empty()
        st.error("The agents hit a problem: %s: %s" % (type(e).__name__, e))
        return None
    states["write"] = "done"
    pipe.markdown(components.pipeline_html(states), unsafe_allow_html=True)
    body.markdown(_md(final["answer"]))
    msg = {"role": "assistant", "content": final["answer"], "citations": final.get("citations", []),
           "warnings": final.get("warnings", []), "analysis": final.get("analysis"), "verification": final.get("verification"),
           "trace": final.get("trace", []), "states": states,
           "meta": "route: supervisor → %s → writer · cost $%.4f" % (" → ".join(final.get("route") or ["-"]), TRACKER.total - before)}
    _details(msg)
    st.caption(msg["meta"])
    return msg


def render(data, sample):
    from rag.cli import build_index
    from rag.store import VectorStore

    st.subheader("Ask the Analyst")
    store = VectorStore.load(config.store_dir(sample))
    if store is None:
        st.info("No search index yet.")
        if st.button("Build index now"):
            with st.spinner("Chunking and embedding documents..."):
                build_index(sample)
            st.rerun()
        return

    st.caption("Index: %d passages · embedder `%s` · built %s · answers by %s" % (
        len(store.chunks), store.embedder_name, store.built_at,
        "GPT with retrieval + tools" if have_key() else "offline mode (no API key: extractive answers)"))
    if store.embedder_name != "hashing-offline" and not have_key():
        st.info("The chat needs an OpenAI key to embed your question (the index was built with the same model). Paste your own key under "
                "**AI access** at the top of the page (it stays in this browser tab only), or unlock the team key. Every other tab works without a key.")
        return
    if store.embedder_name == "hashing-offline" and not sample:
        st.warning("This index uses the free offline embedder. Rebuild with an API key for real semantic search.")

    history = st.session_state.setdefault("chat", [])
    top = st.columns([6, 1])
    if history and top[1].button("Clear", key="clear_chat"):
        st.session_state["chat"] = []
        st.rerun()
    if not history:
        st.markdown("<div style='color:#8FA3C0;margin:2px 0 8px'>Try one of these, or ask your own:</div>", unsafe_allow_html=True)
        cols = st.columns(len(SUGGESTIONS))
        for i, (col, s) in enumerate(zip(cols, SUGGESTIONS)):
            if col.button(s, key="sg%d" % i, use_container_width=True):
                st.session_state["pending"] = s
                st.rerun()

    area = st.container()  # messages render here, ABOVE the input
    q = st.chat_input("Ask about revenue, growth, risks, or whether the numbers can be trusted…") or st.session_state.pop("pending", None)
    with area:
        for m in history:
            with st.chat_message(m["role"], avatar=USER_AVATAR if m["role"] == "user" else BOT_AVATAR):
                if m["role"] == "assistant" and m.get("states"):
                    st.markdown(components.pipeline_html(m["states"]), unsafe_allow_html=True)
                st.markdown(_md(m["content"]))
                if m["role"] == "assistant":
                    _details(m)
                    st.caption(m.get("meta", ""))
        if q:
            history.append({"role": "user", "content": q})
            with st.chat_message("user", avatar=USER_AVATAR):
                st.markdown(_md(q))
            with st.chat_message("assistant", avatar=BOT_AVATAR):
                msg = _answer_live(q, sample)
            if msg:
                history.append(msg)
