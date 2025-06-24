import streamlit as st
import dropbox
import os, io, time
from collections import defaultdict

# ------------------------------------------------------------
#  Compatibility helpers (old vs new dropbox‑python SDKs)
# ------------------------------------------------------------
try:
    from dropbox.files import PathRoot  # present in SDK ≥11.9
except ImportError:  # pragma: no cover – old SDK
    PathRoot = None  # sentinel

# ------------------------------------------------------------
#  Dropbox‑specific utilities
# ------------------------------------------------------------

def norm_dropbox_path(p: str | None) -> str:
    """Return a Dropbox‑API‑compliant path.

    * Root  -> ""  (empty string)
    * Any other -> "/path" with NO trailing slash
    """
    if not p or p.strip() in {"/", "."}:
        return ""
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")


def force_dl(url: str) -> str:
    """Turn a ?dl=0 shared‑link into a ?dl=1 direct‑download link."""
    return url.replace("&dl=0", "&dl=1")

def make_member_client(team: dropbox.DropboxTeam, member_id: str) -> dropbox.Dropbox:
    """Return a Dropbox client that *always* carries Dropbox‑API‑Select‑User."""
    try:  # modern SDK
        return team.as_user(member_id)
    except AttributeError:  # older SDK
        return dropbox.Dropbox(
            team._oauth2_access_token,
            headers={"Dropbox-API-Select-User": member_id},
        )


def ns_scoped_client(base: dropbox.Dropbox, ns_id: str) -> dropbox.Dropbox:
    """Return *base* client rooted at a namespace regardless of SDK version."""
    if PathRoot:  # SDK ≥11.9
        return base.with_path_root(PathRoot.namespace_id(ns_id))
    hdr = {
        "Dropbox-API-Path-Root": f'{{".tag":"namespace_id","namespace_id":"{ns_id}"}}'
    }
    return dropbox.Dropbox(base._oauth2_access_token, headers={**base._headers, **hdr})

# ------------------------------------------------------------
#  Namespace resolution helpers (team folders / shared folders)
# ------------------------------------------------------------

def resolve_namespace(team: dropbox.DropboxTeam, top_name: str) -> str | None:
    """Return namespace‑ID matching *top_name* or *None* if not found."""
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

# ------------------------------------------------------------
#  File gathering (recursively) with root‑path fix
# ------------------------------------------------------------

def try_list(dbx: dropbox.Dropbox, path: str):
    try:
        return dbx.files_list_folder(path, recursive=True).entries
    except dropbox.exceptions.ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            return None
        raise


def get_files(dbx_user: dropbox.Dropbox, team: dropbox.DropboxTeam, full_path: str, exts):
    """Return (*dbx_client*, [FileMetadata, …]) for *full_path* (root‑safe)."""
    full_path = norm_dropbox_path(full_path)

    entries = try_list(dbx_user, full_path)
    if entries is None:  # maybe team‑space namespace
        first_seg = full_path.lstrip("/").split("/")[0]
        ns_id = resolve_namespace(team, first_seg)
        if not ns_id:
            raise FileNotFoundError("Folder not found and no matching team namespace")

        dbx_ns = ns_scoped_client(dbx_user, ns_id)
        # inner path: everything *after* the namespace top folder
        rest = "/".join(full_path.lstrip("/").split("/")[1:])
        inner = norm_dropbox_path(rest)  # may be "" => namespace root

        entries = try_list(dbx_ns, inner)
        if entries is None:
            raise FileNotFoundError("Folder not found even inside team namespace")
        dbx_user = dbx_ns  # use namespaced client for link generation

    files = [
        f for f in entries
        if isinstance(f, dropbox.files.FileMetadata) and f.name.lower().endswith(exts)
    ]
    return dbx_user, files

# ------------------------------------------------------------
#  Markdown builder (progress bar + cancel check)
# ------------------------------------------------------------

def build_md(dbx: dropbox.Dropbox, files, cancel):
    """Yield a list of markdown lines for *files*, honouring *cancel()*."""
    groups: dict[str, list] = defaultdict(list)
    for f in files:
        groups[os.path.dirname(f.path_display).lstrip("/") or "Root"].append(f)

    total = len(files)
    if not total:
        return []

    bar = st.progress(0.0)
    stat = st.empty()
    done = 0
    md: list[str] = ["# Sources\n\n"]

    for folder in sorted(groups):
        md.append(f"## {folder} ({len(groups[folder])})\n\n")
        for f in groups[folder]:
            if cancel():
                stat.warning("✘ Cancelled")
                return md
            done += 1
            bar.progress(done / total)
            stat.text(f"{done}/{total} – {f.name}")
            try:
                links = dbx.sharing_list_shared_links(path=f.path_lower, direct_only=True).links
                url = links[0].url if links else dbx.sharing_create_shared_link_with_settings(f.path_lower).url
                md.append(f"- [{os.path.splitext(f.name)[0]}]({force_dl(url)})\n")
            except Exception as e:
                md.append(f"- {f.name} (link err {e})\n")
        md.append("\n")

    bar.progress(1.0)
    return md

# ------------------------------------------------------------
#  Streamlit UI
# ------------------------------------------------------------

st.set_page_config(page_title="Dropbox Markdown", page_icon="★")
st.title("★ Dropbox Markdown – Team Ready")

# 1️⃣ Inputs

token = st.text_input("🔐 Team access token", type="password")
folder_path = st.text_input("📁 Folder path (leave blank for root, e.g. /PAB_One_Bot)")
kind = st.radio("Type", ["PDF", "Excel"], horizontal=True)
filename = st.text_input("📝 Output filename", "Sources.md")
run = st.button("Generate")

# 2️⃣ Run logic

if run and token:
    try:
        # -------- authentication --------
        team = dropbox.DropboxTeam(token)
        members = team.team_members_list().members
        user_email = st.selectbox("Act as", [m.profile.email for m in members], key="userbox")
        member_id = next(m.profile.team_member_id for m in members if m.profile.email == user_email)
        dbx_user = make_member_client(team, member_id)
        st.success(f"Authenticated as {user_email}")

        # -------- gather files --------
        exts = (".pdf",) if kind == "PDF" else (".xlsx", ".xls", ".xlsm")
        dbx_final, files = get_files(dbx_user, team, folder_path, exts)
        st.info(f"{len(files)} file(s) found. Building markdown…")

        # -------- build markdown --------
        md = build_md(dbx_final, files, lambda: not run)
        if md:
            if not filename.lower().endswith(".md"):
                filename += ".md"
            st.download_button(
                "⬇ Download", io.StringIO("".join(md)).getvalue(), filename, "text/markdown"
            )
    except Exception as e:
        st.error(str(e))
