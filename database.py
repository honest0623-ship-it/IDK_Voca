import sqlite3
import pandas as pd
import streamlit as st
import os
from datetime import datetime

DB_FILE = "voca.db"

def get_db_connection():
    """DB 연결 가져오기 (없으면 생성)"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """데이터베이스 초기화 (테이블 생성)"""
    if os.path.exists(DB_FILE):
        return # 이미 DB 파일이 있으면 실행하지 않음

    conn = get_db_connection()
    c = conn.cursor()

    # --- 테이블 생성 ---
    # 1. users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT,
            level INTEGER DEFAULT 1
        )
    ''')

    # 2. voca_db
    c.execute('''
        CREATE TABLE IF NOT EXISTS voca_db (
            id INTEGER PRIMARY KEY,
            target_word TEXT NOT NULL,
            meaning TEXT,
            level INTEGER DEFAULT 1,
            sentence_en TEXT,
            sentence_ko TEXT,
            root_word TEXT,
            total_try INTEGER DEFAULT 0,
            total_wrong INTEGER DEFAULT 0
        )
    ''')

    # 3. user_progress
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            word_id INTEGER,
            last_reviewed DATE,
            next_review DATE,
            interval INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            FOREIGN KEY (username) REFERENCES users (username),
            FOREIGN KEY (word_id) REFERENCES voca_db (id)
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_progress_user_word ON user_progress (username, word_id)')


    # 4. study_log
    c.execute('''
        CREATE TABLE IF NOT EXISTS study_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            date DATE,
            word_id INTEGER,
            username TEXT,
            level INTEGER,
            is_correct INTEGER,
            FOREIGN KEY (username) REFERENCES users (username),
            FOREIGN KEY (word_id) REFERENCES voca_db (id)
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_log_username ON study_log (username)')


    conn.commit()
    conn.close()
    st.info(f"데이터베이스 '{DB_FILE}'가 생성되었습니다.")

# --- 데이터 읽기 함수 ---

@st.cache_data(ttl=60)
def load_all_vocab():
    """voca_db 전체 로드 (기존 load_data 대체)"""
    init_db() # DB 없으면 생성
    conn = get_db_connection()
    df = pd.read_sql('SELECT * FROM voca_db', conn)
    conn.close()
    return df

def get_user_info(username):
    """사용자 정보 가져오기 (기존 get_user_info 대체)"""
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    if user:
        return dict(user)
    return None

def load_user_progress(username):
    """사용자 학습 진도 로드 (기존 load_user_progress 대체)"""
    conn = get_db_connection()
    df = pd.read_sql('SELECT * FROM user_progress WHERE username = ?', conn, params=(username,))
    
    # 날짜 컬럼 파싱
    for col in ['next_review', 'last_reviewed']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.date
    conn.close()
    return df

def load_study_log(username):
    """사용자 학습 로그 로드"""
    conn = get_db_connection()
    df = pd.read_sql('SELECT * FROM study_log WHERE username = ?', conn, params=(username,))
    conn.close()
    return df

def get_all_users():
    """모든 사용자 정보 로드 (관리자용)"""
    conn = get_db_connection()
    df = pd.read_sql('SELECT username, name, level FROM users', conn)
    conn.close()
    return df

def get_all_study_logs():
    """모든 학습 로그 로드 (관리자용)"""
    conn = get_db_connection()
    df = pd.read_sql('SELECT * FROM study_log', conn)
    conn.close()
    return df


# --- 데이터 쓰기 함수 ---

def register_user(username, password, name):
    """사용자 등록 (기존 register_user 대체)"""
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (username, password, name, level) VALUES (?, ?, ?, ?)',
            (username, password, name, 1) # 기본 레벨 1
        )
        conn.commit()
        return "SUCCESS"
    except sqlite3.IntegrityError:
        return "EXIST" # Primary Key 중복
    except Exception as e:
        print(f"Error registering user: {e}")
        return "ERROR"
    finally:
        conn.close()

def update_user_level(username, new_level):
    """사용자 레벨 업데이트"""
    conn = get_db_connection()
    try:
        conn.execute('UPDATE users SET level = ? WHERE username = ?', (new_level, username))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating user level: {e}")
        return False
    finally:
        conn.close()

def reset_user_password(username, new_password_hash):
    """비밀번호 초기화"""
    conn = get_db_connection()
    try:
        conn.execute('UPDATE users SET password = ? WHERE username = ?', (new_password_hash, username))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error resetting password: {e}")
        return False
    finally:
        conn.close()

def save_user_progress(username, progress_df):
    """사용자 진도 저장 (기존 save_progress 대체) - 훨씬 효율적!"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # 1. 해당 유저의 기존 progress 모두 삭제
        c.execute("DELETE FROM user_progress WHERE username = ?", (username,))
        
        # 2. progress_df에 있는 내용 새로 삽입
        if not progress_df.empty:
            # 날짜 객체를 문자열로 변환
            df_to_save = progress_df.copy()
            df_to_save['last_reviewed'] = df_to_save['last_reviewed'].astype(str)
            df_to_save['next_review'] = df_to_save['next_review'].astype(str)
            df_to_save['username'] = username # 혹시 모르니 username 다시 한번 확인

            # id 컬럼이 있다면 제거 (자동 증가이므로)
            if 'id' in df_to_save.columns:
                df_to_save = df_to_save.drop(columns=['id'])

            df_to_save.to_sql('user_progress', conn, if_exists='append', index=False)
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error saving progress: {e}")
        return False
    finally:
        conn.close()


def batch_log_study_results(log_buffer):
    """학습 로그 일괄 저장 (기존 batch_log_study_results 대체)"""
    if not log_buffer:
        return True
        
    conn = get_db_connection()
    try:
        log_df = pd.DataFrame(log_buffer, columns=['timestamp', 'date', 'word_id', 'username', 'level', 'is_correct'])
        log_df.to_sql('study_log', conn, if_exists='append', index=False)
        conn.commit()
        return True
    except Exception as e:
        print(f"Error batch logging results: {e}")
        return False
    finally:
        conn.close()

def update_vocab_stats(updates):
    """단어 통계(total_try, total_wrong) 업데이트"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.executemany(
            'UPDATE voca_db SET total_try = total_try + ?, total_wrong = total_wrong + ? WHERE id = ?',
            updates # [(try_increment, wrong_increment, word_id), ...]
        )
        conn.commit()
    except Exception as e:
        print(f"Error updating vocab stats: {e}")
    finally:
        conn.close()
