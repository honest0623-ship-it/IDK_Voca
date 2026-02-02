import pandas as pd
import hashlib
import os
from datetime import datetime, timedelta
import pytz
import glob
import streamlit as st
import streamlit.components.v1 as components
from gtts import gTTS
import io
import re
import random

import calendar
# --- 설정 및 경로 ---
DB_FILE_PATTERN = 'Voca_DB_Integrated.csv'
USER_FILE = 'users.csv'

# 등업 기준
LEVEL_UP_INTERVAL_DAYS = 7
LEVEL_UP_RATIO = 0.8
LEVEL_UP_MIN_COUNT = 30

# 레벨 다운 기준
LEVEL_DOWN_ACCURACY = 0.4

# 레벨 조정 심사 최소 조건
MIN_TRAIN_DAYS = 3
MIN_TRAIN_COUNT = 50

# 보안 설정
SIGNUP_SECRET_CODE = "math2026"
ADMIN_PASSWORD = "teacher1234"

# --- 보안 함수 ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

# --- 날짜/시간 함수 ---
def get_korea_today():
    try:
        kst = pytz.timezone('Asia/Seoul')
        return datetime.now(kst).date()
    except Exception: return datetime.now().date()

# --- 데이터 로딩 ---
@st.cache_data(ttl=60)
def load_data():
    if os.path.exists(DB_FILE_PATTERN):
        files = [DB_FILE_PATTERN]
    else:
        files = glob.glob('Voca_DB*.csv')

    if not files: return None
    
    combined_df = pd.DataFrame()
    for filename in files:
        try:
            df = pd.read_csv(filename, encoding='utf-8-sig')
            if 'level' not in df.columns: df['level'] = 1
            if 'source' not in df.columns:
                source_name = os.path.basename(filename).replace("Voca_DB", "").replace(".csv", "").strip(" _-")
                df['source'] = source_name
            if 'root_word' in df.columns:
                df['root_word'] = df['root_word'].fillna('')
            if 'id' not in df.columns:
                df['id'] = range(1, len(df) + 1)
            if 'total_try' not in df.columns: df['total_try'] = 0
            if 'total_wrong' not in df.columns: df['total_wrong'] = 0
                
            combined_df = pd.concat([combined_df, df], ignore_index=True)
        except Exception as e:
            st.error(f"⚠️ {filename} 로딩 중 오류: {e}")
            continue

    if combined_df.empty: return None
    if len(files) > 1:
        combined_df = combined_df.reset_index(drop=True)
        combined_df['id'] = combined_df.index + 1
    return combined_df

def load_user_progress(username):
    filename = f"progress_{username}.csv"
    if os.path.exists(filename):
        try:
            df = pd.read_csv(filename)
            df['next_review'] = pd.to_datetime(df['next_review']).dt.date
            df['last_reviewed'] = pd.to_datetime(df['last_reviewed'], errors='coerce').dt.date
            return df
        except: pass
    return pd.DataFrame(columns=['word_id', 'last_reviewed', 'next_review', 'interval', 'fail_count'])

def save_progress(username, progress_df):
    filename = f"progress_{username}.csv"
    try:
        progress_df.to_csv(filename, index=False, encoding='utf-8-sig')
    except PermissionError:
        st.error("⚠️ 파일을 저장할 수 없습니다. 엑셀 파일이 열려있는지 확인해주세요.")

# --- 학습 로그 ---
def log_study_result(username, word_id, level, is_correct):
    log_file = f"study_log_{username}.csv"
    today = get_korea_today()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    new_data = pd.DataFrame([{
        'timestamp': timestamp,
        'date': today,
        'word_id': word_id,
        'username': username,
        'level': level,
        'is_correct': 1 if is_correct else 0
    }])
    
    if not os.path.exists(log_file):
        new_data.to_csv(log_file, index=False, encoding='utf-8-sig')
    else:
        try:
            new_data.to_csv(log_file, mode='a', header=False, index=False, encoding='utf-8-sig')
        except: pass 

def load_study_log(username):
    log_file = f"study_log_{username}.csv"
    if os.path.exists(log_file):
        try: return pd.read_csv(log_file)
        except: pass
    return pd.DataFrame()

