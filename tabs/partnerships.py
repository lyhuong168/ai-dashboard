"""Partnerships & supply chain tab. Owner: Lyhuong (Facts); the animated network is by Reid.

The graph reads data/partnerships.csv directly, so every row Lyhuong adds becomes a node/edge automatically.
Edges flow from the provider to the receiver; hover an edge to see its description, amount and source.
"""
import streamlit as st

from app import components
from app.data_loader import load_data


def render(data):
    st.subheader("Partnerships & supply chain")
    df = data["partnerships"]
    if df.empty:
        st.info("No partnership data yet. Fill data/partnerships.csv (each row needs a source_id).")
        with st.expander("Preview the network with SAMPLE data (illustrative only, not real)"):
            components.network(load_data(use_sample=True)["partnerships"].to_dict("records"), height=480)
        return
    kinds = sorted(df["relationship_type"].unique())
    pick = st.multiselect("Relationship types", kinds, default=kinds)
    sub = df[df["relationship_type"].isin(pick)]
    components.network(sub.to_dict("records"), height=580)
    st.caption("%d relationships · drag nodes, hover edges for sources. Arrows point from provider to receiver." % len(sub))
    with st.expander("Table with sources"):
        st.dataframe(sub)
