import os
import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from oauth2client.service_account import ServiceAccountCredentials
import io
from datetime import datetime

# 설정
SCOPES = ['https://www.googleapis.com/auth/drive']
DB_FILE = 'voca.db'
FOLDER_NAME = 'VocaDB_Backup' # 구글 드라이브 내 백업 폴더 이름
FIXED_FILENAME = 'voca_backup_latest.db' # [FIX] 단일 파일 덮어쓰기용 고정 파일명

def get_drive_service():
    """구글 드라이브 서비스 객체 생성"""
    try:
        gcp_info = dict(st.secrets["gcp_service_account"])
        if "private_key" in gcp_info:
            gcp_info["private_key"] = gcp_info["private_key"].replace("\n", "\n")
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_info, SCOPES)
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        st.error(f"구글 드라이브 연결 실패: {e}")
        return None

def _find_folder(service, folder_name):
    """폴더 ID 찾기"""
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    # [FIX] Shared Drive 지원 추가
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name)',
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    return None

def _create_folder(service, folder_name):
    """폴더 생성"""
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    # [FIX] Shared Drive 지원 추가
    file = service.files().create(
        body=file_metadata, 
        fields='id',
        supportsAllDrives=True
    ).execute()
    return file.get('id')

def _find_file_in_folder(service, folder_id, filename):
    """폴더 내 파일 ID 찾기"""
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    # [FIX] Shared Drive 지원 추가
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name)',
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    return None

def list_backups(limit=20):
    """
    [복구] 백업 파일 목록 가져오기
    Return: list of dict {'id', 'name', 'createdTime', 'size'}
    """
    service = get_drive_service()
    if not service: return []

    folder_id = _find_folder(service, FOLDER_NAME)
    if not folder_id: return []

    # [FIX] 고정 파일명 검색
    query = f"name = '{FIXED_FILENAME}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name, createdTime, size)',
        orderBy='createdTime desc',
        pageSize=limit,
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True
    ).execute()
    
    return results.get('files', [])

def create_backup(note=""):
    """
    [백업] 단일 파일 덮어쓰기 모드
    """
    return upload_db_to_drive()

def restore_backup(file_id):
    """
    [복구] 특정 파일 ID의 내용을 voca.db로 덮어쓰기
    """
    service = get_drive_service()
    if not service: return False

    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        # 기존 DB 덮어쓰기
        with open(DB_FILE, 'wb') as f:
            f.write(fh.getvalue())
        
        return True
    except Exception as e:
        print(f"Restore Error: {e}")
        return False

def download_db_from_drive():
    """
    [복구] 구글 드라이브에서 DB 다운로드
    """
    service = get_drive_service()
    if not service: return False

    folder_id = _find_folder(service, FOLDER_NAME)
    if not folder_id:
        return False

    # [FIX] 고정 파일명 사용
    file_id = _find_file_in_folder(service, folder_id, FIXED_FILENAME)
    if not file_id:
        return False

    # 다운로드 실행
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        with open(DB_FILE, 'wb') as f:
            f.write(fh.getvalue())
        
        return True
    except Exception as e:
        print(f"Download Error: {e}")
        return False

def upload_db_to_drive():
    """
    [백업] 로컬 DB를 구글 드라이브로 업로드 (단일 파일 덮어쓰기)
    """
    if not os.path.exists(DB_FILE):
        return False

    service = get_drive_service()
    if not service: return False

    try:
        # 1. 백업 폴더 확인
        folder_id = _find_folder(service, FOLDER_NAME)
        if not folder_id:
            # 폴더 생성 시도 (폴더 생성은 권한에 따라 실패할 수도 있음)
            try:
                folder_id = _create_folder(service, FOLDER_NAME)
            except:
                st.error(f"구글 드라이브에 '{FOLDER_NAME}' 폴더를 찾을 수 없습니다. 직접 생성해주세요.")
                return False

        # 2. 기존 파일 확인
        file_id = _find_file_in_folder(service, folder_id, FIXED_FILENAME)

        media = MediaFileUpload(DB_FILE, mimetype='application/x-sqlite3', resumable=True)

        if file_id:
            # [CASE 1] 파일이 있으면 -> 업데이트 (OK)
            updated_metadata = {'name': FIXED_FILENAME, 'mimeType': 'application/x-sqlite3'}
            service.files().update(
                fileId=file_id, 
                body=updated_metadata, 
                media_body=media,
                supportsAllDrives=True
            ).execute()
            return True, f"백업 업데이트 완료 ({FIXED_FILENAME})"
        else:
            # [CASE 2] 파일이 없으면 -> 생성 시도 (하지만 개인 계정 공유 시 403 에러 발생 가능)
            try:
                file_metadata = {
                    'name': FIXED_FILENAME,
                    'parents': [folder_id]
                }
                service.files().create(
                    body=file_metadata, 
                    media_body=media, 
                    fields='id',
                    supportsAllDrives=True
                ).execute()
                return True, f"새 백업 파일 생성 완료 ({FIXED_FILENAME})"
            except Exception as e:
                err_str = str(e)
                if "storageQuotaExceeded" in err_str or "403" in err_str:
                    st.error(f"⚠️ 업로드 권한 오류: '{FOLDER_NAME}' 폴더 안에 '{FIXED_FILENAME}' 이름의 빈 파일을 직접 만들고 봇에게 편집 권한을 주세요.")
                    return False
                print(f"Upload Create Error: {e}")
                return False
                
    except Exception as e:
        print(f"Upload Error: {e}")
        return False