# --- 사용자 정보 ---
def get_user_info(username):
    if not os.path.exists(USER_FILE): return None
    users = pd.read_csv(USER_FILE)
    if username in users['username'].values:
        user_row = users[users['username'] == username].iloc[0]
        user_level = user_row['level'] if 'level' in users.columns and pd.notna(user_row['level']) else None
        real_name = user_row['name'] if 'name' in users.columns else username
        return {'level': user_level, 'name': real_name}
    return None

def update_user_level(username, new_level):
    if not os.path.exists(USER_FILE): return
    users = pd.read_csv(USER_FILE)
    if username in users['username'].values:
        idx = users[users['username'] == username].index[0]
        users.at[idx, 'level'] = new_level
        users.to_csv(USER_FILE, index=False, encoding='utf-8-sig')

# --- 텍스트 유틸리티 ---
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
    replacement = r"<span style='color: #E74C3C; font-weight: 900; font-size: 1.2em;'>\g<0></span>"
    return pattern.sub(replacement, sentence)

@st.cache_data(show_spinner=False)
def text_to_speech(text):
    try:
        tts = gTTS(text=text, lang='en')
        mp3_fp = io.BytesIO()
        tts.write_to_fp(mp3_fp)
        return mp3_fp
    except Exception as e: return None

def focus_element(target_type="input"):
    components.html(
        f"""
        <div id="focus_marker_{datetime.now().timestamp()}" style="display:none;"></div>
        <script>
            function setFocus() {{
                var targetType = "{target_type}";
                var elementToFocus = null;
                if (targetType === 'input') {{
                    var inputs = window.parent.document.querySelectorAll('input[type="text"]');
                    if (inputs.length > 0) {{ elementToFocus = inputs[inputs.length - 1]; }}
                }} else if (targetType === 'button') {{
                    var buttons = window.parent.document.querySelectorAll('button[kind="primary"]');
                    if (buttons.length > 0) {{ elementToFocus = buttons[buttons.length - 1]; }}
                }}
                if (elementToFocus) {{ elementToFocus.focus(); }}
            }}
            setTimeout(setFocus, 300);
        </script>
        """,
        height=0
    )

# --- 🔥 [중요] 이름 통일된 SRS 스케줄링 로직 ---
# --- 🔁 망각곡선(Spaced Repetition) 스케줄 ---
# - 오답(한 번이라도 틀린 단어): 1일 → 3일 → 7일 → 14일 → 2개월(≈ +2 months)
# - '처음 출제에서 바로 정답' 단어(오답 이력 없음): 2개월(≈ +2 months)마다
_SRS_STEPS_DAYS = [1, 3, 7, 14, 60]  # 60은 저장용(통계/표시). 실제 날짜는 월 단위로 +2개월 처리.

