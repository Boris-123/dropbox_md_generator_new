
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
    """Convert Dropbox preview URL to a direct‐download URL."""
    return url.replace("&dl=0", "&dl=1")

def gather_all_pdfs(dbx: dropbox.Dropbox, path: str) -> list:
    """Recursively gather all PDF files under the given Dropbox path."""
    result = dbx.files_list_folder(path, recursive=True)
    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    return [
        e for e in entries
        if isinstance(e, dropbox.files.FileMetadata)
        and e.name.lower().endswith(".pdf")
    ]

def generate_sources(dbx: dropbox.Dropbox, pdfs: list, cancel_flag, filter_keyword: str = "") -> list:
    """
    Generate grouped Markdown lines by full folder path, with:
        • Progress bar
        • Current status
        • ETA
        • Cancel support
        • Optional filename filter
    """
    grouped = defaultdict(list)
    total = len(pdfs)

    # Group by the full nested path under the root
    for item in pdfs:
        parts = item.path_display.strip("/").split("/")
        if len(parts) > 2:
            folder_path = "/".join(parts[1:-1])
        elif len(parts) == 2:
            folder_path = parts[1]
        else:
            folder_path = "Uncategorized"
        grouped[folder_path].append(item)

    lines = ["# Document Sources\n\n"]

    # Initialize Streamlit progress elements
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    time_text = st.empty()

    # If a filter keyword is provided, drop any files whose names do not contain it
    if filter_keyword:
        for folder in list(grouped.keys()):
            grouped[folder] = [
                f for f in grouped[folder]
                if filter_keyword.lower() in f.name.lower()
            ]

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
            # Allow user to cancel mid‐process
            if cancel_flag():
                status_text.warning("✘ Generation cancelled by user.")
                return lines

            processed += 1
            progress = processed / total_filtered
            progress_bar.progress(progress)
            status_text.text(f"[{processed}/{total_filtered}] Processing: {item.name}")

            # Compute and display ETA
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

# Use a BMP‐safe icon or None here to avoid surrogate errors on Windows
st.set_page_config(page_title="Dropbox Markdown Generator", page_icon="★")

st.title("★ Dropbox Markdown Link Generator")

# Input: Dropbox Access Token
token = st.text_input("🔑 Dropbox Access Token", type="password")

# Input: Dropbox Folder Path
folder_path = st.text_input("📂 Dropbox Folder Path (e.g., /PIAS testing)", value="/")

# Input: Desired Markdown filename
output_filename = st.text_input("📝 Output Markdown File Name", value="Sources.md")

# Input: Optional filter text
filter_keyword = st.text_input("🔍 Optional Filter (filename contains…)", value="")

# Cancel button logic (store in session_state)
cancel_flag = st.session_state.get("cancel", False)
if st.button("✘ Cancel"):
    st.session_state["cancel"] = True
else:
    st.session_state["cancel"] = False

# Generate Markdown button
if st.button("➤ Generate Markdown"):
    if not token or not folder_path or not output_filename:
        st.error("⚠ Please fill in all required fields.")
    else:
        try:
            # Authenticate to Dropbox
            dbx = dropbox.Dropbox(token)
            account = dbx.users_get_current_account()
            st.success(f"✔ Authenticated as: {account.name.display_name}")

            # List all PDFs under the given folder
            pdfs = gather_all_pdfs(dbx, folder_path)
            st.write(f"Found {len(pdfs)} PDF(s) in the specified folder.")

            # Generate the markdown lines (with progress & cancel support)
            lines = generate_sources(
                dbx,
                pdfs,
                cancel_flag=lambda: st.session_state["cancel"],
                filter_keyword=filter_keyword
            )

            # Ensure the filename ends with .md
            if not output_filename.lower().endswith(".md"):
                output_filename += ".md"

            # Create an in‐memory text buffer and push to download button
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
    """Convert Dropbox preview URL to a direct‐download URL."""
    return url.replace("&dl=0", "&dl=1")

def gather_all_pdfs(dbx: dropbox.Dropbox, path: str) -> list:
    """Recursively gather all PDF files under the given Dropbox path."""
    result = dbx.files_list_folder(path, recursive=True)
    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    return [
        e for e in entries
        if isinstance(e, dropbox.files.FileMetadata)
        and e.name.lower().endswith(".pdf")
    ]

def generate_sources(dbx: dropbox.Dropbox, pdfs: list, cancel_flag, filter_keyword: str = "") -> list:
    """
    Generate grouped Markdown lines by full folder path, with:
        • Progress bar
        • Current status
        • ETA
        • Cancel support
        • Optional filename filter
    """
    grouped = defaultdict(list)
    total = len(pdfs)

    # Group by the full nested path under the root
    for item in pdfs:
        parts = item.path_display.strip("/").split("/")
        if len(parts) > 2:
            folder_path = "/".join(parts[1:-1])
        elif len(parts) == 2:
            folder_path = parts[1]
        else:
            folder_path = "Uncategorized"
        grouped[folder_path].append(item)

    lines = ["# Document Sources\n\n"]

    # Initialize Streamlit progress elements
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    time_text = st.empty()

    # If a filter keyword is provided, drop any files whose names do not contain it
    if filter_keyword:
        for folder in list(grouped.keys()):
            grouped[folder] = [
                f for f in grouped[folder]
                if filter_keyword.lower() in f.name.lower()
            ]

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
            # Allow user to cancel mid‐process
            if cancel_flag():
                status_text.warning("✘ Generation cancelled by user.")
                return lines

            processed += 1
            progress = processed / total_filtered
            progress_bar.progress(progress)
            status_text.text(f"[{processed}/{total_filtered}] Processing: {item.name}")

            # Compute and display ETA
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

# Use a BMP‐safe icon or None here to avoid surrogate errors on Windows
st.set_page_config(page_title="Dropbox Markdown Generator", page_icon="★")

st.title("★ Dropbox Markdown Link Generator")

# Input: Dropbox Access Token
token = st.text_input("🔑 Dropbox Access Token", type="password")

# Input: Dropbox Folder Path
folder_path = st.text_input("📂 Dropbox Folder Path (e.g., /PIAS testing)", value="/")

# Input: Desired Markdown filename
output_filename = st.text_input("📝 Output Markdown File Name", value="Sources.md")

# Input: Optional filter text
filter_keyword = st.text_input("🔍 Optional Filter (filename contains…)", value="")

# Cancel button logic (store in session_state)
cancel_flag = st.session_state.get("cancel", False)
if st.button("✘ Cancel"):
    st.session_state["cancel"] = True
else:
    st.session_state["cancel"] = False

# Generate Markdown button
if st.button("➤ Generate Markdown"):
    if not token or not folder_path or not output_filename:
        st.error("⚠ Please fill in all required fields.")
    else:
        try:
            # Authenticate to Dropbox
            dbx = dropbox.Dropbox(token)
            account = dbx.users_get_current_account()
            st.success(f"✔ Authenticated as: {account.name.display_name}")

            # List all PDFs under the given folder
            pdfs = gather_all_pdfs(dbx, folder_path)
            st.write(f"Found {len(pdfs)} PDF(s) in the specified folder.")

            # Generate the markdown lines (with progress & cancel support)
            lines = generate_sources(
                dbx,
                pdfs,
                cancel_flag=lambda: st.session_state["cancel"],
                filter_keyword=filter_keyword
            )

            # Ensure the filename ends with .md
            if not output_filename.lower().endswith(".md"):
                output_filename += ".md"

            # Create an in‐memory text buffer and push to download button
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

