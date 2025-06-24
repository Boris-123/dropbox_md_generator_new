import streamlit as st
import dropbox
import os, io, time
from datetime import timedelta
from collections import defaultdict

# ────────────────────────────────────────────────────────────
#  Compatibility helpers (old vs new dropbox-python SDKs)
# ────────────────────────────────────────────────────────────
try:
    from dropbox.files import PathRoot              # SDK ≥ 11.9
except ImportError:                                  # old SDK
    PathRoot = None

# ────────────────────────────────────────────────────────────
#  Dropbox path + client helpers
# ────────────────────────────────────────────────────────────

def norm_dropbox_path(p: str | None) -> str:
    """Return Dropbox‑API‑compliant path ("" for root, else "/…", no trailing slash)."""
    if not p or p.strip() in {"/", "."}:
        return ""
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")


def force_dl(url: str) -> str:
    """Convert a ?dl=0 link to direct‑download ?dl=1."""
    return url.replace("?dl=0", "?dl=1").replace("&dl=0", "&dl=1")


def make_member_client(team: dropbox.DropboxTeam, member_id: str) -> dropbox.Dropbox:
    try:
        return team.as_user(member_id)              # modern SDK
    except AttributeError:                          # old SDK shim
        return dropbox.Dropbox(team._oauth2_access_token, headers={"Dropbox-API-Select-User": member_id})


def ns_scoped_client(base: dropbox.Dropbox, ns_id: str) -> dropbox.Dropbox:
    if PathRoot:
        return base.with_path_root(PathRoot.namespace_id(ns_id))
    hdr = {"Dropbox-API-Path-Root": f'{{".tag":"namespace_id","namespace_id":"{ns_id}"}}'}
    return dropbox.Dropbox(base._oauth2_access_token, headers={**base._headers, **hdr})

# ────────────────────────────────────────────────────────────
#  Namespace resolution (team & shared folders)
# ────────────────────────────────────────────────────────────

def resolve_namespace(team: dropbox.DropboxTeam, top_name: str) -> str | None:
    """Return namespace‑id whose top‑level folder matches *top_name*."""
    try:  # shared folders
        for sf in team.as_admin().sharing_list_folders(limit=300).entries:
            if sf.name == top_name and sf.path_lower:
                return sf.path_lower.split("ns:")[-1].split("/")[0]
    except Exception:
        pass
    try:  # team folders
        for tf in team.team_team_folder_list().team_folders:
            if tf.name == top_name:
                return tf.team_folder_id.replace("tfid:", "")
    except Exception:
        pass
    return None

# ────────────────────────────────────────────────────────────
#  Safe, paginated folder listing
# ────────────────────────────────────────────────────────────

def list_folder_all_safe(dbx: dropbox.Dropbox, path: str, recursive: bool = True):
    """Return list of entries or *None* if the path isn’t found (no exception)."""
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

# ────────────────────────────────────────────────────────────
#  Top‑level file fetcher (handles member space *and* team space)
# ────────────────────────────────────────────────────────────

def get_files(dbx_user: dropbox.Dropbox, team: dropbox.DropboxTeam, full_path: str, exts):
    full_path = norm_dropbox_path(full_path)

    # 1️⃣ member’s personal space
    entries = list_folder_all_safe(dbx_user, full_path)

    # 2️⃣ if missing there, try inside a team namespace
    if entries is None:
        top_seg = full_path.lstrip("/").split("/")[0]
        ns_id = resolve_namespace(team, top_seg)
        if not ns_id:
            raise FileNotFoundError(f"Folder ‘{top_seg}’ not found in member space or as team namespace")
        dbx_ns = ns_scoped_client(dbx_user, ns_id)
        inner = norm_dropbox_path("/".join(full_path.lstrip("/").split("/")[1:]))
        entries = list_folder_all_safe(dbx_ns, inner)
        if entries is None:
            raise FileNotFoundError("Folder not found even inside resolved team namespace")
        dbx_user = dbx_ns  # use namespaced client later (links)

    files = [f for f in entries if isinstance(f, dropbox.files.FileMetadata) and f.name.lower().endswith(exts)]
    return dbx_user, files

# ────────────────────────────────────────────────────────────
#  Progress + ETA markdown builder
# ────────────────────────────────────────────────────────────

def fmt_hms(sec: float) -> str:
    return str(timedelta(seconds=int(sec)))


def build_md(dbx: dropbox.Dropbox, files, is_cancelled):
    groups = defaultdict(list)
    for f in files:
        groups[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)

    total = len(files)
    if total == 0:
        return []

    bar = st.progress(0.0)
    eta_box = st.empty()
    status_box = st.empty()
    md_lines = ["# Sources\n\n"]

    processed = 0
    for folder in sorted(groups):
        md_lines.append(f"## {folder} ({len(groups[folder])})\n\n")
        for f in groups[folder]:
            if is_cancelled():
                status_box.warning("✘ Cancelled by user")
                return md_lines

            processed += 1
            elapsed = time.time() - st.session_state.start_time
            eta_total = (elapsed / processed) * total
            eta_remaining = max(0.0, eta_total - elapsed)

            bar.progress(processed / total)
            eta_box.text(f"⏳ Time left: {fmt_hms(eta_remaining)} • Elapsed: {fmt_hms(elapsed)}")
            status_box.text(f"{processed}/{total} – {f.name}")

            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md_lines.append(f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
            except Exception as e:
                md_lines.append(f"- {f.name} (link err {e})\n")
        md_lines.append("\n")

    bar.progress(1.0)
    eta_box.success(f"✔ Completed in {fmt_hms(time.time() - st.session_state.start_time)}")
    return md_lines

# ────────────────────────────────────────────────────────────
#  Streamlit UI / state management
# ────────────────────────────────────────────────────────────

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Ready")

for key, default in {"running": False, "cancel": False, "start_time": None}.items():
    st.session_state.setdefault(key, default)

# 👉 Inputs

token = st.text_input("🔐 Team access token", type="password")
folder_path = st.text_input("📁 Folder path (leave blank for root, e.g. /PAB_One_Bot)")
kind = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename = st.text_input("📝 Output filename", "Sources.md")

c1, c2 = st.columns(2)
with c1:
    gen_click = st.button("Generate", disabled=st.session_state.running)
with c2:
    cancel_click = st.button("Cancel", disabled=not st.session_state.running)

if gen_click:
    st.session_state.update({"running": True, "cancel": False, "start_time": time.time()})

if cancel_click:
    st.session_state.cancel = True
    st.warning("Cancelling… will stop after current file.")

# 👉 Main processing loop
if st.session_state.running and token:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        user_email = st.selectbox("Act as", [m.profile.email for m in members])
        member_id = next(m.profile.team_member_id for m in members if m.profile.email == user_email)
        dbx_user = make_member_client(team, member_id)
        st.success(f"Authenticated as {user_email}")

        exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_final, files = get_files(dbx_user, team, folder_path, exts)
        st.info(f"{len(files)} file(s) found. Building markdown…")

        md = build_md(dbx_final, files, lambda: st.session_state.cancel)
        st.session_state.running = False

        if md and not st.session_state.cancel:
            if not filename.lower().endswith(".md"):
                filename += ".md"
            st.download_button("⬇ Download", io.StringIO("".join(md)).getvalue(), filename, "text/markdown")
    except Exception as e:
        st.session_state.running = False
        st.error(str(e))
