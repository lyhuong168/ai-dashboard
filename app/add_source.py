"""Add a source from inside the dashboard: the document goes to data/raw/<Company>/ and a row to
data/sources/sources_U.csv (U = added through the app).

Streamlit Cloud wipes its disk on every restart, so there both files are committed to GitHub
(Secrets: GITHUB_SAVE_TOKEN, GITHUB_REPO, ADD_SOURCE_PASSWORD) and .github/workflows/reindex.yml
rebuilds the search index. Run locally, it writes into data/ and you push with GitHub Desktop.
"""
import base64
import csv
import io
import os
from datetime import date
from urllib.parse import urlparse

import requests
import streamlit as st

import contract as C
from rag import config

SOURCES_FILE = "data/sources/sources_U.csv"
PREFIX = "U"
COLS = [c for c, _, _ in C.SOURCES_SCHEMA]
FILE_TYPES = ["txt", "md", "htm", "html", "pdf"]
MAX_MB = 10
ON_CLOUD = str(config.ROOT).startswith("/mount/src")  # where Streamlit Community Cloud checks out the repo


def _github_ready():
    return bool(os.getenv("GITHUB_SAVE_TOKEN") and os.getenv("GITHUB_REPO"))


class _GitHub:
    """Just enough of the GitHub REST API to read one file and commit several files in a single commit."""

    def __init__(self):
        self.base = "https://api.github.com/repos/%s" % os.getenv("GITHUB_REPO").strip()
        self.branch = os.getenv("GITHUB_BRANCH", "main")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "Bearer " + os.getenv("GITHUB_SAVE_TOKEN").strip(),
                               "Accept": "application/vnd.github+json"})

    def _call(self, method, path, **kw):
        r = self.s.request(method, self.base + path, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def read(self, path):
        r = self.s.get(self.base + "/contents/" + path, params={"ref": self.branch}, timeout=30)
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        return base64.b64decode(r.json()["content"]).decode("utf-8-sig")

    def commit(self, files, message):
        head = self._call("GET", "/git/ref/heads/" + self.branch)["object"]["sha"]
        tree = self._call("GET", "/git/commits/" + head)["tree"]["sha"]
        items = [{"path": p, "mode": "100644", "type": "blob",
                  "sha": self._call("POST", "/git/blobs", json={"content": base64.b64encode(b).decode(), "encoding": "base64"})["sha"]}
                 for p, b in files.items()]
        new_tree = self._call("POST", "/git/trees", json={"base_tree": tree, "tree": items})["sha"]
        sha = self._call("POST", "/git/commits", json={"message": message, "tree": new_tree, "parents": [head]})["sha"]
        self._call("PATCH", "/git/refs/heads/" + self.branch, json={"sha": sha})


def _next_id(rows):
    nums = [int(r["source_id"].split("-")[1]) for r in rows if r.get("source_id", "").startswith(PREFIX + "-")]
    return "%s-%03d" % (PREFIX, max(nums, default=0) + 1)


def _with_row(csv_text, row):
    rows = list(csv.DictReader(io.StringIO(csv_text))) if csv_text.strip() else []
    sid = _next_id(rows)
    rows.append({**row, "source_id": sid})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLS)
    w.writeheader()
    w.writerows({c: r.get(c, "") for c in COLS} for r in rows)
    return sid, out.getvalue()


def _problems(f, existing_urls):
    out = []
    for k, label in (("title", "Title"), ("url", "Link"), ("publisher", "Publisher")):
        if not f[k].strip():
            out.append("%s is required" % label)
    u = urlparse(f["url"].strip())
    if f["url"].strip() and not (u.scheme == "https" and u.netloc):
        out.append("Link must be a full https:// address")
    if f["url"].strip() in existing_urls:
        out.append("This link is already in the source registry")
    if f["doc_type"] in C.NEWS_ONLY_TIER2 and f["tier"] == "1":
        out.append("%s can only be tier 2" % f["doc_type"])
    if f["upload"] is None and not f["pasted"].strip():
        out.append("Attach the document or paste its text (no source, no row)")
    if f["upload"] is not None and f["upload"].size > MAX_MB * 1024 * 1024:
        out.append("File is larger than %d MB" % MAX_MB)
    return out


