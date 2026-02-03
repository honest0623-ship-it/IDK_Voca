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
        gcp_info["private_key"] = gcp_info["private_key"].replace("\n", "\n")
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
SIGNUP_SECRET_CODE = st.secrets.get("SIGNUP_SECRET_CODE", "math2026")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "teacher1234")
SRS_STEPS_DAYS = [1, 3, 7, 14, 60, 120]

# --- Sheet read cache (TTL + write invalidation) ---
def _get_sheet_cache_ver():
    """세션 단위 시트 캐시 버전 (쓰기 성공 시 증가)"""
    if '_sheet_cache_ver' not in st.session_state:
        st.session_state._sheet_cache_ver = 0
    return int(st.session_state._sheet_cache_ver)

def bump_sheet_cache_ver():
    """쓰기 후 캐시 무효화용 버전 증가"""
    st.session_state._sheet_cache_ver = _get_sheet_cache_ver() + 1

@st.cache_data(show_spinner=False, ttl=90)
def _read_sheet_to_df_cached(tab_name: str, cache_ver: int):
    """시트 전체 읽기 캐시 (기본 90초). cache_ver가 바뀌면 자동 무효화."""
    return _read_sheet_to_df_uncached(tab_name)


@st.cache_resource(show_spinner=False)
def _get_spreadsheet():
    """스프레드시트 객체 캐시 (open 호출 최소화)"""
    if client is None:
        return None
    return client.open(SHEET_NAME)

# --- 3. 헬퍼 함수 (재시도 로직 포함) ---
def get_worksheet(tab_name):
    """워크시트 가져오기 (재시도 포함, open 호출 캐시)"""
    sh = _get_spreadsheet()
    if sh is None:
        return None

    for attempt in range(3):  # 3번 시도
        try:
            return sh.worksheet(tab_name)
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            st.error(f"워크시트 로딩 실패: {e}")
            return None
    return None


def _read_sheet_to_df_uncached(tab_name):
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

def read_sheet_to_df(tab_name, use_cache: bool = True):
    """데이터 읽기 (기본: 90초 캐시). 쓰기 후 bump_sheet_cache_ver()로 무효화."""
    if use_cache:
        return _read_sheet_to_df_cached(str(tab_name), _get_sheet_cache_ver())
    return _read_sheet_to_df_uncached(tab_name)

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
@st.cache_data(ttl=600, show_spinner=False)
def load_data():
    """voca_db 로딩 (빈번한 재조회 방지: 10분 캐시)"""
    df = read_sheet_to_df('voca_db')
    if df.empty:
        return None

    required_cols = [
        'id', 'target_word', 'meaning', 'level', 'sentence_en', 'sentence_ko',
        'root_word', 'total_try', 'total_wrong'
    ]
    for col in required_cols:
        if col not in df.columns:
            if col in ['total_try', 'total_wrong', 'level', 'id']:
                df[col] = 0
            else:
                df[col] = ''

    df['level'] = pd.to_numeric(df['level'], errors='coerce').fillna(1).astype(int)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    return df


def load_user_progress(username):
    """사용자의 학습 진도 로드 (숫자 변환 기능 추가)"""
    df = read_sheet_to_df('user_progress')
    
    # 데이터가 없으면 빈 표 반환
    if df.empty:
        return pd.DataFrame(columns=['username', 'word_id', 'last_reviewed', 'next_review', 'interval', 'fail_count'])
    
    # 해당 유저 데이터만 필터링
    user_df = df[df['username'] == username].copy()
    
    # 1. 날짜 컬럼 변환 (기존 코드)
    for col in ['next_review', 'last_reviewed']:
        if col in user_df.columns:
            user_df[col] = pd.to_datetime(user_df[col], errors='coerce').dt.date
            
    # 2. [추가됨] 숫자 컬럼 변환 (여기가 핵심! ⭐)
    # interval, fail_count, word_id는 무조건 숫자로 인식하게 만듦
    for col in ['interval', 'fail_count', 'word_id']:
        if col in user_df.columns:
            user_df[col] = pd.to_numeric(user_df[col], errors='coerce').fillna(0).astype(int)
            
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
            bump_sheet_cache_ver()
            return # 성공하면 종료
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            st.error(f"저장 실패: {e}")
            break

# --- 6. 학습 로그 ---


