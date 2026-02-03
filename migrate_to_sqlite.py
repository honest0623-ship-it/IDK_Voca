import pandas as pd
import streamlit as st
import os
import sqlite3

# 기존 구글 시트 로직과 새로운 DB 로직을 모두 임포트
import utils as old_utils 
import database as db

def migrate():
    """
    구글 시트에서 데이터를 읽어와 SQLite DB에 저장하는 마이그레이션 스크립트.
    DB 파일이 이미 존재하면 실행되지 않습니다.
    """
    if os.path.exists(db.DB_FILE):
        conn = sqlite3.connect(db.DB_FILE)
        # 간단하게 users 테이블에 데이터가 있는지 확인
        try:
            count = pd.read_sql(f"SELECT COUNT(*) FROM users", conn).iloc[0, 0]
            if count > 0:
                st.warning(f"이미 '{db.DB_FILE}' 데이터베이스에 데이터가 존재합니다. 마이그레이션을 건너뜁니다.")
                conn.close()
                return
        except pd.io.sql.DatabaseError:
             # 테이블이 아직 없을 수 있음
             pass
        conn.close()


    st.info(f"'{db.DB_FILE}' 데이터베이스를 초기화합니다...")
    db.init_db() # DB 및 테이블 생성

    st.info("구글 시트에서 데이터를 읽어옵니다. 잠시만 기다려주세요...")

    conn = db.get_db_connection()

    try:
        # 1. voca_db 마이그레이션
        st.write("- 단어 DB (voca_db) 마이그레이션 중...")
        voca_df = old_utils.read_sheet_to_df('voca_db')
        if not voca_df.empty:
            # 데이터 클리닝
            voca_df = voca_df[['id', 'target_word', 'meaning', 'level', 'sentence_en', 'sentence_ko', 'root_word', 'total_try', 'total_wrong']]
            voca_df['level'] = pd.to_numeric(voca_df['level'], errors='coerce').fillna(1).astype(int)
            voca_df['id'] = pd.to_numeric(voca_df['id'], errors='coerce').fillna(0).astype(int)
            voca_df.to_sql('voca_db', conn, if_exists='replace', index=False)
            st.success(f"  > {len(voca_df)}개 단어 완료.")
        else:
            st.warning("  > voca_db 시트에 데이터가 없습니다.")

        # 2. users 마이그레이션
        st.write("- 사용자 (users) 마이그레이션 중...")
        users_df = old_utils.read_sheet_to_df('users')
        if not users_df.empty:
            users_df = users_df[['username', 'password', 'name', 'level']]
            users_df['level'] = pd.to_numeric(users_df['level'], errors='coerce').fillna(1).astype(int)
            users_df.to_sql('users', conn, if_exists='replace', index=False)
            st.success(f"  > {len(users_df)}명 사용자 완료.")
        else:
            st.warning("  > users 시트에 데이터가 없습니다.")

        # 3. user_progress 마이그레이션
        st.write("- 학습 진도 (user_progress) 마이그레이션 중...")
        progress_df = old_utils.read_sheet_to_df('user_progress')
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
            progress_df = progress_df.dropna(subset=['username'])

            progress_df = progress_df[['username', 'word_id', 'last_reviewed', 'next_review', 'interval', 'fail_count']]
            progress_df.to_sql('user_progress', conn, if_exists='append', index=False)
            st.success(f"  > {len(progress_df)}개 학습 기록 완료.")
        else:
            st.warning("  > user_progress 시트에 데이터가 없습니다.")

        # 4. study_log 마이그레이션
        st.write("- 학습 로그 (study_log) 마이그레이션 중...")
        log_df = old_utils.read_sheet_to_df('study_log')
        if not log_df.empty:
            log_df['word_id'] = pd.to_numeric(log_df['word_id'], errors='coerce').astype(int)
            log_df['level'] = pd.to_numeric(log_df['level'], errors='coerce').astype(int)
            log_df['is_correct'] = pd.to_numeric(log_df['is_correct'], errors='coerce').astype(int)
            log_df['timestamp'] = pd.to_datetime(log_df['timestamp']).astype(str)
            log_df['date'] = pd.to_datetime(log_df['date']).dt.date.astype(str)

            log_df = log_df[['timestamp', 'date', 'word_id', 'username', 'level', 'is_correct']]
            log_df.to_sql('study_log', conn, if_exists='append', index=False)
            st.success(f"  > {len(log_df)}개 로그 완료.")
        else:
            st.warning("  > study_log 시트에 데이터가 없습니다.")

        st.balloons()
        st.header("🎉 데이터 마이그레이션이 성공적으로 완료되었습니다!")
        st.info("이제 앱은 로컬 SQLite 데이터베이스를 사용하여 훨씬 빠르게 동작합니다.")

    except Exception as e:
        st.error(f"마이그레이션 중 오류가 발생했습니다: {e}")
        # 오류 발생 시 생성된 DB 파일 삭제
        conn.close()
        if os.path.exists(db.DB_FILE):
            os.remove(db.DB_FILE)
        st.warning(f"오류로 인해 생성되었던 '{db.DB_FILE}' 파일을 삭제했습니다.")
    finally:
        conn.close()

if __name__ == "__main__":
    st.title("데이터베이스 마이그레이션")
    st.write("구글 시트의 데이터를 로컬 SQLite 데이터베이스로 옮깁니다.")
    
    if st.button("🚀 마이그레이션 시작하기"):
        migrate()