def _add_months(date_obj, months: int):
    """date_obj에 months만큼 더한 날짜를 반환(말일은 자동 보정)."""
    y = date_obj.year + (date_obj.month - 1 + months) // 12
    m = (date_obj.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    d = min(date_obj.day, last_day)
    return datetime(y, m, d).date()

def update_schedule(word_id, is_correct, progress_df, today):
    # 컬럼 호환 (예전 progress 파일이 컬럼을 누락했을 수 있음)
    if 'fail_count' not in progress_df.columns:
        progress_df['fail_count'] = 0
    if 'last_reviewed' not in progress_df.columns:
        progress_df['last_reviewed'] = pd.NaT
    if 'next_review' not in progress_df.columns:
        progress_df['next_review'] = pd.NaT
    if 'interval' not in progress_df.columns:
        progress_df['interval'] = 0

    def _to_int(x, default=0):
        try:
            if pd.isna(x): 
                return default
        except Exception:
            pass
        try:
            return int(float(x))
        except Exception:
            return default

    def _next_step(cur_days: int):
        # cur_days가 steps에 없으면, 가장 가까운 하위 step으로 보정
        if cur_days not in _SRS_STEPS_DAYS:
            cur_days = max([s for s in _SRS_STEPS_DAYS if s <= cur_days], default=1)
        if cur_days == 1: return 3
        if cur_days == 3: return 7
        if cur_days == 7: return 14
        return 60  # 14 이상이면 최종(2개월)

    if word_id in progress_df['word_id'].values:
        idx = progress_df[progress_df['word_id'] == word_id].index[0]

        # 오늘 학습 기록
        progress_df.loc[idx, 'last_reviewed'] = today

        cur_fail = _to_int(progress_df.loc[idx, 'fail_count'], 0)
        cur_interval = _to_int(progress_df.loc[idx, 'interval'], 0)

        if is_correct:
            # 오답 이력이 있으면: 1→3→7→14→2개월
            if cur_fail > 0:
                # 혹시 과거 데이터에서 interval=0으로 남아있다면 1로 보정
                if cur_interval <= 0:
                    cur_interval = 1
                new_interval = _next_step(cur_interval)
                progress_df.loc[idx, 'interval'] = int(new_interval)

                if new_interval >= 60:
                    progress_df.loc[idx, 'next_review'] = _add_months(today, 2)
                else:
                    progress_df.loc[idx, 'next_review'] = today + timedelta(days=int(new_interval))
            else:
                # 한 번도 틀린 적 없는(=한 번에 정답) 단어는 2개월 뒤 출제
                progress_df.loc[idx, 'interval'] = 60
                progress_df.loc[idx, 'next_review'] = _add_months(today, 2)

        else:
            # 오답이면: 오답노트는 '당일'에만 하고, 다음 출제는 무조건 '내일(1일 뒤)'로
            progress_df.loc[idx, 'fail_count'] = int(cur_fail) + 1
            progress_df.loc[idx, 'interval'] = 1
            progress_df.loc[idx, 'next_review'] = today + timedelta(days=1)

    else:
        # 신규 단어
        if is_correct:
            new_row = {
                'word_id': word_id,
                'last_reviewed': today,
                'next_review': _add_months(today, 2),  # 첫 출제 정답 → 2개월 뒤
                'interval': 60,
                'fail_count': 0
            }
        else:
            new_row = {
                'word_id': word_id,
                'last_reviewed': today,
                'next_review': today + timedelta(days=1),  # 오답 → 1일 뒤
                'interval': 1,
                'fail_count': 1
            }
        progress_df = pd.concat([progress_df, pd.DataFrame([new_row])], ignore_index=True)

    return progress_df

# --- 🔥 [중요] 이름 통일된 레벨 조정 로직 ---
def adjust_level_based_on_stats():
    log_files = glob.glob("study_log_*.csv")
    if not log_files: return 0, "학습 데이터가 없습니다."

    all_logs = pd.DataFrame()
    for f in log_files:
        try:
            temp_df = pd.read_csv(f)
            if 'username' not in temp_df.columns:
                user_from_file = f.replace("study_log_", "").replace(".csv", "")
                temp_df['username'] = user_from_file
            all_logs = pd.concat([all_logs, temp_df], ignore_index=True)
        except: continue
    
    if all_logs.empty: return 0, "유효한 데이터가 없습니다."
    if not os.path.exists(DB_FILE_PATTERN): return 0, "DB 파일이 없습니다."

    df = pd.read_csv(DB_FILE_PATTERN, encoding='utf-8-sig')
    
    try_counts = all_logs.groupby('word_id')['username'].nunique()
    wrong_logs = all_logs[all_logs['is_correct'] == 0]
    wrong_counts = wrong_logs.groupby('word_id')['username'].nunique()
    
    updated_count = 0
    
    for word_id, user_count in try_counts.items():
        if word_id in df['id'].values:
            idx = df[df['id'] == word_id].index[0]
            wrong_user_count = wrong_counts.get(word_id, 0)
            
            df.at[idx, 'total_try'] = user_count
            df.at[idx, 'total_wrong'] = wrong_user_count
            
            wrong_rate = wrong_user_count / user_count if user_count > 0 else 0
            
            curr, new_lv = df.at[idx, 'level'], df.at[idx, 'level']
            
            # 최소 인원 6명 (테스트 시 1로 변경)
            if user_count >= 6: 
                if wrong_rate >= 0.5: new_lv = min(30, curr + 1)
                elif wrong_rate <= 0.1: new_lv = max(1, curr - 1)
            
            if new_lv != curr:
                df.at[idx, 'level'] = new_lv
                updated_count += 1
                
    df['last_level_update'] = datetime.now().strftime("%Y-%m-%d")
    df.to_csv(DB_FILE_PATTERN, index=False, encoding='utf-8-sig')
    return updated_count, "성공적으로 조정되었습니다."