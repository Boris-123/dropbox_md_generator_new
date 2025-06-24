import streamlit as st
import dropbox
from dropbox.files import PathRoot
import os, io, time, datetime
from collections import defaultdict

"""
Dropbox Markdown Generator  –  Namespace‑aware
=============================================
Works whether the target folder is:
* a **member‑root** folder
* a **mounted team folder**
* a **pure team‑space folder** that is *not mounted*

Strategy
--------
1.  Accept any user path `/foo/bar`  
    • If it lists successfully → done.  
    • If it returns `not_found`, extract the *first segment* (`foo`).
2.  Query `sharing_list_folders()`  and  `team/team_folder/list` to map that
    first segment → **namespace_id**.
3.  Re‑run the call via `dbx.with_path_root(PathRoot.namespace_id(ns_id))`.

No UI changes – the dropdown + custom‑path boxes stay the same.
"""

# ────────────────────────── helpers ──────────────────────────

def direct_url(url: str) -> str:
    return url.replace("?dl=0", "?dl=1").replace("&dl=0", "&dl=1")


def list_path(dbx: dropbox.Dropbox, path: str):
    """Wrapper that returns entries or None on not-found."""
    try:
        return dbx.files_list_folder(path, recursive=True).entries
    except dropbox.exceptions.ApiError as e:
        if isinstance(e.error, dropbox.files.ListFolderError) and e.error.is_path() and e.error.get_path().is_not_found():
            return None  # signal not-found
        raise


def resolve_namespace(dbx_team: dropbox.DropboxTeam, folder_name: str) -> str | None:
    """Return namespace_id for a top-level team folder called `folder_name`."""
    # 1) Try shared folders (mounted or not)
    try:
        shared = dbx_team.as_admin().sharing_list_folders(limit=300).entries
        for sf in shared:
            if sf.name == folder_name and sf.path_lower:
                return str(sf.path_lower.split("ns:")[-1].split("/")[0])
    except Exception:
        pass
    # 2) Try team folders list
    try:
        tf_res = dbx_team.team_team_folder_list().team_folders
        for tf in tf_res:
            if tf.name == folder_name:
                return str(tf.team_folder_id.replace("tfid:", ""))
    except Exception:
        pass
    return None


def gather_files(dbx: dropbox.Dropbox, root: str, exts: tuple[str]):
    entries = list_path(dbx, root)
    if entries is None:  # try namespace resolution
        first_seg = root.lstrip("/").split("/")[0]
        ns = resolve_namespace(dbx_team, first_seg)
        if ns:
            dbx_ns = dbx.with_path_root(PathRoot.namespace_id(ns))
            new_root = "/" + "/".join(root.lstrip("/").split("/")[1:])  # drop the first segment inside ns
            entries = list_path(dbx_ns, new_root)
            if entries is None:
                raise FileNotFoundError(f"Folder not found even inside namespace {ns}")
            dbx = dbx_ns  # subsequent calls use ns client
        else:
            raise FileNotFoundError("Folder not found and no matching namespace")
    files = [e for e in entries if isinstance(e, dropbox.files.FileMetadata) and e.name.lower().endswith(exts)]
    return dbx, files


def markdown_from_files(dbx, files, cancel):
    grouped = defaultdict(list)
    for f in files:
        grouped[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)
    total = sum(len(v) for v in grouped.values())
    if not total:
        return []
    bar, stat = st.progress(0.), st.empty()
    t0, done, md = time.time(), 0, ["# Sources\n\n"]
    for folder in sorted(grouped):
        md.append(f"## {folder} ({len(grouped[folder])})\n\n")
        for f in grouped[folder]:
            if cancel():
                stat.warning("✘ Cancelled"); return md
            done += 1; bar.progress(done/total); stat.text(f"{done}/{total} {f.name}")
            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md.append(f"- [{os.path.splitext(f.name)[0]}]({direct_url(url)})\n")
            except Exception as e:
                md.append(f"- {f.name} (link err {e})\n")
        md.append("\n")
    bar.progress(1.0); stat.success("✔ Done"); return md

# ───────────────────────────── UI ─────────────────────────────

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Namespace‑aware")

token = st.text_input("🔐 Dropbox access token", type="password")
output = st.text_input("📝 Output .md", "Sources.md")
kind = st.radio("File type", ["PDF", "Excel"], horizontal=True)
manual = st.text_input("✏️ Folder path (e.g. /PAB One Bot)")
cancel = st.button("✘ Cancel")

if token and manual:
    try:
        dbx_team = dropbox.DropboxTeam(token)
        members = dbx_team.team_members_list().members
        sel = st.selectbox("Act as", [f"{m.profile.email}" for m in members])
        dbx = dbx_team.as_user(next(m.profile.team_member_id for m in members if m.profile.email == sel))
        st.success("Authenticated")
        ext = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_final, files = gather_files(dbx, manual, ext)
        st.info(f"{len(files)} file(s) found – ready to generate")
        if st.button("Generate Markdown"):
            md = markdown_from_files(dbx_final, files, lambda: cancel)
            if md:
                if not output.lower().endswith(".md"):
                    output += ".md"
                st.download_button("Download", io.StringIO("".join(md)).getvalue(), output, "text/markdown")
    except Exception as e:
        st.error(str(e))
