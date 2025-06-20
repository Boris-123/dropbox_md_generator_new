import dropbox
import sys
from collections import defaultdict
import os

# ─── CONFIGURATION ──────────────────────────────────────────────────────────────
TOKEN = "sl.u.AFzLF4g8Qq_AXXXZdZ0J4urxijLP0mAkc_S7o9q_acv2tpR2dfS7Jb8VEU-dukzyPidMPrijl-6nGFeM2eOof8KvblyhETaQqrPsAKGJxDUggGQmrrInSZRppbthHu4GYrlC4RJ4l5ftN8XIY3Cev0LJhPqDz1o6ddSW5oUMIZ5_a5sJrJxOCUU0WywMNuZqfqo4D7NYl_xB6CaFztyY9-wVu1aUZPSrk-NEOTLqznbpB95tP9E8xzXnoX7ZPecL-7ygnUWjEDq0PO839LHFCK5COkYryPLC9pK2PBoEmrYvvO1u5wQk9oWbLqlXehdTiVj9F5sCfajxZNVYgy3PVY0T2tUAlB_46HFNv2HT3NjqectY8LN--WpjekWNxmK7FjJEPkFyCApoVcfjbA7ZbPkLWIOqU7VFF-Dak2p_hjK1h4Qx1GMETVEmHRsP0-3Sft5_kC81ZxGXSnMVFnRrm0RZ3zEeaWyiZCk_cuRofO9o1J558NQFF02quwCfcdqN1mS7uWnZKWm4z-D0nbRy4jF56_pSf_XB2PGR3dg3bzm8QdYNcOIWYW8yraZEKgNva4JmYa6cuDpGa9g0LGyYPz3yjABOdoNLaCB9SK2FzNlMHPJjKaWM2ISQECZffDYgQ-vv7AYMSpZp_29rQTE86daDcodEwXjNjBjdVxGcq9w3FjIS8NDpuH_wbeKt5yBnUamggahY2xIlq4E8iNO5QDuW_-O184bpUkimKm1CHrYky10ltOwTLjJ9G9LmweiCNv8si9opGiWItLWhIQR0OcAZg4ZIFGDrvdJqgSl-OcaS-iDU77u_Q4KoWjEx6TBtrPbCDb-Q-gBlt8CftM9hCQ1UmrGSvNQjPpXc2SYztZrQSctyw-h5DoZPT--hijA9wIbPcpa3izXnwUKpsur0A66EMGUuwo0Z7hkTu3ewqq6IIN3GX0hyL89dA7Vw1oallXnF2EA8RAl-OfaYaQtClUTGFobgLYez6BCePL0TVoxIDmpv7dJK-S_zkt5n2qoMW1H87Q39x1-9G-VbpUaZFoztfC6PXSy5rcdQvN4CfI-5jDnJkdPI6j3zVuhFHxCHrjSCuot5enMxIQ8ttWFsGohemF38nOd9L5lY0aKbeXFqhxsdzDJlCGcoAqL7SvHAbHV9SRz4gE5wiykl6ySE2PZtbT72PkLNPt63vVpApolYCTIiDtqCeBs08hH_UU4wNh1JkXMjTcqb5-xJBRxYZZ3pOUn8wnzKEOFM6aoBpFw8sVeVQWoPdOd_HHHBB4BE6wOxCxaEaGIvo2IR3tc0umwHo59P5iSOXarL2_ZZAlETMdFbgzJhztU4yrRPf7Ra4v6qBPfAj92J0ZpuVU1999srcT1t9SAKJY1IhgG-yTgIpOClmmeRd9p4N1jPfv9XStU"      # ← Paste your Dropbox OAuth2 token here
DROPBOX_FOLDER = "/PIAS testing"        # ← The root Dropbox folder path to scan
OUTPUT_FILE = "Sources.md"              # ← The output Markdown file name
# ─── END CONFIGURATION ──────────────────────────────────────────────────────────

def force_direct_download(url: str) -> str: 
    # Convert "&dl=0" to "&dl=1" for direct download links
    return url.replace("&dl=0", "&dl=1")

def gather_all_pdfs(dbx: dropbox.Dropbox, path: str):
    """Recursively list all PDF file entries under the given path."""
    result = dbx.files_list_folder(path, recursive=True)
    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)
    # Filter for PDF metadata only
    return [e for e in entries
            if isinstance(e, dropbox.files.FileMetadata)
            and e.name.lower().endswith(".pdf")]

def generate_sources(dbx: dropbox.Dropbox, pdfs: list):
    """Generate Markdown lines with progress for each PDF."""
    total = len(pdfs)
    grouped = defaultdict(list)

    for item in pdfs:
        # Full relative folder path under root (skip root level)
        parts = item.path_display.strip("/").split("/")
        if len(parts) > 2:
            # Join everything after root (e.g., "Forms/New Reps")
            folder_path = "/".join(parts[1:-1])
        elif len(parts) == 2:   
            # Directly under root (e.g., "Forms")
            folder_path = parts[1]
        else:
            folder_path = "Uncategorized"
        grouped[folder_path].append(item)

    lines = ["# Document Sources\n\n"]
    progress_count = 1
    for folder in sorted(grouped.keys()):
        lines.append(f"## {folder}\n\n")
        for item in grouped[folder]:
            print(f"[{progress_count}/{total}] Processing: {item.name}")
            progress_count += 1
            try:
                # Try to get an existing share link, otherwise create one
                links = dbx.sharing_list_shared_links(path=item.path_lower,
                                                    direct_only=True).links
                share_url = links[0].url if links else \
                            dbx.sharing_create_shared_link_with_settings(item.path_lower).url

                # Force direct download
                direct_url = force_direct_download(share_url)

                # Build Markdown entry
                title = os.path.splitext(item.name)[0]
                lines.append(f"- [{title}]({direct_url})\n\n\n")
            except Exception as e:
                print(f"  ⚠️ Failed to get link for {item.path_lower}: {e}")
    return lines

def main():
    dbx = dropbox.Dropbox(TOKEN)
    try:
        account = dbx.users_get_current_account()
        print("Authenticated as:", account.email)
    except Exception as e:
        print("❌ Authentication failed:", e)
        sys.exit(1)

    pdfs = gather_all_pdfs(dbx, DROPBOX_FOLDER)
    print(f"Found {len(pdfs)} PDF files under '{DROPBOX_FOLDER}'.\n")

    md_lines = generate_sources(dbx, pdfs)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(md_lines)
    print(f"\n✅ Successfully wrote {OUTPUT_FILE} with {len(pdfs)} entries.")

if __name__ == "__main__":
    main()
