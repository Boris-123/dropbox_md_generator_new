import streamlit as st
import dropbox
import os, io, time, datetime
from collections import defaultdict

"""
**Key fix** – Dropbox root must be passed as an **empty string** (``""``), *never* ``"/"``.
We now:
1. List *mounted* root folders with path="" and ``include_mounted_folders=True``
2. Allow manual entry (auto‐strip redundant spaces)  
3. Generate Markdown links for PDF/Excel
"""

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def force_dl(url: str) -> str:
    return url.replace("?dl=0", "?dl=1").replace("&dl=0", "&dl=1")


def gather(dbx: dropbox.Dropbox, root: str, exts: tuple[str]) -> list:
    res = dbx.files_list_folder(root, recursive=True)
    files = list(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        files.extend(res.entries)
    return [f for f in files if isinstance(f, dropbox.files.FileMetadata) and f.name.lower().endswith(exts)]


def group(files):
    g = defaultdict(list)
    for f in files:
        folder = os.path.dirname(f.path_display).lstrip("/") or "Root"
        g[folder].append(f)
    return g


def make_md(dbx, files, cancel):
    grouped = group(files)
    total = sum(len(v) for v in grouped.values())
    if not total:
        return []
    bar, stat, eta = st.progress(0.), st.empty(), st.empty()
    t0, done = time.time(), 0
    md = ["# Document Sources\n\n"]
    for folder in sorted(grouped):
        md.append(f"## {folder} ({len(grouped[folder])})\n\n")
        for f in grouped[folder]:
            if cancel():
                stat.warning("✘ Cancelled"); return md
            done += 1; bar.progress(done/total)
            stat.text(f"[{done}/{total}] {f.name}")
            eta.text(f"⌛ ETA {datetime.timedelta(seconds=int((time.time()-t0)/done*(total-done)))}")
            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md.append(f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
            except Exception as e:
                md.append(f"- {f.name} (link error {e})\n")
        md.append("\n")
    bar.progress(1.0); stat.success("✔ Done"); eta.empty(); return md

# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown Link Generator – Team Edition")

token = st.text_input("🔐 Dropbox Access Token", type="password")
output_name = st.text_input("📝 Output file", "Sources.md")
filter_kw = st.text_input("🔍 Filename filter (optional)")
kind = st.radio("📄 File type", ["PDF", "Excel"], horizontal=True)

cancel = st.button("✘ Cancel")

if token:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        member_map = {f"{m.profile.name.display_name} ({m.profile.email})": m.profile.team_member_id for m in members}
        sel_member = st.selectbox("👤 Act as", list(member_map))
        dbx = team.as_user(member_map[sel_member])
        st.success("Authenticated ✔")

        @st.cache_data(show_spinner=False)
        def root_folders():
            entries = dbx.files_list_folder("", include_mounted_folders=True).entries
            return [e.path_display or "/" for e in entries if isinstance(e, dropbox.files.FolderMetadata)]

        roots = root_folders()
        root_choice = st.selectbox("📂 Mounted folders", roots)
        manual = st.text_input("✏️ Custom folder path", placeholder="/PAB One Bot/Forms")
        manual = manual.replace(" /", "/").replace("/ ", "/").strip()
        path = manual if manual else root_choice
        if path == "/":
            path = ""  # API root

        if st.button("🔍 Preview count") and path:
            exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
            pre = gather(dbx, path, exts)
            st.info(f"Found {len(pre)} {kind} file(s)")

        if st.button("➤ Generate Markdown") and path:
            exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
            files = gather(dbx, path, exts)
            if filter_kw:
                files = [f for f in files if filter_kw.lower() in f.name.lower()]
            md = make_md(dbx, files, lambda: cancel)
            if md:
                if not output_name.lower().endswith(".md"):
                    output_name += ".md"
                st.download_button("⬇ Download MD", io.StringIO("".join(md)).getvalue(), output_name, "text/markdown")
    except Exception as err:
        st.error(f"💥 {err}")
