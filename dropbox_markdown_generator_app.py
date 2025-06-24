import streamlit as st
import dropbox
import os
import io
import time
import datetime
from collections import defaultdict

"""
Dropbox Markdown Link Generator – Team‑Aware
===========================================
• Lists **all mount‑points** (personal + team folders) for the chosen user
• Allows manual path entry (auto‑sanitised)
• Pre‑views PDF / Excel file counts
• Works with Dropbox Business **Team‑Member File Access** tokens
"""

# ──────────────────────────────────────────────
# Utility helpers
# ──────────────────────────────────────────────

def force_direct_download(url: str) -> str:
    """Convert ?dl=0/preview links to ?dl=1 direct links."""
    return url.replace("&dl=0", "&dl=1").replace("?dl=0", "?dl=1")


def gather_files(dbx: dropbox.Dropbox, root: str, ext_tuple: tuple[str]) -> list:
    """Return all FileMetadata objects whose names end with `ext_tuple`."""
    result = dbx.files_list_folder(root, recursive=True)
    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)
    return [e for e in entries if isinstance(e, dropbox.files.FileMetadata) and e.name.lower().endswith(ext_tuple)]


def group_by_subfolder(files):
    grouped = defaultdict(list)
    for f in files:
        # drop initial slash and split full path
        parts = f.path_display.lstrip("/").split("/")
        folder = "/".join(parts[:-1]) if len(parts) > 1 else "Root"
        grouped[folder].append(f)
    return grouped


def build_markdown(dbx, files, cancel_fn):
    grouped = group_by_subfolder(files)
    total = sum(len(v) for v in grouped.values())
    if total == 0:
        return []

    bar = st.progress(0.0)
    stat = st.empty()
    eta_box = st.empty()
    t0 = time.time()
    processed = 0
    md_lines = ["# Document Sources\n\n"]

    for folder in sorted(grouped.keys()):
        md_lines.append(f"## {folder} ({len(grouped[folder])})\n\n")
        for f in grouped[folder]:
            if cancel_fn():
                stat.warning("✘ Generation cancelled.")
                return md_lines
            processed += 1
            bar.progress(processed / total)
            elapsed = time.time() - t0
            eta = datetime.timedelta(seconds=int(elapsed / processed * (total - processed)))
            stat.text(f"[{processed}/{total}] {os.path.basename(f.path_display)}")
            eta_box.text(f"⌛ ETA {eta}")

            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md_lines.append(f"- [{os.path.splitext(f.name)[0]}]({force_direct_download(url)})\n")
            except Exception as e:
                md_lines.append(f"- {f.name} (link‑error: {e})\n")
        md_lines.append("\n")

    bar.progress(1.0)
    stat.success("✔ Done")
    eta_box.empty()
    return md_lines

# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

st.set_page_config(page_title="Dropbox Markdown Generator", page_icon="★")
st.title("★ Dropbox Markdown Link Generator – Team Edition")

# Credentials & basic options
TOKEN = st.text_input("🔐 Dropbox Access Token", type="password")
OUTPUT_NAME = st.text_input("📝 Output Markdown File Name", "Sources.md")
FILTER = st.text_input("🔍 Optional Filename Filter")
FILE_KIND = st.radio("📄 File Type", ["PDF", "Excel"], horizontal=True)

cancel_pressed = st.button("✘ Cancel Generation")

if TOKEN:
    try:
        # Team‑level auth
        dbx_team = dropbox.DropboxTeam(TOKEN)
        members = dbx_team.team_members_list().members
        member_map = {f"{m.profile.name.display_name} ({m.profile.email})": m.profile.team_member_id for m in members}
        sel_member = st.selectbox("👤 Act As Team Member", list(member_map.keys()))
        dbx = dbx_team.as_user(member_map[sel_member])
        user = dbx.users_get_current_account()
        st.success(f"Authenticated as {user.name.display_name}")

        # --- Folder picker ---
        @st.cache_data(show_spinner=False)
        def list_mounts():
            entries = dbx.files_list_folder("", recursive=False, include_mounted_folders=True).entries
            return [e.path_display for e in entries if isinstance(e, dropbox.files.FolderMetadata)]

        mounts = list_mounts()
        pick = st.selectbox("📂 Choose Root/Mounted Folder", mounts)
        manual = st.text_input("✏️ Or enter custom folder path (case‑sensitive)")
        target_path = manual.strip() if manual.strip() else pick
        if target_path.startswith("/"):
            target_path = target_path  # API accepts with leading slash
        else:
            target_path = f"/{target_path}" if target_path else ""  # root if blank

        # Preview counts
        if st.button("🔍 Preview File Count") and target_path:
            ext = (".pdf",) if FILE_KIND == "PDF" else (".xlsx", ".xls", ".xlsm")
            files_preview = gather_files(dbx, target_path, ext)
            st.info(f"{len(files_preview)} {FILE_KIND} file(s) will be processed from *{target_path}*.")

        # Generate button
        if st.button("➤ Generate Markdown") and target_path:
            ext = (".pdf",) if FILE_KIND == "PDF" else (".xlsx", ".xls", ".xlsm")
            files_matched = gather_files(dbx, target_path, ext)
            if FILTER:
                files_matched = [f for f in files_matched if FILTER.lower() in f.name.lower()]

            md = build_markdown(dbx, files_matched, lambda: cancel_pressed)
            if md:
                if not OUTPUT_NAME.lower().endswith(".md"):
                    OUTPUT_NAME += ".md"
                buf = io.StringIO("".join(md))
                st.download_button("⬇ Download Markdown", data=buf.getvalue(), file_name=OUTPUT_NAME, mime="text/markdown")
    except Exception as exc:
        st.error(f"💥 Error: {exc}")
