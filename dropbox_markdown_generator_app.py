import streamlit as st
import dropbox, os, io, time
from datetime import timedelta
from collections import defaultdict

# ░░░  CONFIG  ░░░ ###########################################################
BATCH = 25   # number of files processed per script run
###########################################################################

try:
    from dropbox.files import PathRoot
except ImportError:
    PathRoot = None

# ───────── Dropbox helpers (保持原样) ───────────────────────────────────────
def norm_dropbox_path(p): ...
def force_dl(url): ...
def make_member_client(team, member_id): ...
def ns_scoped_client(base, ns_id): ...
def resolve_namespace(team, top_name): ...
def list_folder_all_safe(dbx, path, recursive=True): ...
def get_files(dbx_user, team, full_path, exts): ...

# ───────── UI helpers / init state (保持原样) ──────────────────────────────
fmt_hms = lambda s: str(timedelta(seconds=int(s)))
def init_state(): ...
init_state()

# ───────── 顶部 UI (保持原样) ──────────────────────────────────────────────
st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Ready")
token = st.text_input("🔐 Team access token", type="password")
folder_path = st.text_input("📁 Folder path (leave blank for root, e.g. /PAB_One_Bot)")
kind = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename = st.text_input("📝 Output filename", "Sources.md")
c1, c2 = st.columns(2)
gen_click    = c1.button("Generate", disabled=st.session_state.running)
cancel_click = c2.button("Cancel",   disabled=not st.session_state.running)

# ───────── 按钮逻辑 (保持原样) ─────────────────────────────────────────────
if gen_click:  ...
if cancel_click: st.session_state.cancel = True

# ───────── 准备阶段 (保持原样) ────────────────────────────────────────────
if st.session_state.running and not st.session_state.file_list:
    try:
        ...
    except Exception as e:
        st.session_state.running = False
        st.error(str(e))

# ───────── Incremental processing (仅此处有改动) ──────────────────────────
if (st.session_state.running
        and not st.session_state.cancel
        and st.session_state.file_list):

    files_all = st.session_state.file_list
    dbx       = st.session_state.dbx_final

    start_idx = st.session_state.processed
    end_idx   = min(start_idx + BATCH, len(files_all))
    slice_list = files_all[start_idx:end_idx]          # ← 列表即可

    if st.session_state.group_map is None:
        grp = defaultdict(list)
        for f in files_all:
            grp[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)
        st.session_state.group_map       = grp
        st.session_state.sorted_folders  = sorted(grp)
        st.session_state.folder_written  = set()

    for folder in st.session_state.sorted_folders:
        for f in st.session_state.group_map[folder]:
            if f not in slice_list:                    # ← 用列表判断
                continue
            if st.session_state.cancel:
                break

            # 进度/ETA UI —— 保持原逻辑
            st.session_state.processed += 1
            elapsed = time.time() - st.session_state.start_time
            eta_total = (elapsed / st.session_state.processed) * len(files_all)
            eta_remaining = max(0.0, eta_total - elapsed)
            st.session_state.progress_bar.progress(
                st.session_state.processed / len(files_all))
            st.session_state.eta_box.text(
                f"⏳ Time left: {fmt_hms(eta_remaining)} • "
                f"Elapsed: {fmt_hms(elapsed)}")
            st.session_state.status_box.text(
                f"{st.session_state.processed}/{len(files_all)} – {f.name}")

            if folder not in st.session_state.folder_written:
                st.session_state.md.append(f"\n### {folder}\n")
                st.session_state.folder_written.add(folder)

            try:
                links = dbx.sharing_list_shared_links(
                    path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(
                    f.path_lower).url
                st.session_state.md.append(
                    f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
            except Exception as e:
                st.session_state.md.append(f"- {f.name} (link err {e})\n")

    if (st.session_state.processed < len(files_all)
            and not st.session_state.cancel):
        st.rerun()                                    # ← 使用 st.rerun()

# ───────── Finishing up (保持原样，未动) ───────────────────────────────────
if (st.session_state.running
        and (st.session_state.processed == len(st.session_state.file_list)
             or st.session_state.cancel)):

    st.session_state.running = False
    ...
    st.session_state.file_list     = []
    st.session_state.group_map     = None
    st.session_state.sorted_folders = None
