import streamlit as st
import dropbox
import os, io, time, datetime
from collections import defaultdict

# ------------------------------------------------------------
#  Compatibility helpers (old vs new dropbox-python SDKs)
# ------------------------------------------------------------
try:
    from dropbox.files import PathRoot  # present in SDK ≥11.9
except ImportError:  # pragma: no cover – old SDK
    PathRoot = None  # sentinel

# ---------------------------- misc ---------------------------

def force_dl(url: str) -> str:
    return url.replace("&dl=0", "&dl=1")


def make_member_client(team: dropbox.DropboxTeam, member_id: str) -> dropbox.Dropbox:
    """Return a Dropbox client that *always* carries Dropbox-API-Select-User."""
    try:  # modern SDK
        return team.as_user(member_id)
    except AttributeError:
        return dropbox.Dropbox(
            team._oauth2_access_token,
            headers={"Dropbox-API-Select-User": member_id},
        )


def ns_scoped_client(base: dropbox.Dropbox, ns_id: str) -> dropbox.Dropbox:
    """Return client rooted at namespace regardless of SDK version."""
    if PathRoot:
        return base.with_path_root(PathRoot.namespace_id(ns_id))
    hdr = {"Dropbox-API-Path-Root": f'{{".tag":"namespace_id","namespace_id":"{ns_id}"}}'}
    return dropbox.Dropbox(base._oauth2_access_token, headers={**base._headers, **hdr})

# ------------------- namespace resolution -------------------

def resolve_namespace(team: dropbox.DropboxTeam, top_name: str) -> str | None:
    # shared/team folders API
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

# ---------------------- file gathering ----------------------

def try_list(dbx, path):
    try:
        return dbx.files_list_folder(path, recursive=True).entries
    except dropbox.exceptions.ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            return None
        raise


def get_files(dbx_user, team, full_path: str, exts):
    entries = try_list(dbx_user, full_path)
    if entries is None:  # maybe team-space namespace
        first_seg = full_path.lstrip("/").split("/")[0]
        ns_id = resolve_namespace(team, first_seg)
        if not ns_id:
            raise FileNotFoundError("Folder not found and no matching team namespace")
        dbx_ns = ns_scoped_client(dbx_user, ns_id)
        inner = "/" + "/".join(full_path.lstrip("/").split("/")[1:])
        entries = try_list(dbx_ns, inner)
        if entries is None:
            raise FileNotFoundError("Folder not found even inside team namespace")
        dbx_user = dbx_ns  # use namespaced client for link generation
    return dbx_user, [f for f in entries if isinstance(f, dropbox.files.FileMetadata) and f.name.lower().endswith(exts)]

# --------------------- markdown builder ---------------------

def build_md(dbx, files, cancel):
    groups = defaultdict(list)
    for f in files:
        groups[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)
    total = len(files)
    if not total:
        return []
    bar, stat = st.progress(0.), st.empty()
    t0, done, md = time.time(), 0, ["# Sources\n\n"]
    for folder in sorted(groups):
        md.append(f"## {folder} ({len(groups[folder])})\n\n")
        for f in groups[folder]:
            if cancel():
                stat.warning("✘ Cancelled"); return md
            done += 1; bar.progress(done/total)
            stat.text(f"{done}/{total} – {f.name}")
            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md.append(f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
            except Exception as e:
                md.append(f"- {f.name} (link err {e})\n")
        md.append("\n")
    bar.progress(1.0); return md

# --------------------------- UI ------------------------------

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Ready")

token = st.text_input("🔐 Team access token", type="password")
folder_path = st.text_input("📁 Folder path (e.g. /PAB One Bot)")
kind = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename = st.text_input("📝 Output filename", "Sources.md")
run = st.button("Generate")

if run and token and folder_path:
    try:
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        user_email = st.selectbox("Act as", [m.profile.email for m in members], key="userbox")
        member_id = next(m.profile.team_member_id for m in members if m.profile.email == user_email)
        dbx_user = make_member_client(team, member_id)
        st.success(f"Authenticated as {user_email}")
        exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_final, files = get_files(dbx_user, team, folder_path, exts)
        st.info(f"{len(files)} file(s) found. Building markdown…")
        md = build_md(dbx_final, files, lambda: not run)
        if md:
            if not filename.lower().endswith(".md"):
                filename += ".md"
            st.download_button("⬇ Download", io.StringIO("".join(md)).getvalue(), filename, "text/markdown")
    except Exception as e:
        st.error(str(e))
