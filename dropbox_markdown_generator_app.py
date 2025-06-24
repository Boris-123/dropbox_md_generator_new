import streamlit as st
import dropbox
import os, io, time, datetime
from collections import defaultdict

"""
Drop box Markdown Generator – final fix
--------------------------------------
• Root folder passed as **empty string** only
• All paths fed to API have **no leading slash**
• Dropdown shows mount‑points w/out slash; manual box still accepts either
• Preview + generation now succeed for `/PAB One Bot`
"""

# ────────────────────────── helpers ──────────────────────────

def force_dl(url):
    return url.replace("?dl=0", "?dl=1").replace("&dl=0", "&dl=1")

def gather(dbx, root, exts):
    res = dbx.files_list_folder(root, recursive=True)
    items = list(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        items.extend(res.entries)
    return [f for f in items if isinstance(f, dropbox.files.FileMetadata) and f.name.lower().endswith(exts)]

def group(files):
    g = defaultdict(list)
    for f in files:
        g[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)
    return g

def make_md(dbx, files, cancel):
    grouped, total = group(files), len(files)
    if not total:
        return []
    bar, stat, eta = st.progress(0.), st.empty(), st.empty()
    done, t0, md = 0, time.time(), ["# Document Sources\n\n"]
    for folder in sorted(grouped):
        md.append(f"## {folder} ({len(grouped[folder])})\n\n")
        for f in grouped[folder]:
            if cancel():
                stat.warning("✘ Cancelled"); return md
            done += 1; bar.progress(done/total)
            elapsed = time.time()-t0
            eta.text(f"⌛ ETA {datetime.timedelta(seconds=int(elapsed/done*(total-done)))}")
            stat.text(f"[{done}/{total}] {f.name}")
            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md.append(f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
            except Exception as e:
                md.append(f"- {f.name} (link error {e})\n")
        md.append("\n")
    bar.progress(1.0); stat.success("✔ Done"); eta.empty(); return md

# ───────────────────────────── UI ─────────────────────────────

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Edition (final)")

token = st.text_input("🔐 Dropbox Access Token", type="password")
outfile = st.text_input("📝 Output .md", "Sources.md")
flt = st.text_input("🔍 Filename filter (optional)")
kind = st.radio("📄 File type", ["PDF", "Excel"], horizontal=True)

cancel_btn = st.button("✘ Cancel")

if token:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        opts = {f"{m.profile.name.display_name} ({m.profile.email})": m.profile.team_member_id for m in members}
        sel = st.selectbox("👤 Act as", list(opts))
        dbx = team.as_user(opts[sel])
        st.success("Authenticated ✔")

        @st.cache_data(show_spinner=False)
        def mounts():
            root_list = dbx.files_list_folder("", include_mounted_folders=True).entries
            return sorted((e.path_display or "/").lstrip("/") for e in root_list if isinstance(e, dropbox.files.FolderMetadata))

        root_pick = st.selectbox("📂 Mounted folders", mounts())
        manual = st.text_input("✏️ Custom path", placeholder="PAB One Bot")
        path = (manual.strip() or root_pick).lstrip("/")  # API wants NO leading slash

        if st.button("🔍 Preview") and path:
            exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
            st.info(f"🔢 {len(gather(dbx, path if path!="/" else '', exts))} file(s) match")

        if st.button("➤ Generate Markdown") and path:
            exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
            files = gather(dbx, path if path!="/" else '', exts)
            if flt:
                files = [f for f in files if flt.lower() in f.name.lower()]
            md = make_md(dbx, files, lambda: cancel_btn)
            if md:
                if not outfile.lower().endswith(".md"):
                    outfile += ".md"
                st.download_button("⬇ Download", io.StringIO("".join(md)).getvalue(), outfile, "text/markdown")
    except Exception as e:
        st.error(f"💥 {e}")
