import os
import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from oauth2client.service_account import ServiceAccountCredentials
import io

# 설정
SCOPES = ['https://www.googleapis.com/auth/drive']
DB_FILE = 'voca.db'
FOLDER_NAME = 'VocaDB_Backup' # 구글 드라이브 내 백업 폴더 이름

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
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
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
    file = service.files().create(body=file_metadata, fields='id').execute()
    return file.get('id')

def _find_file_in_folder(service, folder_id, filename):
    """폴더 내 파일 ID 찾기"""
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    return None

def download_db_from_drive():
    """
    [복구] 구글 드라이브에서 DB 다운로드
    - 앱 시작 시 호출
    """
    if os.path.exists(DB_FILE):
        # 로컬에 이미 있으면 다운로드 건너뛸 수도 있지만,
        # 클라우드 환경(Streamlit Cloud)에서는 재부팅 시 사라지므로
        # 확실히 하기 위해 최신 버전을 받는 게 안전함.
        # 단, 로컬 개발 환경에서는 매번 덮어쓰면 곤란할 수 있으니 주의.
        # 여기서는 "로컬 파일이 없으면 다운로드" 전략을 기본으로 하되,
        # 배포 환경을 고려해 항상 다운로드가 나을 수 있음.
        # -> 전략: "DB_FILE"이 없으면 다운로드.
        #    있으면? (개발 중엔 유지, 배포 땐 어차피 없음)
        pass

    service = get_drive_service()
    if not service: return False

    folder_id = _find_folder(service, FOLDER_NAME)
    if not folder_id:
        # 폴더가 없으면 백업된 적도 없음
        return False

    file_id = _find_file_in_folder(service, folder_id, DB_FILE)
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
    [백업] 로컬 DB를 구글 드라이브로 업로드
    - 학습 종료 시 호출
    """
    if not os.path.exists(DB_FILE):
        return False

    service = get_drive_service()
    if not service: return False

    # 1. 백업 폴더 확인/생성
    folder_id = _find_folder(service, FOLDER_NAME)
    if not folder_id:
        folder_id = _create_folder(service, FOLDER_NAME)

    # 2. 기존 파일 확인
    file_id = _find_file_in_folder(service, folder_id, DB_FILE)

    file_metadata = {
        'name': DB_FILE,
        'parents': [folder_id]
    }
    media = MediaFileUpload(DB_FILE, mimetype='application/x-sqlite3', resumable=True)

    try:
        if file_id:
            # 업데이트 (메타데이터 + 내용)
            updated_metadata = {'name': DB_FILE, 'mimeType': 'application/x-sqlite3'}
            service.files().update(fileId=file_id, body=updated_metadata, media_body=media).execute()
        else:
            # 새로 생성
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return True
    except Exception as e:
        print(f"Upload Error: {e}")
        return False