def save_progress_fast(username, progress_df):
    """진도 저장 (속도 개선 버전)
    - 전체 시트를 clear/update 하지 않고
    - 해당 username 블록만 삭제 후 append
    - 삭제 대상 탐색은 username 컬럼만 조회(전송량 감소)
    """
    for attempt in range(3):
        try:
            ws = get_worksheet('user_progress')
            if not ws:
                return

            df = progress_df.copy()
            df['username'] = username
            for col in ['last_reviewed', 'next_review']:
                if col in df.columns:
                    df[col] = df[col].astype(str)

            # 1) 헤더 로딩/보정
            original_headers = ws.row_values(1)
            headers = [str(h).strip() for h in original_headers] if original_headers else []
            required = ['word_id', 'last_reviewed', 'next_review', 'interval', 'fail_count', 'username']
            if not headers:
                headers = required[:]  # 시트가 비어 있으면 기본 헤더 생성
                ws.append_row(headers, value_input_option='USER_ENTERED')
            else:
                changed = False
                for col in required:
                    if col not in headers:
                        headers.append(col)
                        changed = True
                if changed:
                    ws.update('A1', [headers], value_input_option='USER_ENTERED')

            # 2) username 컬럼만 조회해서 기존 행 찾기
            user_col_idx = headers.index('username') + 1
            user_col = ws.col_values(user_col_idx)  # header 포함
            existing_rows = [i for i, val in enumerate(user_col[1:], start=2) if val == username]

            # 3) 기존 행 삭제
            if existing_rows:
                if existing_rows == list(range(existing_rows[0], existing_rows[-1] + 1)):
                    ws.delete_rows(existing_rows[0], existing_rows[-1])
                else:
                    for r in sorted(existing_rows, reverse=True):
                        ws.delete_rows(r)

            # 4) 새 데이터 append
            out = df.copy()
            for col in required:
                if col not in out.columns:
                    out[col] = 0 if col in ['word_id', 'interval', 'fail_count'] else ''
            out = out[required]
            rows_to_append = out.values.tolist()

            if hasattr(ws, 'append_rows'):
                ws.append_rows(rows_to_append, value_input_option='USER_ENTERED')
            else:
                for r in rows_to_append:
                    ws.append_row(r, value_input_option='USER_ENTERED')

            bump_sheet_cache_ver()
            return

        except Exception as e:
            if '429' in str(e):
                time.sleep(2)
                continue
            st.error(f"저장 실패(FAST): {e}")
            break
def log_study_result(username, word_id, level, is_correct):
    for attempt in range(3):
        try:
            ws = get_worksheet('study_log')
            if not ws: return
            
            today = get_korea_today()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [timestamp, str(today), int(word_id), username, int(level), 1 if is_correct else 0]
            ws.append_row(row)
            bump_sheet_cache_ver()
            return
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            print(f"Log Error: {e}")
            break


def log_study_results_batch(rows):
    """학습 로그를 여러 행 한 번에 append (속도 개선)"""
    if not rows:
        return
    for attempt in range(3):
        try:
            ws = get_worksheet('study_log')
            if not ws:
                return
            # gspread 버전에 따라 append_rows가 없을 수 있어 fallback 제공
            if hasattr(ws, "append_rows"):
                ws.append_rows(rows, value_input_option='USER_ENTERED')
            else:
                for r in rows:
                    ws.append_row(r)
            return
        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            print(f"Batch Log Error: {e}")
            break


def load_study_log(username):
    df = read_sheet_to_df('study_log')
    if df.empty:
        return pd.DataFrame()

    # 컬럼 보정
    for col in ['timestamp', 'date', 'word_id', 'username', 'level', 'is_correct']:
        if col not in df.columns:
            df[col] = None

    df = df[df['username'] == username].copy()

    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
    df['word_id'] = pd.to_numeric(df['word_id'], errors='coerce')
    df['level'] = pd.to_numeric(df['level'], errors='coerce')
    df['is_correct'] = pd.to_numeric(df['is_correct'], errors='coerce')

    df = df.dropna(subset=['date'])
    df['word_id'] = df['word_id'].fillna(0).astype(int)
    df['level'] = df['level'].fillna(0).astype(int)
    df['is_correct'] = df['is_correct'].fillna(0).astype(int)

    return df
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
            if not ws:
                return "ERROR"

            existing_df = read_sheet_to_df('users')
            if not existing_df.empty and 'username' in existing_df.columns and username in existing_df['username'].values:
                return "EXIST"

            hashed_pw = make_hashes(password)
            ws.append_row([username, hashed_pw, name, ""])

            # ✅ 가입 직후 바로 로그인 가능하게 캐시 클리어
            st.cache_data.clear()
            bump_sheet_cache_ver()
            return "SUCCESS"

        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            return "ERROR"
    return "ERROR"

def update_user_level(username, new_level):
    for attempt in range(3):
        try:
            ws = get_worksheet('users')
            if not ws:
                return

            cell = ws.find(username, in_column=1)
            if not cell:
                st.error("유저를 찾을 수 없습니다.")
                return

            ws.update_cell(cell.row, 4, new_level)
            bump_sheet_cache_ver()
            return
        except Exception as e:
            if "429" in str(e):
                time.sleep(3)
                continue
            st.error(f"레벨 업데이트 실패: {e}")
            break


