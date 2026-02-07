import os
import toml
import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials

# 1. Load Secrets manually (since we are running as a script, not via streamlit run)
secrets_path = os.path.join(".streamlit", "secrets.toml")
if os.path.exists(secrets_path):
    with open(secrets_path, "r", encoding="utf-8") as f:
        secrets_data = toml.load(f)
else:
    print("Error: .streamlit/secrets.toml not found.")
    exit(1)

# 2. Setup Google Drive Service
SCOPES = ['https://www.googleapis.com/auth/drive']
DB_FILE = 'voca.db'
FOLDER_NAME = 'VocaDB_Backup'
FIXED_FILENAME = 'voca_backup_latest.db' # [FIX]

try:
    gcp_info = secrets_data["gcp_service_account"]
    # Fix private key newline issue
    if "private_key" in gcp_info:
        gcp_info["private_key"] = gcp_info["private_key"].replace("\n", "\n")
        
    creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_info, SCOPES)
    service = build('drive', 'v3', credentials=creds)
except Exception as e:
    print(f"Auth Error: {e}")
    exit(1)

# 3. Upload Logic (Simplified from drive_sync.py)
def _find_folder(service, folder_name):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    # [FIX] Shared Drive Support
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name)',
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    return None

def _create_folder(service, folder_name):
    file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    # [FIX] Shared Drive Support
    file = service.files().create(
        body=file_metadata, 
        fields='id',
        supportsAllDrives=True
    ).execute()
    return file.get('id')

def _find_file_in_folder(service, folder_id, filename):
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    # [FIX] Shared Drive Support
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name)',
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    return None

print("Starting backup (Single File Mode)...")
try:
    if not os.path.exists(DB_FILE):
        print(f"Error: {DB_FILE} not found localy.")
        exit(1)

    folder_id = _find_folder(service, FOLDER_NAME)
    if not folder_id:
        print(f"Creating folder: {FOLDER_NAME}...")
        try:
            folder_id = _create_folder(service, FOLDER_NAME)
        except Exception as e:
            print(f"Folder Create Error: {e}")
            print(f"Please create '{FOLDER_NAME}' manually.")
            exit(1)
    else:
        print(f"Found existing folder: {FOLDER_NAME}")

    file_id = _find_file_in_folder(service, folder_id, FIXED_FILENAME)
    
    media = MediaFileUpload(DB_FILE, mimetype='application/x-sqlite3', resumable=True)
    
    if file_id:
        print(f"Updating existing file ({FIXED_FILENAME})...")
        file_metadata = {'name': FIXED_FILENAME, 'mimeType': 'application/x-sqlite3'}
        service.files().update(
            fileId=file_id, 
            body=file_metadata, 
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print("Backup SUCCESS!")
    else:
        print(f"Creating new file ({FIXED_FILENAME})...")
        try:
            file_metadata = {'name': FIXED_FILENAME, 'parents': [folder_id]}
            service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id',
                supportsAllDrives=True
            ).execute()
            print("Backup SUCCESS!")
        except Exception as e:
             if "storageQuotaExceeded" in str(e) or "403" in str(e):
                 print("\n[ERROR] Service Account Storage Quota Exceeded.")
                 print(f"Please create an empty file named '{FIXED_FILENAME}' inside '{FOLDER_NAME}' folder")
                 print("and share it with the service account email.")
             else:
                 print(f"Error: {e}")

except Exception as e:
    print(f"Backup FAILED: {e}")

