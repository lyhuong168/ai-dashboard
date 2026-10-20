"""Who pays for the AI features in this browser session.

1. The visitor's own OpenAI key, pasted under "AI access". Kept only in this session's memory
   (st.session_state): never written to disk, GitHub or logs, and gone when the tab closes.
2. Otherwise the team key (OPENAI_API_KEY in .env or Streamlit Secrets). If TEAM_PASSWORD is set,
   a session must enter it first, so strangers on the public link can't spend the team's credit.
3. Otherwise no key: every tab still works; the AI features say they need a key.
"""
import os

import streamlit as st

from rag import llm


def _team_key_open():
    if not os.getenv("OPENAI_API_KEY"):
        return False
    return not os.getenv("TEAM_PASSWORD") or st.session_state.get("team_unlocked", False)


def apply():
    """Pick this session's key. Call at the top of every run, before anything talks to OpenAI."""
    own = st.session_state.get("own_key")
    llm.use_key(own if own else (None if _team_key_open() else ""))


def _status():
    if st.session_state.get("own_key"):
        return "Your key", "Using your own OpenAI key. It is kept only in this browser tab and is charged to your account."
    if _team_key_open():
        return "Team key", "Using the team's OpenAI key."
    return "No key", "AI answers, the analyst chat and Regenerate need an OpenAI key. Everything else works without one."


def _key_works(key):
    try:
        from openai import OpenAI

        OpenAI(api_key=key, timeout=15).models.list()  # free call: just checks the key
        return True, ""
    except Exception as e:  # never echo the key itself
        return False, type(e).__name__


def control():
    """The 'AI access' popover in the page header."""
    label, text = _status()
    icon = ":material/key:" if label != "No key" else ":material/key_off:"
    with st.popover("AI · %s" % label, icon=icon, width="stretch"):
        st.markdown("**AI access**")
        st.caption(text)
        if st.session_state.get("own_key"):
            if st.button("Forget my key", icon=":material/delete:", width="stretch"):
                st.session_state.pop("own_key", None)
                st.rerun()
        else:
            with st.form("own_key_form", border=False):
                key = st.text_input("Your OpenAI API key", type="password", placeholder="sk-...",
                                    help="Get one at platform.openai.com/api-keys. Usage is billed to your OpenAI account.")
                if st.form_submit_button("Use my key", type="primary", width="stretch"):
                    key = key.strip()
                    ok, why = _key_works(key) if key.startswith("sk-") else (False, "it should start with sk-")
                    if ok:
                        st.session_state["own_key"] = key
                        st.rerun()
                    st.error("That key did not work (%s)." % why)
        if os.getenv("TEAM_PASSWORD") and os.getenv("OPENAI_API_KEY") and not st.session_state.get("own_key"):
            if st.session_state.get("team_unlocked"):
                if st.button("Lock team key", icon=":material/lock:", width="stretch"):
                    st.session_state.pop("team_unlocked", None)
                    st.rerun()
            else:
                with st.form("team_form", border=False):
                    pw = st.text_input("Team password", type="password", help="Team members can use the shared key instead.")
                    if st.form_submit_button("Unlock team key", width="stretch"):
                        if pw == os.getenv("TEAM_PASSWORD"):
                            st.session_state["team_unlocked"] = True
                            st.rerun()
                        st.error("Wrong password.")
