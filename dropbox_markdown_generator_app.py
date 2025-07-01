import streamlit as st
import dropbox, os, io, time, math
from datetime import timedelta
from collections import defaultdict

# ░░░  CONFIG  ░░░ ###########################################################
BATCH = 25           # 每次脚本运行最多处理多少文件
###########################################################################

try:
    from dropbox.files import PathRoot
except ImportError:
    PathRoot = None


# ───────────────── Dropbox helpers ─────────────────────────────────────────
def norm_dropbox_path(p: str | None) -> str:
    if not p or p.strip() in {"/", "."}:
        return ""
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")


def force_dl(url: str) -> str:
    return url.replace("&dl=0", "&dl=1")


def make_member_client(team: dropbox.DropboxTeam, member_id: str) -> dropbox.Dropbox:
    try:
        return team.as_user(member_id)
    except AttributeError:          # 免费版 SDK 兼容
        return dropbox.Dropbox(team._oauth2_access_token,
                               headers={"Dropbox-API-Select-User": member_id})


def ns_scoped_client(base: dropbox.Dropbox, ns_id: str) -> dropbox.Dropbox:
    if PathRoot:
        return base.with_path_root(PathRoot.namespace_id(ns_id))
    hdr = {"Dropbox-API-Path-Root": f'{{".tag":"namespace_id","namespace_id":"{ns_id}"}}'}
    return dropbox.Dropbox(base._oauth2_access_token, headers={**base._headers, **hdr})


def resolve_namespace(team: dropbox.DropboxTeam, top_name: str) -> str | None:
    try:
        for sf in team.as_admin().sharing_list_folders(limit=300).entries:
            if sf.name == top_name and sf.path_lower:
                return sf.path_lower.split("ns:")[-1].split("/")[0]
    except Exception:
        pass
    try:
        for tf in team.team_team_folder_list().team_folders:
            if tf.name == top_name:
                return tf.team_folder_id.replace("tfid:", "")
    except Exception:
        pass
    return None


def list_folder_all_safe(dbx: dropbox.Dropbox, path: str, recursive: bool = True):
    try:
        res = dbx.files_list_folder(path, recursive=recursive)
    except dropbox.exceptions.ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            return None
        raise
    entries = res.entries
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        entries.extend(res.entries)
    return entries


def get_files(dbx_user: dropbox.Dropbox, team: dropbox.DropboxTeam,
              full_path: str, exts):
    full_path = norm_dropbox_path(full_path)
    entries = list_folder_all_safe(dbx_user, full_path)
    if entries is None:
        top_seg = full_path.lstrip("/").split("/")[0]
        ns_id = resolve_namespace(team, top_seg)
        if not ns_id:
            raise FileNotFoundError(f"Folder ‘{top_seg}’ not found")
        dbx_ns = ns_scoped_client(dbx_user, ns_id)
        inner = norm_dropbox_path("/".join(full_path.lstrip("/").split("/")[1:]))
        entries = list_folder_all_safe(dbx_ns, inner)
        if entries is None:
            raise FileNotFoundError("Folder not found inside team namespace")
        dbx_user = dbx_ns
    return dbx_user, [f for f in entries
                      if isinstance(f, dropbox.files.FileMetadata)
                      and f.name.lower().endswith(exts)]


# ───────────────── Streamlit helpers ───────────────────────────────────────
def fmt_hms(sec: float) -> str:
    return str(timedelta(seconds=int(sec)))


# ─────────────────  初始化 session_state  ───────────────────────────────────
def init_state():
    defaults = dict(
        running=False, cancel=False, start_time=None, file_list=[],
        processed=0, md=[], dbx_final=None,
        progress_bar=None, eta_box=None, status_box=None
    )
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

init_state()

# ─────────────────  UI  ─────────────────────────────────────────────────────
st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Ready")

token = st.text_input("🔐 Team access token", type="password")
folder_path = st.text_input("📁 Folder path (leave blank for root, e.g. /PAB_One_Bot)")
kind = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename = st.text_input("📝 Output filename", "Sources.md")

c1, c2 = st.columns(2)
gen_click = c1.button("Generate", disabled=st.session_state.running)
cancel_click = c2.button("Cancel", disabled=not st.session_state.running)

# ─────────────────  按钮逻辑  ───────────────────────────────────────────────
if gen_click:
    st.session_state.update(
        running=True, cancel=False, start_time=time.time(),
        processed=0, md=["# Sources\n\n"], file_list=[]
    )

if cancel_click:
    st.session_state.cancel = True

# ─────────────────  准备阶段 – 只跑一次  ────────────────────────────────────
if st.session_state.running and not st.session_state.file_list:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        user_email = st.selectbox("Act as", [m.profile.email for m in members])
        member_id = next(m.profile.team_member_id for m in members
                         if m.profile.email == user_email)
        dbx_user = make_member_client(team, member_id)
        st.success(f"Authenticated as {user_email}")

        exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_final, files = get_files(dbx_user, team, folder_path, exts)
        st.info(f"{len(files)} file(s) found. Building markdown…")

        st.session_state.update(
            file_list=files,
            dbx_final=dbx_final,
            progress_bar=st.progress(0.0),
            eta_box=st.empty(),
            status_box=st.empty()
        )
    except Exception as e:
        st.session_state.running = False
        st.error(str(e))

# ─────────────────  处理文件批次（修复重复）  ───────────────────────────────
if (st.session_state.running
        and not st.session_state.cancel
        and st.session_state.file_list):

    dbx   = st.session_state.dbx_final
    files = st.session_state.file_list

    # 只取本轮要处理的 slice，彻底避免重复
    start_idx = st.session_state.processed
    end_idx   = min(start_idx + BATCH, len(files))
    batch     = files[start_idx:end_idx]

    for f in batch:
        if st.session_state.cancel:
            break

        st.session_state.processed += 1
        elapsed = time.time() - st.session_state.start_time
        eta_total = (elapsed / st.session_state.processed) * len(files)
        eta_remaining = max(0.0, eta_total - elapsed)

        st.session_state.progress_bar.progress(
            st.session_state.processed / len(files))
        st.session_state.eta_box.text(
            f"⏳ Time left: {fmt_hms(eta_remaining)} • "
            f"Elapsed: {fmt_hms(elapsed)}")
        st.session_state.status_box.text(
            f"{st.session_state.processed}/{len(files)} – {f.name}")

        try:
            links = dbx.sharing_list_shared_links(path=f.path_lower,
                                                  direct_only=True).links
            url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(
                f.path_lower).url
            st.session_state.md.append(
                f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
        except Exception as e:
            st.session_state.md.append(f"- {f.name} (link err {e})\n")

    # 还有剩余就 rerun
    if st.session_state.processed < len(files) and not st.session_state.cancel:
        st.rerun()

# ─────────────────  收尾  ─────────────────────────────────────────────────
if (st.session_state.running
        and (st.session_state.processed == len(st.session_state.file_list)
             or st.session_state.cancel)):

    st.session_state.running = False

    if st.session_state.cancel:
        st.warning("✘ Cancelled – partial markdown ready below.")
    else:
        st.success(f"✔ Completed in "
                   f"{fmt_hms(time.time() - st.session_state.start_time)}")

    if st.session_state.md:
        if not filename.lower().endswith(".md"):
            filename += ".md"
        st.download_button("⬇ Download", io.StringIO("".join(st.session_state.md))
                           .getvalue(), filename, "text/markdown")

    # 清理占内存的大对象
    st.session_state.file_list  = []
    st.session_state.dbx_final  = None
