import pandas as pd
import hashlib
import os
import time
from datetime import datetime, timedelta
import pytz
import streamlit as st
import streamlit.components.v1 as components
from gtts import gTTS
import io
import re
import random
import calendar
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. 구글 시트 연결 설정 ---
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

try:
    gcp_info = dict(st.secrets["gcp_service_account"])
    if "private_key" in gcp_info:
        gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_info, SCOPE)
    client = gspread.authorize(creds)
except Exception as e:
    client = None

SHEET_NAME = "Voca_DB"

# --- 2. 기본 상수 설정 ---
LEVEL_UP_INTERVAL_DAYS = 7
LEVEL_UP_RATIO = 0.8
LEVEL_UP_MIN_COUNT = 30
LEVEL_DOWN_ACCURACY = 0.4
MIN_TRAIN_DAYS = 3
MIN_TRAIN_COUNT = 50
SIGNUP_SECRET_CODE = "math2026"
ADMIN_PASSWORD = "teacher1234"
SRS_STEPS_DAYS = [1, 3, 7, 14, 60]

# --- 3. 헬퍼 함수 (재시도 로직 포함) ---
def get_worksheet(tab_name):
    """워크시트 가져오기 (재시도 포함)"""
    if client is None: return None
    for attempt in range(3): # 3번 시도
        try:
            sh = client.open(SHEET_NAME)
            return sh.worksheet(tab_name)
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            st.error(f"워크시트 로딩 실패: {e}")
            return None
    return None

def read_sheet_to_df(tab_name):
    """데이터 읽기 (429 에러 방지 및 헤더 처리 강화)"""
    for attempt in range(3):
        try:
            ws = get_worksheet(tab_name)
            if not ws: return pd.DataFrame()

            data = ws.get_all_values()
            
            if not data or len(data) < 2:
                if data: 
                    cleaned_cols = [str(c).strip() for c in data[0]]
                    return pd.DataFrame(columns=cleaned_cols)
                return pd.DataFrame()
            
            raw_headers = data[0]
            headers = [str(h).strip() for h in raw_headers]
            
            # 헤더 비상 대책 (users 탭)
            if tab_name == 'users' and 'username' not in headers:
                if len(headers) >= 4:
                    headers = ['username', 'password', 'name', 'level'] + headers[4:]
            
            rows = data[1:]
            df = pd.DataFrame(rows, columns=headers)
            return df
            
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            print(f"Sheet Load Error ({tab_name}): {e}")
            return pd.DataFrame()
    return pd.DataFrame()

# --- 4. 보안 및 시간 함수 ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

def get_korea_today():
    try:
        kst = pytz.timezone('Asia/Seoul')
        return datetime.now(kst).date()
    except: return datetime.now().date()

