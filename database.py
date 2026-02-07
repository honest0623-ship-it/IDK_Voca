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
    # if os.path.exists(DB_FILE):
    #    return # 이미 DB 파일이 있으면 실행하지 않음

    conn = get_db_connection()
    c = conn.cursor()

    # --- 테이블 생성 ---
    # 1. users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT,
            level INTEGER DEFAULT 1,
            fail_streak INTEGER DEFAULT 0,
            level_shield INTEGER DEFAULT 3,
            qs_count INTEGER DEFAULT 0,
            pending_wrongs TEXT DEFAULT '',
            pending_session TEXT DEFAULT ''
        )
    ''')

    # 2. voca_db
    c.execute('''
        CREATE TABLE IF NOT EXISTS voca_db (
            id INTEGER PRIMARY KEY,
            target_word TEXT NOT NULL,
            meaning TEXT,
            pos TEXT,
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

    # 5. config
    c.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    conn.commit()
    conn.close()

# --- 데이터 읽기 함수 ---

def get_system_config():
    """시스템 설정 로드"""
    conn = get_db_connection()
    try:
        # DB에 테이블이 있는지 확인 (마이그레이션 전일 수 있음)
        # 하지만 init_db가 호출되면 생성됨.
        rows = conn.execute('SELECT key, value FROM config').fetchall()
        config = {row['key']: row['value'] for row in rows}
        
        # 기본값 병합
        defaults = {'signup_code': '', 'admin_pw': ''}
        for k, v in defaults.items():
            if k not in config:
                config[k] = v
        return config
    except Exception as e:
        print(f"Error loading config: {e}")
        return {'signup_code': '', 'admin_pw': ''}
    finally:
        conn.close()

def update_system_config(key, value):
    """시스템 설정 업데이트"""
    conn = get_db_connection()
    try:
        conn.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating config: {e}")
        return False
    finally:
        conn.close()

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
    # 1. Exact Match
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    
    # 2. Case-insensitive Fallback (if not found)
    if not user:
        user = conn.execute('SELECT * FROM users WHERE lower(username) = lower(?)', (username,)).fetchone()
        
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

def get_full_users_dump():
    """모든 사용자 전체 정보 로드 (백업용)"""
    conn = get_db_connection()
    df = pd.read_sql('SELECT * FROM users', conn)
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
        # Check if user exists (Case-insensitive)
        exists = conn.execute('SELECT 1 FROM users WHERE lower(username) = lower(?)', (username,)).fetchone()
        if exists:
            return "EXIST"

        conn.execute(
            'INSERT INTO users (username, password, name, level, fail_streak, level_shield, qs_count, pending_wrongs, pending_session) VALUES (?, ?, ?, NULL, 0, 3, 0, "", "")',
            (username, password, name) # 기본 레벨 NULL (레벨 테스트 유도)
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

def update_user_dynamic_fields(username, updates):
    """
    사용자 동적 필드 업데이트
    updates: dict of {'col_name': value}
    Available cols: level, fail_streak, level_shield, qs_count, pending_wrongs, pending_session
    """
    conn = get_db_connection()
    try:
        # 허용된 컬럼만 필터링 (SQL Injection 방지)
        allowed_cols = ['level', 'fail_streak', 'level_shield', 'qs_count', 'pending_wrongs', 'pending_session']
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_cols}
        
        if not filtered_updates:
            return False

        set_clause = ", ".join([f"{k} = ?" for k in filtered_updates.keys()])
        values = list(filtered_updates.values())
        values.append(username)

        conn.execute(f'UPDATE users SET {set_clause} WHERE username = ?', values)
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating user dynamic fields: {e}")
        return False
    finally:
        conn.close()

def update_student_info(old_username, new_username, new_name, new_level):
    """학생 정보 수정 (ID, 이름, 레벨)"""
    conn = get_db_connection()
    try:
        # 1. ID 중복 체크 (ID가 변경된 경우)
        if old_username != new_username:
            exists = conn.execute('SELECT 1 FROM users WHERE username = ?', (new_username,)).fetchone()
            if exists:
                return "DUPLICATE"

        # 2. 업데이트 실행
        # SQLite에서는 PK 업데이트 시 Cascade 옵션이 없으면 자식 테이블 참조가 깨질 수 있음.
        # 따라서 PRAGMA foreign_keys = ON; 을 켜거나, 수동으로 자식 테이블도 업데이트해야 함.
        # 여기서는 수동 업데이트 방식을 사용 (안전하게)
        
        conn.execute("BEGIN TRANSACTION")
        
        if old_username != new_username:
            # 새 유저 생성 (기존 정보 복사)
            user_row = conn.execute('SELECT * FROM users WHERE username = ?', (old_username,)).fetchone()
            if not user_row:
                return "NOT_FOUND"
                
            user_data = dict(user_row)
            user_data['username'] = new_username
            user_data['name'] = new_name
            user_data['level'] = new_level
            
            # 새 레코드로 삽입
            cols = ', '.join(user_data.keys())
            placeholders = ', '.join(['?'] * len(user_data))
            conn.execute(f'INSERT INTO users ({cols}) VALUES ({placeholders})', list(user_data.values()))
            
            # 자식 테이블 업데이트 (username 참조 변경)
            conn.execute('UPDATE user_progress SET username = ? WHERE username = ?', (new_username, old_username))
            conn.execute('UPDATE study_log SET username = ? WHERE username = ?', (new_username, old_username))
            
            # 기존 레코드 삭제
            conn.execute('DELETE FROM users WHERE username = ?', (old_username,))
        else:
            # ID 변경 없음
            conn.execute('UPDATE users SET name = ?, level = ? WHERE username = ?', (new_name, new_level, old_username))
            
        conn.commit()
        return "SUCCESS"
    except Exception as e:
        conn.rollback()
        print(f"Error updating student info: {e}")
        return f"UPDATE_ERROR: {e}"
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
    """사용자 진도 저장 (기존 save_progress 대체) - 훨씬 효율적! (executemany 사용)"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # 1. 해당 유저의 기존 progress 모두 삭제
        c.execute("DELETE FROM user_progress WHERE username = ?", (username,))
        
        # 2. 데이터 삽입 (executemany 사용)
        if not progress_df.empty:
            data_to_insert = []
            for _, row in progress_df.iterrows():
                # Word ID
                try:
                    w_id = int(row.get('word_id', 0))
                except:
                    w_id = 0
                
                # Skip invalid word_id
                if w_id == 0: continue

                # Dates (Handle NaT/None)
                lr = row.get('last_reviewed')
                nr = row.get('next_review')
                
                if pd.isna(lr) or str(lr).strip().lower() in ['nat', 'none', 'nan', '']:
                    lr = None
                else:
                    lr = str(lr)
                    
                if pd.isna(nr) or str(nr).strip().lower() in ['nat', 'none', 'nan', '']:
                    nr = None
                else:
                    nr = str(nr)

                # Stats
                try:
                    iv = int(row.get('interval', 0))
                except: iv = 0
                
                try:
                    fc = int(row.get('fail_count', 0))
                except: fc = 0

                data_to_insert.append((username, w_id, lr, nr, iv, fc))

            if data_to_insert:
                c.executemany('''
                    INSERT INTO user_progress (username, word_id, last_reviewed, next_review, interval, fail_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', data_to_insert)
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error saving progress: {e}")
        return False
    finally:
        conn.close()

def update_single_user_progress(username, word_id, last_reviewed, next_review, interval, fail_count):
    """단일 단어 진행 상황 업데이트 (UPSERT) - 성능 최적화용"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # [FIX] word_id 강제 형변환
        word_id = int(word_id)
        
        # 날짜 타입 변환 (Safety)
        if hasattr(last_reviewed, 'strftime'): last_reviewed = str(last_reviewed)
        if hasattr(next_review, 'strftime'): next_review = str(next_review)
        
        # 1. 존재 여부 확인
        c.execute("SELECT id FROM user_progress WHERE username = ? AND word_id = ?", (username, word_id))
        row = c.fetchone()
        
        if row:
            # Update
            c.execute('''
                UPDATE user_progress 
                SET last_reviewed = ?, next_review = ?, interval = ?, fail_count = ?
                WHERE id = ?
            ''', (last_reviewed, next_review, interval, fail_count, row['id']))
        else:
            # Insert
            c.execute('''
                INSERT INTO user_progress (username, word_id, last_reviewed, next_review, interval, fail_count)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (username, word_id, last_reviewed, next_review, interval, fail_count))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating single progress: {e}")
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

def batch_update_vocab_levels(updates):
    """
    단어 레벨 일괄 업데이트
    updates: list of (new_level, word_id)
    """
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.executemany(
            'UPDATE voca_db SET level = ? WHERE id = ?',
            updates
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating vocab levels: {e}")
        return False
    finally:
        conn.close()

def delete_student(username):
    """학생 삭제 (관련 기록 Cascade 삭제)"""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute('DELETE FROM user_progress WHERE username = ?', (username,))
        conn.execute('DELETE FROM study_log WHERE username = ?', (username,))
        conn.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error deleting student: {e}")
        return False
    finally:
        conn.close()

def add_word(target_word, meaning, level, sentence_en, sentence_ko, root_word):
    """단어 추가"""
    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT INTO voca_db (target_word, meaning, level, sentence_en, sentence_ko, root_word) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (target_word, meaning, level, sentence_en, sentence_ko, root_word)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding word: {e}")
        return False
    finally:
        conn.close()

def update_word(word_id, target_word, meaning, level, sentence_en, sentence_ko, root_word):
    """단어 수정"""
    conn = get_db_connection()
    try:
        conn.execute(
            '''UPDATE voca_db 
               SET target_word=?, meaning=?, level=?, sentence_en=?, sentence_ko=?, root_word=?
               WHERE id=?''',
            (target_word, meaning, level, sentence_en, sentence_ko, root_word, word_id)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating word: {e}")
        return False
    finally:
        conn.close()

def delete_word(word_id):
    """단어 삭제 (관련 학습 기록도 삭제 고려)"""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        # 1. 단어 삭제
        conn.execute('DELETE FROM voca_db WHERE id = ?', (word_id,))
        # 2. 관련 진행 기록 삭제 (참조 무결성)
        conn.execute('DELETE FROM user_progress WHERE word_id = ?', (word_id,))
        # 3. 로그는 남길지 말지 고민이나, 보통은 로그도 지우거나 NULL 처리. 여기선 그냥 둠 (통계용)
        # 하지만 word_id가 사라지면 join이 안되므로 사실상 고아 레코드. 
        # 깔끔하게 지우거나, study_log에 word_text 컬럼을 둬야 하는데 구조 변경은 큼.
        # 일단 진행 기록만 삭제.
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error deleting word: {e}")
        return False
    finally:
        conn.close()

def bulk_upsert_words(df):
    """엑셀 데이터 일괄 업로드 (Target Word 기준 Upsert)"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        count_added = 0
        count_updated = 0
        
        # 1. 기존 단어 매핑 가져오기 (target_word -> id)
        c.execute("SELECT id, target_word FROM voca_db")
        existing_words = {row['target_word']: row['id'] for row in c.fetchall()}
        
        for _, row in df.iterrows():
            # 필수 컬럼 체크
            if 'target_word' not in row or pd.isna(row['target_word']): continue
            
            # 데이터 정제
            target_word = str(row['target_word']).strip()
            meaning = row.get('meaning', '')
            level = int(row.get('level', 1)) if pd.notna(row.get('level')) else 1
            sentence_en = row.get('sentence_en', '')
            sentence_ko = row.get('sentence_ko', '')
            root_word = row.get('root_word', '')
            
            # Target Word 존재 여부 확인
            if target_word in existing_words:
                # 존재하면 UPDATE (ID 기반)
                word_id = existing_words[target_word]
                c.execute('''
                    UPDATE voca_db 
                    SET meaning=?, level=?, sentence_en=?, sentence_ko=?, root_word=?
                    WHERE id=?
                ''', (meaning, level, sentence_en, sentence_ko, root_word, word_id))
                count_updated += 1
            else:
                # 없으면 INSERT
                c.execute('''
                    INSERT INTO voca_db (target_word, meaning, level, sentence_en, sentence_ko, root_word)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (target_word, meaning, level, sentence_en, sentence_ko, root_word))
                count_added += 1
                
        conn.commit()
        return count_added, count_updated
    except Exception as e:
        print(f"Bulk Upsert Error: {e}")
        return 0, 0
    finally:
        conn.close()

def clear_vocabulary_data():
    """단어 데이터 및 관련 진도 초기화 (학생 계정은 유지)"""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        # 1. 테이블 삭제 (스키마 초기화를 위해)
        conn.execute('DROP TABLE IF EXISTS user_progress')
        conn.execute('DROP TABLE IF EXISTS study_log')
        conn.execute('DROP TABLE IF EXISTS voca_db')
        
        # 2. 유저 상태 초기화 (pending_wrongs, pending_session)
        conn.execute('UPDATE users SET pending_wrongs = "", pending_session = ""')
        
        conn.commit()
        conn.close()
        
        # 3. 테이블 재생성
        init_db()
        
        return True
    except Exception as e:
        # conn might be closed if commit succeeded but init_db failed? 
        # No, close() is called.
        print(f"Error clearing vocabulary: {e}")
        return False
