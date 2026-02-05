import pandas as pd
import streamlit as st
import os
import sqlite3
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

import database as db

# --- 구글 시트 연결 (마이그레이션용) ---
def get_google_sheet_client():
    SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        gcp_info = dict(st.secrets["gcp_service_account"])
        if "private_key" in gcp_info:
            gcp_info["private_key"] = gcp_info["private_key"].replace("\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_info, SCOPE)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"구글 시트 연결 실패: {e}")
        return None

def read_sheet_to_df(client, tab_name):
    try:
        sh = client.open("Voca_DB") # 시트 이름 하드코딩 (utils.py와 동일)
        ws = sh.worksheet(tab_name)
        data = ws.get_all_values()
        if not data or len(data) < 2:
            return pd.DataFrame()
        
        headers = data[0]
        # 헤더 보정 (users)
        if tab_name == 'users' and 'username' not in headers:
            if len(headers) >= 4:
                headers = ['username', 'password', 'name', 'level'] + headers[4:]
        
        df = pd.DataFrame(data[1:], columns=headers)
        return df
    except Exception as e:
        st.warning(f"'{tab_name}' 시트 읽기 실패: {e}")
        return pd.DataFrame()

def migrate(force_overwrite=False):
    """
    구글 시트 -> SQLite 마이그레이션
    """
    if os.path.exists(db.DB_FILE) and not force_overwrite:
        conn = sqlite3.connect(db.DB_FILE)
        try:
            # users 테이블에 데이터가 있는지 확인
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if cursor.fetchone():
                count = pd.read_sql(f"SELECT COUNT(*) FROM users", conn).iloc[0, 0]
                if count > 0:
                    st.warning(f"이미 '{db.DB_FILE}' 데이터베이스에 데이터가 존재합니다. 마이그레이션을 건너뜁니다.")
                    st.info("덮어쓰려면 '기존 데이터 삭제 후 덮어쓰기'를 체크하세요.")
                    conn.close()
                    return
        except Exception as e:
             pass
        conn.close()

    if force_overwrite and os.path.exists(db.DB_FILE):
        try:
            os.remove(db.DB_FILE)
            st.warning(f"기존 '{db.DB_FILE}' 파일을 삭제했습니다.")
        except Exception as e:
            st.error(f"기존 파일 삭제 실패: {e}")
            return

    st.info(f"'{db.DB_FILE}' 데이터베이스를 초기화합니다...")
    db.init_db() # DB 및 테이블 생성

    st.info("구글 시트에서 데이터를 읽어옵니다. 잠시만 기다려주세요...")
    
    client = get_google_sheet_client()
    if not client:
        return

    conn = db.get_db_connection()

    try:
        # 1. voca_db 마이그레이션
        st.write("- 단어 DB (voca_db) 마이그레이션 중...")
        voca_df = read_sheet_to_df(client, 'voca_db')
        if not voca_df.empty:
            # 데이터 클리닝
            cols = ['id', 'target_word', 'meaning', 'level', 'sentence_en', 'sentence_ko', 'root_word', 'total_try', 'total_wrong']
            # 존재하는 컬럼만 선택
            voca_df = voca_df[[c for c in cols if c in voca_df.columns]]
            
            if 'level' in voca_df.columns:
                voca_df['level'] = pd.to_numeric(voca_df['level'], errors='coerce').fillna(1).astype(int)
            if 'id' in voca_df.columns:
                voca_df['id'] = pd.to_numeric(voca_df['id'], errors='coerce').fillna(0).astype(int)
            
            voca_df.to_sql('voca_db', conn, if_exists='replace', index=False)
            st.success(f"  > {len(voca_df)}개 단어 완료.")
        else:
            st.warning("  > voca_db 시트에 데이터가 없습니다.")

        # 2. users 마이그레이션
        st.write("- 사용자 (users) 마이그레이션 중...")
        users_df = read_sheet_to_df(client, 'users')
        if not users_df.empty:
            # 필수 컬럼 외 동적 필드도 처리해야 함.
            # 하지만 database.py의 users 테이블 스키마에 맞춰야 함.
            # database schema: username, password, name, level, fail_streak, level_shield, qs_count, pending_wrongs, pending_session
            
            # 1) 기본 컬럼
            base_cols = ['username', 'password', 'name', 'level']
            # 2) 추가 컬럼 (시트에 있다면 가져오고, 없으면 기본값)
            extra_cols = ['fail_streak', 'level_shield', 'qs_count', 'pending_wrongs', 'pending_session']
            
            # 시트 컬럼 정리
            available_cols = users_df.columns.tolist()
            
            final_users = pd.DataFrame()
            for col in base_cols:
                if col in available_cols:
                    final_users[col] = users_df[col]
                else:
                    final_users[col] = '' # Should not happen for base cols
            
            if 'level' in final_users.columns:
                final_users['level'] = pd.to_numeric(final_users['level'], errors='coerce').fillna(1).astype(int)
            
            # 추가 컬럼 처리
            for col in extra_cols:
                if col in available_cols:
                    if col in ['fail_streak', 'level_shield', 'qs_count']:
                        final_users[col] = pd.to_numeric(users_df[col], errors='coerce').fillna(0).astype(int)
                    else:
                        final_users[col] = users_df[col]
                else:
                    # 기본값 설정
                    if col == 'level_shield': val = 3
                    elif col in ['fail_streak', 'qs_count']: val = 0
                    else: val = ''
                    final_users[col] = val

            final_users.to_sql('users', conn, if_exists='replace', index=False)
            st.success(f"  > {len(final_users)}명 사용자 완료.")
        else:
            st.warning("  > users 시트에 데이터가 없습니다.")

        # 3. user_progress 마이그레이션
        st.write("- 학습 진도 (user_progress) 마이그레이션 중...")
        progress_df = read_sheet_to_df(client, 'user_progress')
        if not progress_df.empty:
            # 데이터 타입 정리
            progress_df['word_id'] = pd.to_numeric(progress_df['word_id'], errors='coerce')
            progress_df = progress_df.dropna(subset=['word_id'])
            progress_df['word_id'] = progress_df['word_id'].astype(int)
            progress_df['last_reviewed'] = pd.to_datetime(progress_df['last_reviewed'], errors='coerce').dt.date.astype(str)
            progress_df['next_review'] = pd.to_datetime(progress_df['next_review'], errors='coerce').dt.date.astype(str)
            progress_df['interval'] = pd.to_numeric(progress_df['interval'], errors='coerce').fillna(0).astype(int)
            progress_df['fail_count'] = pd.to_numeric(progress_df['fail_count'], errors='coerce').fillna(0).astype(int)
            
            # username 이 없는 행 제거
            if 'username' in progress_df.columns:
                progress_df = progress_df.dropna(subset=['username'])

            cols = ['username', 'word_id', 'last_reviewed', 'next_review', 'interval', 'fail_count']
            progress_df = progress_df[[c for c in cols if c in progress_df.columns]]
            
            progress_df.to_sql('user_progress', conn, if_exists='append', index=False)
            st.success(f"  > {len(progress_df)}개 학습 기록 완료.")
        else:
            st.warning("  > user_progress 시트에 데이터가 없습니다.")

        # 4. study_log 마이그레이션
        st.write("- 학습 로그 (study_log) 마이그레이션 중...")
        log_df = read_sheet_to_df(client, 'study_log')
        if not log_df.empty:
            log_df['word_id'] = pd.to_numeric(log_df['word_id'], errors='coerce').astype(int)
            log_df['level'] = pd.to_numeric(log_df['level'], errors='coerce').astype(int)
            log_df['is_correct'] = pd.to_numeric(log_df['is_correct'], errors='coerce').astype(int)
            log_df['timestamp'] = pd.to_datetime(log_df['timestamp']).astype(str)
            log_df['date'] = pd.to_datetime(log_df['date']).dt.date.astype(str)

            cols = ['timestamp', 'date', 'word_id', 'username', 'level', 'is_correct']
            log_df = log_df[[c for c in cols if c in log_df.columns]]
            
            log_df.to_sql('study_log', conn, if_exists='append', index=False)
            st.success(f"  > {len(log_df)}개 로그 완료.")
        else:
            st.warning("  > study_log 시트에 데이터가 없습니다.")
            
        # 5. config 마이그레이션
        st.write("- 설정 (config) 마이그레이션 중...")
        config_df = read_sheet_to_df(client, 'config')
        if not config_df.empty and 'key' in config_df.columns and 'value' in config_df.columns:
             config_df = config_df[['key', 'value']]
             config_df.to_sql('config', conn, if_exists='replace', index=False)
             st.success(f"  > {len(config_df)}개 설정 완료.")

        st.balloons()
        st.header("🎉 데이터 마이그레이션이 성공적으로 완료되었습니다!")
        st.info("이제 앱은 로컬 SQLite 데이터베이스를 사용하여 훨씬 빠르게 동작합니다.")

    except Exception as e:
        st.error(f"마이그레이션 중 오류가 발생했습니다: {e}")
        # 오류 발생 시 생성된 DB 파일 삭제
        conn.close()
        if os.path.exists(db.DB_FILE):
             # 안전을 위해 삭제는 보류하거나 경고만
             pass
        st.warning("오류가 발생했습니다. 로그를 확인하세요.")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    st.set_page_config(page_title="DB Migration", page_icon="📦")
    st.title("데이터베이스 마이그레이션")
    st.markdown("""
    **Google Sheets**의 데이터를 **로컬 SQLite** 데이터베이스로 옮깁니다.
    
    ⚠️ **주의사항**
    - 마이그레이션 중에는 앱 사용을 중지해주세요.
    - 기존 `voca.db` 파일이 있다면 덮어쓰거나 건너뛸 수 있습니다.
    """)
    
    force = st.checkbox("🗑 기존 데이터 삭제 후 덮어쓰기 (강제 실행)", value=False)
    
    if st.button("🚀 마이그레이션 시작하기", type="primary"):
        migrate(force_overwrite=force)