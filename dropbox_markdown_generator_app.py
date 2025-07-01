import streamlit as st
import dropbox, os, io, time
from datetime import timedelta
from collections import defaultdict

# ░░░  CONFIG  ░░░ ###########################################################
BATCH = 25               # 每轮 Streamlit run 最多处理多少文件
###########################################################################

# ───────────────────────────────────────────────────────────────────────────
#  初始化 session_state（避免缺键异常）
# ───────────────────────────────────────────────────────────────────────────
def safe_init_state():
    defaults = dict(
        running=False, cancel=False, start_time=None,
        file_list=[], processed=0,
        dbx_final=None, progress_bar=None, eta_box=None, status_box=None,
        group_map=None, sorted_folders=None,
        folder_md=defaultdict(list),        # folder -> [markdown_line, ...]
    )
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

safe_init_state()

# ───────────────────────────────────────────────────────────────────────────
#  Dropbox 助手函数（与原始脚本保持一致）
# ───────────────────────────────────────────────────────────────────────────
try:
    from dropbox.files import PathRoot
except ImportError:
    PathRoot = None

def norm_dropbox_path(p):
    if not p or p.strip() in {"/", "."}:
        return ""
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")

def force_dl(url): return url.replace("&dl=0", "&dl=1")

def make_member_client(team, member_id):
    try:
        return team.as_user(member_id)
    except AttributeError:   # 免费 SDK 兼容
        return dropbox.Dropbox(team._oauth2_access_token,
                               headers={"Dropbox-API-Select-User": member_id})

def ns_scoped_client(base, ns_id):
    if PathRoot:
        return base.with_path_root(PathRoot.namespace_id(ns_id))
    hdr = {"Dropbox-API-Path-Root":
           f'{{".tag":"namespace_id","namespace_id":"{ns_id}"}}'}
    return dropbox.Dropbox(base._oauth2_access_token,
                           headers={**base._headers, **hdr})

def resolve_namespace(team, top_name):
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

def list_folder_all_safe(dbx, path, recursive=True):
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

def get_files(dbx_user, team, full_path, exts):
    full_path = norm_dropbox_path(full_path)
    entries = list_folder_all_safe(dbx_user, full_path)
    if entries is None:                          # 可能在团队空间
        top_seg = full_path.lstrip("/").split("/")[0]
        ns_id = resolve_namespace(team, top_seg)
        if not ns_id:
            raise FileNotFoundError(f"Folder ‘{top_seg}’ not found")
        dbx_ns = ns_scoped_client(dbx_user, ns_id)
        inner = norm_dropbox_path("/".join(full_path.lstrip("/").split("/")[1:]))
        entries = list_folder_all_safe(dbx_ns, inner)
        if entries is None:
            raise FileNotFoundError("Inner folder not found in namespace")
        dbx_user = dbx_ns
    return dbx_user, [f for f in entries
                      if isinstance(f, dropbox.files.FileMetadata)
                      and f.name.lower().endswith(exts)]

# ───────────────────────────────────────────────────────────────────────────
#  Streamlit UI
# ───────────────────────────────────────────────────────────────────────────
fmt_hms = lambda s: str(timedelta(seconds=int(s)))
st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Ready")

token       = st.text_input("🔐 Team access token", type="password")
folder_path = st.text_input("📁 Folder path (e.g. /PAB_One_Bot)", value="/")
kind        = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename    = st.text_input("📝 Output filename", "Sources.md")

c1, c2 = st.columns(2)
gen_click    = c1.button("Generate",
                         disabled=st.session_state.get("running", False))
cancel_click = c2.button("Cancel",
                         disabled=not st.session_state.get("running", False))

# ───────────────── 按钮逻辑 ────────────────────────────────────────────────
if gen_click:
    st.session_state.update(
        running=True, cancel=False, start_time=time.time(),
        processed=0, file_list=[], group_map=None, sorted_folders=None,
        folder_md=defaultdict(list))

if cancel_click:
    st.session_state.cancel = True

# ───────────────── 准备阶段（一次） ────────────────────────────────────────
if st.session_state.running and not st.session_state.file_list:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        user_email = st.selectbox("Act as", [m.profile.email for m in members])
        member_id  = next(m.profile.team_member_id for m in members
                          if m.profile.email == user_email)
        dbx_user = make_member_client(team, member_id)
        st.success(f"Authenticated as {user_email}")

        exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_final, files = get_files(dbx_user, team, folder_path, exts)
        st.info(f"{len(files)} file(s) found. Building markdown…")

        grp = defaultdict(list)
        for f in files:
            key = os.path.dirname(f.path_display).lstrip("/") or "Root"
            grp[key].append(f)

        st.session_state.update(
            file_list=files,
            dbx_final=dbx_final,
            group_map=grp,
            sorted_folders=sorted(grp),
            progress_bar=st.progress(0.0),
            eta_box=st.empty(),
            status_box=st.empty()
        )
    except Exception as e:
        st.session_state.running = False
        st.error(str(e))

# ───────────────── Incremental processing（分批缓存到 folder_md） ──────────
if (st.session_state.running
        and not st.session_state.cancel
        and st.session_state.file_list):

    files_all = st.session_state.file_list
    dbx       = st.session_state.dbx_final

    start_idx = st.session_state.processed
    end_idx   = min(start_idx + BATCH, len(files_all))
    current_batch = files_all[start_idx:end_idx]

    for f in current_batch:
        if st.session_state.cancel:
            break

        st.session_state.processed += 1
        elapsed = time.time() - st.session_state.start_time
        eta_tot = (elapsed / st.session_state.processed) * len(files_all)
        eta_rem = max(0.0, eta_tot - elapsed)
        st.session_state.progress_bar.progress(
            st.session_state.processed / len(files_all))
        st.session_state.eta_box.text(
            f"⏳ Time left: {fmt_hms(eta_rem)} • Elapsed: {fmt_hms(elapsed)}")
        st.session_state.status_box.text(
            f"{st.session_state.processed}/{len(files_all)} – {f.name}")

        folder = os.path.dirname(f.path_display).lstrip("/") or "Root"
        try:
            links = dbx.sharing_list_shared_links(
                path=f.path_lower, direct_only=True).links
            url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(
                f.path_lower).url
            line = f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n"
        except Exception as e:
            line = f"- {f.name} (link err {e})\n"

        st.session_state.folder_md[folder].append(line)

    if (st.session_state.processed < len(files_all)
            and not st.session_state.cancel):
        st.rerun()

# ───────────────── 收尾：生成 Markdown（含计数） ──────────────────────────
if (st.session_state.running
        and (st.session_state.processed == len(st.session_state.file_list)
             or st.session_state.cancel)):

    st.session_state.running = False
    md_lines = ["# Sources\n\n"]

    for folder in st.session_state.sorted_folders:
        count = len(st.session_state.folder_md[folder])
        md_lines.append(f"## {folder} ({count})\n")
        md_lines.extend(st.session_state.folder_md[folder])
        md_lines.append("\n")

    if st.session_state.cancel:
        st.warning("✘ Cancelled – partial markdown ready below.")
    else:
        st.success(f"✔ Completed in "
                   f"{fmt_hms(time.time() - st.session_state.start_time)}")

    out_name = filename if filename.lower().endswith(".md") else f"{filename}.md"
    st.download_button("⬇ Download", "".join(md_lines), out_name, "text/markdown")

    # 清理大对象
    st.session_state.file_list      = []
    st.session_state.group_map      = None
    st.session_state.sorted_folders = None
    st.session_state.folder_md      = defaultdict(list)
