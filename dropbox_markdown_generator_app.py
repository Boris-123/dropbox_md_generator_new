import streamlit as st
import dropbox
import os, io, time, datetime
from collections import defaultdict

# Optional import – older Dropbox SDKs (<11.9) don’t ship PathRoot
try:
    from dropbox.files import PathRoot  # type: ignore
except ImportError:  # pragma: no cover – fallback for old SDK
    PathRoot = None  # sentinel so we can branch later

"""
Dropbox Markdown Generator – **SDK-version tolerant**
----------------------------------------------------
* Works with *any* dropbox-python version (PathRoot present or not).
* Resolves team-space namespaces when a folder is not found in member root.
* UI unchanged: user types `/PAB One Bot` or deeper path.
"""

# ───────────────────────── helpers ──────────────────────────

def to_dl(url: str) -> str:
    return url.replace("&dl=0", "&dl=1")


def list_entries(dbx: dropbox.Dropbox, path: str):
    try:
        return dbx.files_list_folder(path, recursive=True).entries
    except dropbox.exceptions.ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            return None
        raise


def ns_client(dbx: dropbox.Dropbox, ns_id: str):
    """Return a client rooted at namespace *ns_id* regardless of SDK version."""
    if PathRoot:  # modern SDK
        return dbx.with_path_root(PathRoot.namespace_id(ns_id))
    # legacy fallback – inject header manually
    hdr = {"Dropbox-API-Path-Root": f'{{".tag":"namespace_id","namespace_id":"{ns_id}"}}'}
    return dropbox.Dropbox(dbx._oauth2_access_token, headers=hdr)


def get_ns_for_name(team: dropbox.DropboxTeam, name: str):
    # shared folders API
    try:
        for sf in team.as_admin().sharing_list_folders(limit=300).entries:
            if sf.name == name and sf.path_lower:
                return sf.path_lower.split("ns:")[-1].split("/")[0]
    except Exception:
        pass
    # team folders API
    try:
        for tf in team.team_team_folder_list().team_folders:
            if tf.name == name:
                return tf.team_folder_id.replace("tfid:", "")
    except Exception:
        pass
    return None


def fetch_files(dbx, team, full_path: str, exts):
    entries = list_entries(dbx, full_path)
    if entries is None:
        first = full_path.lstrip("/").split("/")[0]
        ns_id = get_ns_for_name(team, first)
        if not ns_id:
            raise FileNotFoundError("Folder not found and no namespace matched")
        dbx = ns_client(dbx, ns_id)
        tail = "/".join(full_path.lstrip("/").split("/")[1:])
        entries = list_entries(dbx, "/"+tail)  # may be empty list, but not None
    files = [e for e in entries if isinstance(e, dropbox.files.FileMetadata) and e.name.lower().endswith(exts)]
    return dbx, files


def build_md(dbx, files, cancel_fn):
    groups = defaultdict(list)
    for f in files:
        groups[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)
    total = len(files)
    if not total:
        return []
    bar, stat = st.progress(0.), st.empty()
    start, done, out = time.time(), 0, ["# Sources\n\n"]
    for folder in sorted(groups):
        out.append(f"## {folder} ({len(groups[folder])})\n\n")
        for f in groups[folder]:
            if cancel_fn():
                stat.warning("✘ Cancelled"); return out
            done += 1; bar.progress(done/total)
            elapsed = time.time()-start
            stat.text(f"{done}/{total} – {f.name} – ETA {datetime.timedelta(seconds=int(elapsed/done*(total-done)))}")
            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                out.append(f"- [{os.path.splitext(f.name)[0]}]({to_dl(url)})\n")
            except Exception as e:
                out.append(f"- {f.name} (link err {e})\n")
        out.append("\n")
    bar.progress(1.0); return out

# ───────────────────────────── UI ─────────────────────────────

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – SDK-Version Safe")

token = st.text_input("🔐 Access token", type="password")
path_in = st.text_input("✏️ Folder path (e.g. /PAB One Bot)")
kind = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename = st.text_input("Output .md", "Sources.md")
cancel_btn = st.button("✘ Cancel")

if token and path_in:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        user_email = st.selectbox("Act as", [m.profile.email for m in members])
        dbx_user = team.as_user(next(m.profile.team_member_id for m in members if m.profile.email == user_email))
        st.success("Authenticated ✔")
        exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_resolved, files = fetch_files(dbx_user, team, path_in, exts)
        st.info(f"{len(files)} file(s) matched – Preview OK")
        if st.button("Generate Markdown"):
            md = build_md(dbx_resolved, files, lambda: cancel_btn)
            if md:
                if not filename.lower().endswith(".md"):
                    filename += ".md"
                st.download_button("⬇ Download MD", io.StringIO("".join(md)).getvalue(), filename, "text/markdown")
    except Exception as err:
        st.error(str(err))