def _add_months(date_obj, months: int):
    y = date_obj.year + (date_obj.month - 1 + months) // 12
    m = (date_obj.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    d = min(date_obj.day, last_day)
    return datetime(y, m, d).date()

# --- 5. 데이터 로딩 ---
@st.cache_data(ttl=60)
def load_data():
    df = read_sheet_to_df('voca_db')
    if df.empty: return None
    
    required_cols = ['id', 'target_word', 'meaning', 'level', 'sentence_en', 'sentence_ko', 'root_word', 'total_try', 'total_wrong']
    for col in required_cols:
        if col not in df.columns:
            if col in ['total_try', 'total_wrong', 'level', 'id']: df[col] = 0
            else: df[col] = ''
            
    df['level'] = pd.to_numeric(df['level'], errors='coerce').fillna(1).astype(int)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    return df

def load_user_progress(username):
    df = read_sheet_to_df('user_progress')
    if df.empty:
        return pd.DataFrame(columns=['username', 'word_id', 'last_reviewed', 'next_review', 'interval', 'fail_count'])
    
    user_df = df[df['username'] == username].copy()
    for col in ['next_review', 'last_reviewed']:
        if col in user_df.columns:
            user_df[col] = pd.to_datetime(user_df[col], errors='coerce').dt.date
    return user_df

def save_progress(username, progress_df):
    """진도 저장 (재시도 로직 포함)"""
    for attempt in range(3):
        try:
            ws = get_worksheet('user_progress')
            if not ws: return

            progress_df['username'] = username
            progress_df['last_reviewed'] = progress_df['last_reviewed'].astype(str)
            progress_df['next_review'] = progress_df['next_review'].astype(str)

            all_data = ws.get_all_values() # 값만 가져오기 (가벼움)
            
            if len(all_data) > 1:
                headers = all_data[0]
                all_df = pd.DataFrame(all_data[1:], columns=headers)
                other_users_df = all_df[all_df['username'] != username]
                final_df = pd.concat([other_users_df, progress_df], ignore_index=True)
            else:
                final_df = progress_df

            ws.clear()
            ws.update([final_df.columns.values.tolist()] + final_df.values.tolist())
            return # 성공하면 종료
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            st.error(f"저장 실패: {e}")
            break

# --- 6. 학습 로그 ---
def log_study_result(username, word_id, level, is_correct):
    for attempt in range(3):
        try:
            ws = get_worksheet('study_log')
            if not ws: return
            
            today = get_korea_today()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [timestamp, str(today), int(word_id), username, int(level), 1 if is_correct else 0]
            ws.append_row(row)
            return
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            print(f"Log Error: {e}")
            break

def load_study_log(username):
    df = read_sheet_to_df('study_log')
    if df.empty: return pd.DataFrame()
    return df[df['username'] == username]

# --- 7. 사용자 정보 ---
def get_user_info(username):
    df = read_sheet_to_df('users')
    if df.empty: return None
    
    if username in df['username'].values:
        user_row = df[df['username'] == username].iloc[0]
        lv = user_row.get('level', '')
        if pd.isna(lv) or str(lv).strip() == '':
            final_lv = None
        else:
            try: final_lv = int(lv)
            except: final_lv = 1
        return {'level': final_lv, 'name': user_row['name']}
    return None

def register_user(username, password, name):
    for attempt in range(3):
        try:
            ws = get_worksheet('users')
            if not ws: return "ERROR"
            
            existing_df = read_sheet_to_df('users')
            if not existing_df.empty and username in existing_df['username'].values:
                return "EXIST"
                
            hashed_pw = make_hashes(password)
            ws.append_row([username, hashed_pw, name, ""])
            return "SUCCESS"
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            return "ERROR"
    return "ERROR"

def update_user_level(username, new_level):
    """레벨 업데이트 (재시도 로직 필수!)"""
    for attempt in range(3):
        try:
            ws = get_worksheet('users')
            if not ws: return
            
            # 여기서 find할 때 읽기 할당량이 소모됨 -> 에러 포인트
            cell = ws.find(username)
            ws.update_cell(cell.row, 4, new_level)
            return # 성공 시 종료
        except Exception as e:
            if "429" in str(e): # 속도 제한 걸리면
                time.sleep(3)   # 3초 쉬었다가 다시
                continue
            st.error(f"레벨 업데이트 실패: {e}")
            break

def reset_user_password(username, new_password_str="1234"):
    for attempt in range(3):
        try:
            ws = get_worksheet('users')
            if not ws: return
            cell = ws.find(username)
            hashed_pw = make_hashes(new_password_str)
            ws.update_cell(cell.row, 2, hashed_pw)
            return True
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            return False
    return False

# --- 8. SRS 스케줄링 ---
def update_schedule(word_id, is_correct, progress_df, today):
    for col in ['fail_count', 'interval']:
        if col not in progress_df.columns: progress_df[col] = 0
    for col in ['last_reviewed', 'next_review']:
        if col not in progress_df.columns: progress_df[col] = pd.NaT

    def _to_int(x, default=0):
        try: return int(float(x)) if pd.notna(x) else default
        except: return default

    def _next_step(cur_days):
        if cur_days not in SRS_STEPS_DAYS:
            cur_days = max([s for s in SRS_STEPS_DAYS if s <= cur_days], default=1)
        if cur_days == 1: return 3
        if cur_days == 3: return 7
        if cur_days == 7: return 14
        return 60 

    if word_id in progress_df['word_id'].values:
        idx = progress_df[progress_df['word_id'] == word_id].index[0]
        progress_df.loc[idx, 'last_reviewed'] = today
        cur_fail = _to_int(progress_df.loc[idx, 'fail_count'], 0)
        cur_interval = _to_int(progress_df.loc[idx, 'interval'], 0)

        if is_correct:
            if cur_fail > 0:
                if cur_interval <= 0: cur_interval = 1
                new_interval = _next_step(cur_interval)
                progress_df.loc[idx, 'interval'] = int(new_interval)
                progress_df.loc[idx, 'next_review'] = _add_months(today, 2) if new_interval >= 60 else today + timedelta(days=int(new_interval))
            else:
                progress_df.loc[idx, 'interval'] = 60
                progress_df.loc[idx, 'next_review'] = _add_months(today, 2)
        else:
            progress_df.loc[idx, 'fail_count'] = int(cur_fail) + 1
            progress_df.loc[idx, 'interval'] = 1
            progress_df.loc[idx, 'next_review'] = today + timedelta(days=1)
    else:
        new_row = {
            'word_id': word_id,
            'last_reviewed': today,
            'interval': 60 if is_correct else 1,
            'fail_count': 0 if is_correct else 1,
            'next_review': _add_months(today, 2) if is_correct else today + timedelta(days=1)
        }
        progress_df = pd.concat([progress_df, pd.DataFrame([new_row])], ignore_index=True)
    
    return progress_df

# --- 9. 기타 유틸 ---
def text_to_speech(text):
    try:
        tts = gTTS(text=text, lang='en')
        mp3_fp = io.BytesIO()
        tts.write_to_fp(mp3_fp)
        return mp3_fp
    except: return None

def get_masked_sentence(sentence, target_word, root_word=None):
    if not isinstance(sentence, str): return sentence
    words_to_mask = [str(target_word)]
    if root_word and isinstance(root_word, str) and root_word.strip():
        words_to_mask.append(root_word.strip())
    words_to_mask.sort(key=len, reverse=True)
    escaped_words = [re.escape(w) for w in words_to_mask]
    pattern_str = '|'.join(escaped_words)
    pattern = re.compile(pattern_str, re.IGNORECASE)
    return pattern.sub(" [ ❓ ] ", sentence)

def get_highlighted_sentence(sentence, target_word):
    if not isinstance(sentence, str): return sentence
    pattern = re.compile(re.escape(target_word), re.IGNORECASE)
    return pattern.sub(r"<span style='color: #E74C3C; font-weight: 900; font-size: 1.2em;'>\g<0></span>", sentence)

def focus_element(target_type="input"):
    components.html(
        f"""
        <div id="focus_marker_{datetime.now().timestamp()}"></div>
        <script>
            setTimeout(function() {{
                var target = window.parent.document.querySelectorAll('{ "input[type=text]" if target_type == "input" else "button" }');
                if (target.length > 0) {{ target[target.length - 1].focus(); }}
            }}, 300);
        </script>
        """,
        height=0
    )

def adjust_level_based_on_stats():
    return 0, "구글 시트 연동 모드에서는 자동 레벨 조정이 일시 중지됩니다."
