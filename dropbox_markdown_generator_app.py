import streamlit as st
import dropbox
import os
import io
import time
import datetime
from collections import defaultdict

# -------------------------------
# Utility Functions
# -------------------------------

def force_direct_download(url: str) -> str:
    return url.replace("&dl=0", "&dl=1")

def gather_all_files(dbx: dropbox.Dropbox, path: str, ext: str) -> list:
    result = dbx.files_list_folder(path, recursive=True)
    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)
    return [e for e in entries if isinstance(e, dropbox.files.FileMetadata) and e.name.lower().endswith(ext)]

def generate_sources(dbx: dropbox.Dropbox, files: list, cancel_flag, filter_keyword: str = "") -> list:
    grouped = defaultdict(list)
    for item in files:
        parts = item.path_display.strip("/").split("/")
        if len(parts) > 2:
            folder_path = "/".join(parts[1:-1])
        elif len(parts) == 2:
            folder_path = parts[1]
        else:
            folder_path = "Uncategorized"
        grouped[folder_path].append(item)

    lines = ["# Document Sources\n\n"]
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    time_text = st.empty()

    if filter_keyword:
        for folder in list(grouped.keys()):
            grouped[folder] = [f for f in grouped[folder] if filter_keyword.lower() in f.name.lower()]

    total_filtered = sum(len(grouped[fld]) for fld in grouped)
    if total_filtered == 0:
        st.warning("⚠ No files match the filter. Please adjust your keyword.")
        return []

    processed = 0
    start_time = time.time()

    for folder in sorted(grouped.keys()):
        if not grouped[folder]:
            continue
        lines.append(f"## {folder}\n\n")
        for item in grouped[folder]:
            if cancel_flag():
                status_text.warning("✘ Generation cancelled by user.")
                return lines

            processed += 1
            progress = processed / total_filtered
            progress_bar.progress(progress)
            status_text.text(f"[{processed}/{total_filtered}] Processing: {item.name}")

            elapsed = time.time() - start_time
            avg_time = elapsed / processed
            eta_sec = int(avg_time * (total_filtered - processed))
            eta = datetime.timedelta(seconds=eta_sec)
            time_text.text(f"⌛ ETA: {eta}")

            try:
                links = dbx.sharing_list_shared_links(path=item.path_lower, direct_only=True).links
                if links:
                    share_url = links[0].url
                else:
                    share_url = dbx.sharing_create_shared_link_with_settings(item.path_lower).url

                direct_url = force_direct_download(share_url)
                title = os.path.splitext(item.name)[0]
                lines.append(f"- [{title}]({direct_url})\n\n\n")
            except Exception as e:
                st.warning(f"⚠ Failed to get link for \"{item.name}\": {e}")

    status_text.success("✔ All files processed.")
    time_text.text("")
    progress_bar.progress(1.0)
    return lines

# -------------------------------
# Streamlit Interface
# -------------------------------

st.set_page_config(page_title="Dropbox Markdown Generator", page_icon="★")
st.title("★ Dropbox Markdown Link Generator")

token = st.text_input("🔐 Dropbox Access Token", type="password", key="access_token")
output_filename = st.text_input("📝 Output Markdown File Name", value="Sources.md", key="output_filename")
filter_keyword = st.text_input("🔍 Optional Filter (filename contains…)", value="", key="filter_text")

type_filter = st.radio("📄 File Type to Link", options=["PDF", "Excel"], horizontal=True)

cancel_flag = st.session_state.get("cancel", False)
if st.button("✘ Cancel", key="cancel button"):
    st.session_state["cancel"] = True
else:
    st.session_state["cancel"] = False

if token:
    try:
        dbx_team = dropbox.DropboxTeam(token)
        members = dbx_team.team_members_list().members
        member_options = {
            f"{m.profile.name.display_name} ({m.profile.email})": m.profile.team_member_id
            for m in members
        }
        selected_display = st.selectbox("👤 Select your Dropbox Identity", list(member_options.keys()))
        selected_team_member_id = member_options[selected_display]
        dbx = dbx_team.as_user(selected_team_member_id)

        account = dbx.users_get_current_account()
        st.success(f"✔ Authenticated as: {account.name.display_name}")

        def get_all_folders(path="/"):
            folder_list = []
            try:
                entries = dbx.files_list_folder(path, recursive=True).entries
                for e in entries:
                    if isinstance(e, dropbox.files.FolderMetadata):
                        folder_list.append(e.path_display)
                return folder_list
            except Exception as e:
                st.warning(f"⚠ Failed to list folders: {e}")
                return []

        folder_choices = get_all_folders()
        selected_folder_path = st.selectbox("📂 Choose a folder to scan:", folder_choices)
        manual_folder_path = st.text_input("✏️ Or enter a custom folder path:")
        final_path = manual_folder_path if manual_folder_path else selected_folder_path

        if st.button("➤ Generate Markdown", key="generate_button"):
            if not output_filename:
                st.error("⚠ Please fill in the output filename.")
            else:
                try:
                    ext = ".pdf" if type_filter == "PDF" else ".xlsx"
                    files = gather_all_files(dbx, final_path, ext)
                    st.write(f"📄 Found {len(files)} {type_filter} file(s) in the folder.")
                    lines = generate_sources(
                        dbx,
                        files,
                        cancel_flag=lambda: st.session_state["cancel"],
                        filter_keyword=filter_keyword
                    )

                    if not output_filename.lower().endswith(".md"):
                        output_filename += ".md"

                    output_buffer = io.StringIO()
                    output_buffer.writelines(lines)

                    st.download_button(
                        label="⬇ Download Markdown File",
                        data=output_buffer.getvalue(),
                        file_name=output_filename,
                        mime="text/markdown"
                    )
                except Exception as e:
                    st.error(f"✘ Error: {e}")
    except Exception as e:
        st.error(f"✘ Error: {e}")