def _save(f):
    """Write the document + sources row. Returns (source_id, where)."""
    if f["upload"] is not None:
        ext, body = f["upload"].name.rsplit(".", 1)[-1].lower(), f["upload"].getvalue()
    else:
        ext, body = "txt", f["pasted"].strip().encode("utf-8")
    row = {"company": f["company"], "title": f["title"].strip(), "url": f["url"].strip(), "publisher": f["publisher"].strip(),
           "doc_type": f["doc_type"], "tier": f["tier"], "published_date": f["published"].isoformat(),
           "retrieved_date": date.today().isoformat()}

    gh = _GitHub() if _github_ready() else None
    path = config.ROOT / SOURCES_FILE
    current = gh.read(SOURCES_FILE) if gh else path.read_text(encoding="utf-8-sig") if path.exists() else ""
    rows = list(csv.DictReader(io.StringIO(current))) if current.strip() else []
    row["local_path"] = "raw/%s/%s.%s" % (f["company"], _next_id(rows), ext)  # file named after its source_id
    sid, text = _with_row(current, row)

    if gh:
        gh.commit({"data/" + row["local_path"]: body, SOURCES_FILE: text.encode("utf-8")},
                  "Add source %s: %s" % (sid, row["title"][:60]))
        return sid, "github"
    doc = config.ROOT / "data" / row["local_path"]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_bytes(body)
    path.write_text(text, encoding="utf-8", newline="")
    return sid, "local"


def _section(label):
    st.markdown('<div class="formsec">%s</div>' % label, unsafe_allow_html=True)


@st.dialog("Add a source", width="medium")
def _dialog(existing_urls):
    password = os.getenv("ADD_SOURCE_PASSWORD")
    if ON_CLOUD and not (_github_ready() and password):
        st.info("To save sources from the online app, add `GITHUB_SAVE_TOKEN`, `GITHUB_REPO` and `ADD_SOURCE_PASSWORD` "
                "in the app's Settings → Secrets. This server forgets local files on restart, so sources are saved to GitHub.")
        return
    st.caption("Only add documents you opened yourself. It becomes searchable after the next index rebuild.")
    with st.form("add_source", border=False):  # not cleared on submit, so a typo doesn't wipe the form
        _section("1 · About the source")
        c1, c2, c3 = st.columns(3)
        f = {"company": c1.selectbox("Company", C.COMPANIES),
             "doc_type": c2.selectbox("Document type", C.DOC_TYPES),
             "tier": c3.selectbox("Trust tier", ["1", "2"], format_func={"1": "1 · Primary", "2": "2 · Press / market"}.get,
                                  help="1 = the company's own document (filing, release, pricing page). 2 = press, reports or market data.")}
        f["title"] = st.text_input("Title", placeholder="NVIDIA Announces Financial Results for Third Quarter")
        f["url"] = st.text_input("Link", placeholder="https://")
        c4, c5 = st.columns([2, 1])
        f["publisher"] = c4.text_input("Publisher", placeholder="NVIDIA Newsroom")
        f["published"] = c5.date_input("Published on", max_value=date.today(), format="YYYY-MM-DD")

        _section("2 · The document")
        f["upload"] = st.file_uploader("Upload a file (up to %d MB)" % MAX_MB, type=FILE_TYPES)
        f["pasted"] = st.text_area("Or paste the text", height=110, placeholder="Paste the article or page text here")

        typed = st.text_input("Password", type="password") if password else None
        st.write("")
        submitted = st.form_submit_button("Save source", type="primary", icon=":material/save:", width="stretch")
    if not submitted:
        return
    if password and typed != password:
        st.error("Wrong password.")
        return
    problems = _problems(f, existing_urls)
    if problems:
        st.error("Not saved:\n\n" + "\n".join("- " + p for p in problems))
        return
    try:
        with st.spinner("Saving…"):
            sid, where = _save(f)
    except requests.HTTPError as e:
        st.error("GitHub refused the save (%s). Check that GITHUB_SAVE_TOKEN has Contents: read and write on %s."
                 % (e.response.status_code, os.getenv("GITHUB_REPO")))
        return
    except requests.RequestException as e:
        st.error("Could not reach GitHub (%s). Nothing was saved; try again." % type(e).__name__)
        return
    st.cache_data.clear()
    if where == "github":
        msg = ("Added **%s**. It is committed to GitHub; the search index rebuilds there in a few minutes, "
               "then the app reloads with it." % sid)
    else:
        msg = "Added **%s** to `data/`. Run `python refresh.py` to add it to the search index, then commit and push." % sid
    st.session_state["source_added"] = msg
    st.rerun()  # closes the dialog; notice() shows the message on the page


def button(existing_urls):
    """The 'Add source' button; opens the form in a dialog."""
    if st.button("Add source", type="primary", icon=":material/add:", width="stretch"):
        _dialog(existing_urls)


def notice():
    """Confirmation for the source saved on the previous run, if any."""
    msg = st.session_state.pop("source_added", None)
    if msg:
        st.success(msg, icon=":material/check_circle:")