def reset_user_password(username, new_password):
    for attempt in range(3):
        try:
            ws = get_worksheet('users')
            if not ws:
                return False

            cell = ws.find(username, in_column=1)
            if not cell:
                return False

            hashed_pw = make_hashes(new_password)
            ws.update_cell(cell.row, 2, hashed_pw)
            bump_sheet_cache_ver()
            return True
        except Exception as e:
            if "429" in str(e):
                time.sleep(3)
                continue
            st.error(f"비밀번호 초기화 실패: {e}")
            break
    return False

def update_schedule(word_id, is_correct, progress_df, today):
    # 컬럼 보정
    for col in ['fail_count', 'interval']:
        if col not in progress_df.columns:
            progress_df[col] = 0
    for col in ['last_reviewed', 'next_review']:
        if col not in progress_df.columns:
            progress_df[col] = pd.NaT

    def _to_int(x, default=0):
        try:
            return int(float(x)) if pd.notna(x) and str(x).strip() != "" else default
        except:
            return default

    def _next_step(cur_days):
        # 오답 경험 단어: 1 → 3 → 7 → 14 → 60(2개월) → 120(4개월)
        if cur_days == 1: return 3
        if cur_days == 3: return 7
        if cur_days == 7: return 14
        if cur_days == 14: return 60
        if cur_days == 60: return 120
        return 120

    def _calc_next_review(base_date, interval_days: int):
        if interval_days >= 120:
            return _add_months(base_date, 4)
        if interval_days >= 60:
            return _add_months(base_date, 2)
        return base_date + timedelta(days=int(interval_days))

    if 'word_id' in progress_df.columns and word_id in progress_df['word_id'].values:
        idx = progress_df[progress_df['word_id'] == word_id].index[0]
        progress_df.loc[idx, 'last_reviewed'] = today
        cur_fail = _to_int(progress_df.loc[idx, 'fail_count'], 0)
        cur_interval = _to_int(progress_df.loc[idx, 'interval'], 0)

        if is_correct:
            if cur_fail > 0:
                if cur_interval <= 0:
                    cur_interval = 1
                new_interval = _next_step(cur_interval)
                progress_df.loc[idx, 'interval'] = int(new_interval)
                progress_df.loc[idx, 'next_review'] = _calc_next_review(today, int(new_interval))
            else:
                # 오답 경험 없는 단어: 첫 정답이면 2개월 뒤
                progress_df.loc[idx, 'interval'] = 60
                progress_df.loc[idx, 'next_review'] = _add_months(today, 2)
        else:
            progress_df.loc[idx, 'fail_count'] = int(cur_fail) + 1
            progress_df.loc[idx, 'interval'] = 1
            progress_df.loc[idx, 'next_review'] = today + timedelta(days=1)

    else:
        # 신규 단어
        new_row = {
            'word_id': int(word_id),
            'last_reviewed': today,
            'interval': 60 if is_correct else 1,
            'fail_count': 0 if is_correct else 1,
            'next_review': _add_months(today, 2) if is_correct else today + timedelta(days=1)
        }
        progress_df = pd.concat([progress_df, pd.DataFrame([new_row])], ignore_index=True)

    # 타입 정리 (안전)
    if 'word_id' in progress_df.columns:
        progress_df['word_id'] = pd.to_numeric(progress_df['word_id'], errors='coerce').fillna(0).astype(int)
    if 'interval' in progress_df.columns:
        progress_df['interval'] = pd.to_numeric(progress_df['interval'], errors='coerce').fillna(0).astype(int)
    if 'fail_count' in progress_df.columns:
        progress_df['fail_count'] = pd.to_numeric(progress_df['fail_count'], errors='coerce').fillna(0).astype(int)

    return progress_df

# --- 9. 기타 유틸 ---
def text_to_speech(word_id, text):
    """
    1) 로컬 tts_audio/{word_id}.mp3 확인
    2) 없으면 gTTS 생성 후 로컬 저장
    3) 바이너리 데이터 반환
    """
    # 폴더 확보
    if not os.path.exists("tts_audio"):
        try:
            os.makedirs("tts_audio")
        except: pass
        
    file_path = f"tts_audio/{word_id}.mp3"
    
    # 1. 로컬에 있으면 읽어서 반환
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                return f.read()
        except:
            pass

    # 2. 없으면 gTTS로 생성 후 저장
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(file_path)
        with open(file_path, "rb") as f:
            return f.read()
    except:
        return None

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