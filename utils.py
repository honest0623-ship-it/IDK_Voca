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
LEVEL_DOWN_ACCURACY = 0.5
LEVEL_UP_ACCURACY = 0.8
MIN_TRAIN_DAYS = 0
MIN_TRAIN_COUNT = 20
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

def read_sheet_to_df(tab_name, use_cache: bool = True):
    """데이터 읽기 (기본: 90초 캐시). 쓰기 후 bump_sheet_cache_ver()로 무효화."""
    if use_cache:
        return _read_sheet_to_df_cached(str(tab_name), _get_sheet_cache_ver())
    return _read_sheet_to_df_uncached(tab_name)

# --- [NEW] 시스템 설정 관리 (Config) ---
@st.cache_data(ttl=60)
def get_system_config():
    """
    구글 시트 'config' 탭에서 설정을 읽어옴.
    없으면 탭을 생성하고 기본값 저장.
    반환: {'signup_code': '...', 'admin_pw': '...'}
    """
    default_config = {
        'signup_code': '',
        'admin_pw': ''
    }
    
    # 1. 시트 읽기
    df = read_sheet_to_df('config', use_cache=False)
    
    # 2. 데이터가 없으면 초기화
    if df.empty or 'key' not in df.columns:
        init_config_sheet(default_config)
        return default_config
    
    # 3. 딕셔너리로 변환
    config_dict = {}
    try:
        for _, row in df.iterrows():
            config_dict[row['key']] = row['value']
    except:
        return default_config
        
    # 필수 키가 없으면 기본값 병합
    for k, v in default_config.items():
        if k not in config_dict:
            config_dict[k] = v
            
    return config_dict

def init_config_sheet(default_config):
    """config 시트 초기화"""
    try:
        sh = _get_spreadsheet()
        try:
            ws = sh.worksheet('config')
            ws.clear()
        except:
            ws = sh.add_worksheet(title='config', rows=20, cols=2)
            
        # 헤더 및 기본 데이터 쓰기
        data = [['key', 'value']]
        for k, v in default_config.items():
            data.append([k, v])
        ws.update(data)
    except Exception as e:
        print(f"Config Init Error: {e}")

def update_system_config(key, new_value):
    """설정값 업데이트 (시트 전체 갱신 방식)"""
    current = get_system_config()
    current[key] = new_value
    
    try:
        sh = _get_spreadsheet()
        try:
            ws = sh.worksheet('config')
        except:
            ws = sh.add_worksheet(title='config', rows=20, cols=2)
        
        ws.clear()
        data = [['key', 'value']]
        for k, v in current.items():
            data.append([k, v])
        ws.update(data)
        
        st.cache_data.clear() # 캐시 초기화
        return True
    except Exception as e:
        st.error(f"설정 저장 실패: {e}")
        return False

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


def batch_log_study_results(rows):
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

def get_all_study_logs():
    """모든 학습 로그 로드 (관리자용 - 전체 유저)"""
    df = read_sheet_to_df('study_log')
    if df.empty:
        return pd.DataFrame()

    # 컬럼 보정
    for col in ['timestamp', 'date', 'word_id', 'username', 'level', 'is_correct']:
        if col not in df.columns:
            df[col] = None

    # 날짜 및 숫자 변환
    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
    df['word_id'] = pd.to_numeric(df['word_id'], errors='coerce')
    df['level'] = pd.to_numeric(df['level'], errors='coerce')
    df['is_correct'] = pd.to_numeric(df['is_correct'], errors='coerce')

    df = df.dropna(subset=['date'])
    df['word_id'] = df['word_id'].fillna(0).astype(int)
    df['level'] = df['level'].fillna(0).astype(int)
    df['is_correct'] = df['is_correct'].fillna(0).astype(int)

    return df

def get_all_users():
    """모든 사용자 정보 로드 (관리자용)"""
    df = read_sheet_to_df('users')
    if df.empty:
        return pd.DataFrame(columns=['username', 'name', 'level'])
    
    # 필수 컬럼 보장
    for col in ['username', 'name', 'level']:
        if col not in df.columns:
            df[col] = ''
            
    return df

def get_user_info(username):
    df = read_sheet_to_df('users')
    if df.empty: return None
    
    if username in df['username'].values:
        user_row = df[df['username'] == username].iloc[0]
        lv = user_row.get('level', '')
        
        # Helper to safely get int
        def _safe_int(val, default):
            try: return int(float(val))
            except: return default

        final_lv = _safe_int(lv, 1)
        
        # Read new fields
        fail_streak = _safe_int(user_row.get('fail_streak'), 0)
        level_shield = _safe_int(user_row.get('level_shield'), 3)
        qs_count = _safe_int(user_row.get('qs_count'), 0)
        pending_wrongs = str(user_row.get('pending_wrongs', ''))
        pending_session = str(user_row.get('pending_session', ''))

        return {
            'level': final_lv, 
            'name': user_row['name'], 
            'password': user_row['password'],
            'fail_streak': fail_streak,
            'level_shield': level_shield,
            'qs_count': qs_count,
            'pending_wrongs': pending_wrongs,
            'pending_session': pending_session
        }
    return None

def manage_session_state(username, action, data):
    """
    진행 중인 세션(pending_session) 관리
    action: 'set' (list of ids) or 'remove' (single id)
    """
    if action == 'set':
        # data expected to be list of ints or strings
        new_str = ",".join(str(x) for x in data)
        update_user_dynamic_fields(username, {'pending_session': new_str})
        
    elif action == 'remove':
        # data expected to be single id
        user_info = get_user_info(username)
        if not user_info: return
        
        current_str = user_info.get('pending_session', '')
        current_ids = [x.strip() for x in current_str.split(',') if x.strip()]
        str_id = str(data)
        
        if str_id in current_ids:
            current_ids.remove(str_id)
            new_str = ",".join(current_ids)
            update_user_dynamic_fields(username, {'pending_session': new_str})

def manage_pending_wrongs(username, action, word_id):
    """
    오답노트(pending_wrongs) 관리
    action: 'add' or 'remove'
    """
    # 1. 현재 상태 가져오기
    user_info = get_user_info(username)
    if not user_info: return
    
    current_str = user_info.get('pending_wrongs', '')
    current_ids = [x.strip() for x in current_str.split(',') if x.strip()]
    
    str_id = str(word_id)
    changed = False
    
    if action == 'add':
        if str_id not in current_ids:
            current_ids.append(str_id)
            changed = True
    elif action == 'remove':
        if str_id in current_ids:
            current_ids.remove(str_id)
            changed = True
            
    if changed:
        new_str = ",".join(current_ids)
        update_user_dynamic_fields(username, {'pending_wrongs': new_str})

def update_user_dynamic_fields(username, updates):
    """
    updates: dict of {'col_name': value}
    Available cols: level, fail_streak, level_shield, qs_count
    """
    for attempt in range(3):
        try:
            ws = get_worksheet('users')
            if not ws: return False

            # 1. 헤더 확인 및 추가
            headers = ws.row_values(1)
            header_map = {h: i+1 for i, h in enumerate(headers)}
            
            new_headers = []
            for col in updates.keys():
                if col not in header_map:
                    new_headers.append(col)
            
            if new_headers:
                # 헤더 추가
                ws.update_cell(1, len(headers) + 1, new_headers[0]) # 하나씩 추가 (단순화)
                # 캐시 무효화 후 재귀 호출로 다시 시도 (헤더 갱신 위해)
                bump_sheet_cache_ver()
                if len(new_headers) > 1:
                     # 여러개면 recursive하게 처리하거나 그냥 루프
                     pass 
                return update_user_dynamic_fields(username, updates)

            # 2. 유저 행 찾기
            cell = ws.find(username, in_column=1)
            if not cell: return False
            
            # 3. 값 업데이트
            # gspread batch update is better but cell update is simpler for now
            # We use a list of cells to update for atomicity if possible, but update_cells requires Cell objects
            # Let's just update one by one for reliability or construct a range
            
            cells_to_update = []
            for col, val in updates.items():
                col_idx = header_map[col]
                ws.update_cell(cell.row, col_idx, val)
                
            bump_sheet_cache_ver()
            return True

        except Exception as e:
            if "429" in str(e):
                time.sleep(2)
                continue
            print(f"Update User Fields Error: {e}")
            break
    return False

def evaluate_level_update(current_level, correct_count, total_questions, fail_streak, level_shield, max_level=30):
    """
    "방어 구간(Buffer) & 연패 방지" 로직
    """
    score_percent = (correct_count / total_questions) * 100
    change = 0
    message = ""
    
    # Next state defaults
    next_streak = fail_streak
    next_shield = level_shield

    # 1. [초고속 승급] 95점 이상 (19~20개) -> 2단계 점프
    if score_percent >= 95:
        change = 2
        next_streak = 0
        next_shield = 3 # 새 레벨 쉴드 충전
        message = "완벽해요! 실력이 압도적이라 2단계 승급합니다! 🚀"

    # 2. [승급] 80점 이상 (16~18개) -> 1단계 상승
    elif score_percent >= 80:
        change = 1
        next_streak = 0
        next_shield = 3 # 새 레벨 쉴드 충전
        message = "참 잘했어요! 다음 레벨로 올라갑니다. 🎉"

    # 3. [유지] 60점 ~ 79점 (12~15개) -> 현상 유지
    elif score_percent >= 60:
        change = 0
        next_streak = 0 # 중간만 가도 경고 초기화
        # 쉴드 차감
        if next_shield > 0:
            next_shield -= 1
        message = "수고했어요. 현재 레벨을 유지하며 실력을 다져봅시다."

    # 4. [하향 위기] 60점 미만 (11개 이하)
    else:
        change = 0
        # A. 쉴드 확인
        if next_shield > 0:
            next_shield -= 1
            message = f"아직 적응 기간이에요. 괜찮습니다! (남은 보호 횟수: {next_shield})"
        else:
            # B. 연패 체크
            next_streak += 1
            if next_streak >= 2:
                change = -1
                next_streak = 0
                next_shield = 3 # 레벨 내려가면 다시 적응 기회 부여
                message = "너무 어려웠나요? 한 단계 낮춰서 기초를 복습해봐요. ⬇️"
            else:
                message = "⚠ 주의! 다음에도 점수가 낮으면 레벨이 내려갈 수 있어요."

    new_level = current_level + change
    new_level = max(1, min(new_level, max_level))
    
    return new_level, next_streak, next_shield, message

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
        if interval_days >= 240: # 8개월 이상
            return _add_months(base_date, 8)
        if interval_days >= 120:
            return _add_months(base_date, 4)
        if interval_days >= 60:
            return _add_months(base_date, 2)
        return base_date + timedelta(days=int(interval_days))

    JUMP_INTERVAL = 240 # 8개월 (약 240일)
    RETIRE_DATE = datetime(9999, 12, 31).date()

    if 'word_id' in progress_df.columns and word_id in progress_df['word_id'].values:
        idx = progress_df[progress_df['word_id'] == word_id].index[0]
        
        # 이전 기록 가져오기 (업데이트 전)
        prev_last_reviewed = progress_df.loc[idx, 'last_reviewed']
        cur_interval = _to_int(progress_df.loc[idx, 'interval'], 0)
        
        progress_df.loc[idx, 'last_reviewed'] = today
        cur_fail = _to_int(progress_df.loc[idx, 'fail_count'], 0)

        if is_correct:
            # 1. 은퇴(졸업) 체크: 이미 8개월(240일) 간격이었던 단어를 맞춤 -> 영구 졸업
            if cur_interval >= JUMP_INTERVAL:
                progress_df.loc[idx, 'next_review'] = RETIRE_DATE
                # interval은 그대로 유지하거나 졸업 코드 부여 (여기선 유지)
            else:
                # 2. 8개월 점프 체크: 마지막 리뷰로부터 30일 이상 지났는데 한 번에 맞춤
                days_since = (today - prev_last_reviewed).days if pd.notna(prev_last_reviewed) else 0
                
                if days_since >= 30:
                    progress_df.loc[idx, 'interval'] = JUMP_INTERVAL
                    progress_df.loc[idx, 'next_review'] = _add_months(today, 8)
                else:
                    # 3. 일반 SRS 로직
                    if cur_fail > 0:
                        if cur_interval <= 0:
                            cur_interval = 1
                        new_interval = _next_step(cur_interval)
                        progress_df.loc[idx, 'interval'] = int(new_interval)
                        progress_df.loc[idx, 'next_review'] = _calc_next_review(today, int(new_interval))
                    else:
                        # 오답 경험 없는 단어 (30일 이내 재학습): 기존 로직 유지 (2개월)
                        # 혹시 interval이 너무 짧다면 조정 가능하나, 기존 로직 따름
                        progress_df.loc[idx, 'interval'] = 60
                        progress_df.loc[idx, 'next_review'] = _add_months(today, 2)
        else:
            progress_df.loc[idx, 'fail_count'] = int(cur_fail) + 1
            progress_df.loc[idx, 'interval'] = 1
            progress_df.loc[idx, 'next_review'] = today + timedelta(days=1)

    else:
        # 신규 단어
        if is_correct:
            # 처음 출제된 문제를 한 번에 맞춤 -> 8개월 뒤 출제
            new_row = {
                'word_id': int(word_id),
                'last_reviewed': today,
                'interval': JUMP_INTERVAL,
                'fail_count': 0,
                'next_review': _add_months(today, 8)
            }
        else:
            # 틀림 -> 1일 뒤
            new_row = {
                'word_id': int(word_id),
                'last_reviewed': today,
                'interval': 1,
                'fail_count': 1,
                'next_review': today + timedelta(days=1)
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
def get_random_question(level, exclude_ids=[]):
    """지정된 레벨의 랜덤 문제 1개 반환 (없으면 근접 레벨 탐색)"""
    df = load_data()
    if df is None or df.empty:
        return None
    
    # 1. 해당 레벨의 단어 필터링 (exclude_ids 제외)
    base_pool = df
    if exclude_ids:
        base_pool = df[~df['id'].isin(exclude_ids)]
        if base_pool.empty: base_pool = df # 제외 후 없으면 전체에서 (중복 허용)

    candidates = base_pool[base_pool['level'] == level]
    
    # 2. 해당 레벨에 단어가 없으면 -> 가장 가까운 레벨 찾기
    if candidates.empty:
        available_levels = base_pool['level'].unique()
        if len(available_levels) > 0:
            # 현재 level과 차이가 가장 적은 레벨 찾기
            nearest_level = min(available_levels, key=lambda x: abs(x - level))
            candidates = base_pool[base_pool['level'] == nearest_level]
        else:
            candidates = base_pool # 정말 데이터가 없는 경우

    if candidates.empty:
        return None
        
    return candidates.sample(n=1).iloc[0].to_dict()

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
    """
    단어 난이도 자동 조정 (Weighted Gap Algorithm)
    - 학생 레벨과 단어 레벨의 차이를 가중치로 사용
    - 고레벨 학생이 틀리면 단어 레벨 상승 (강력)
    - 저레벨 학생이 맞추면 단어 레벨 하락 (강력)
    """
    try:
        logs_df = get_all_study_logs()
        words_df = load_data()
        
        if logs_df.empty or words_df is None:
            return 0, "데이터가 부족합니다."

        # 단어별 현재 레벨 매핑
        word_levels = dict(zip(words_df['id'], words_df['level']))
        
        # 조정 점수 계산
        adjustment_scores = {} # word_id -> score
        
        # 로그 분석 (최근 1000건 정도만? 아니면 전체? 일단 전체 하되 데이터 많으면 최적화 필요)
        # 여기선 전체 분석
        for _, row in logs_df.iterrows():
            word_id = row['word_id']
            user_lv = row['level'] # 로그 당시 유저 레벨 (이걸 써야 정확함. 현재 유저 레벨보다 기록 당시 상황이 중요)
            is_correct = row['is_correct']
            
            if word_id not in word_levels: continue
            
            cur_word_lv = word_levels[word_id]
            gap = user_lv - cur_word_lv
            
            score = 0
            if is_correct:
                if gap < 0: # 저레벨 학생이 맞춤 (쉬움)
                    score = -abs(gap) * 2.0
                elif gap == 0:
                    score = -0.5
                # gap > 0 (고레벨이 맞춤) -> 당연함 (변동 없음)
            else:
                if gap > 0: # 고레벨 학생이 틀림 (어려움)
                    score = abs(gap) * 2.0
                elif gap == 0:
                    score = 0.5
                # gap < 0 (저레벨이 틀림) -> 당연함 (변동 없음)
                
            adjustment_scores[word_id] = adjustment_scores.get(word_id, 0) + score

        # 변경 대상 선별 (Threshold: +/- 15점)
        THRESHOLD = 15
        updates = []
        
        for word_id, score in adjustment_scores.items():
            current_lv = word_levels[word_id]
            new_lv = current_lv
            
            if score >= THRESHOLD:
                new_lv += 1
            elif score <= -THRESHOLD:
                new_lv -= 1
                
            # 범위 제한 (1~30)
            new_lv = max(1, min(30, new_lv))
            
            if new_lv != current_lv:
                updates.append((new_lv, word_id))
        
        # DB 업데이트
        if updates:
            ws = get_worksheet('voca_db')
            if not ws: return 0, "DB 연결 실패"
            
            # Batch Update가 효율적이나, gspread cell 찾기 로직이 필요.
            # 여기서는 안전하게 하나씩 업데이트하거나, 전체 데이터를 다시 쓰는 방식 고려.
            # voca_db는 크기가 클 수 있으므로, 변경된 것만 cell update 권장.
            # 하지만 find 호출이 많으면 느림. -> 전체 다시 쓰기가 나을 수도 있음 (데이터 1000개 미만이면).
            # 일단 안전하게 cell update 시도 (개수가 적을 것으로 예상).
            
            count = 0
            # 성능을 위해 전체 데이터를 로드해서 메모리에서 수정 후 덮어쓰기 (가장 확실)
            all_data = ws.get_all_values()
            headers = all_data[0]
            id_idx = headers.index('id')
            lv_idx = headers.index('level')
            
            id_map = {int(row[id_idx]): i for i, row in enumerate(all_data) if i > 0 and row[id_idx].isdigit()}
            
            changed = False
            for new_lv, w_id in updates:
                if w_id in id_map:
                    row_idx = id_map[w_id]
                    all_data[row_idx][lv_idx] = str(new_lv)
                    changed = True
                    count += 1
            
            if changed:
                ws.update(all_data)
                bump_sheet_cache_ver()
                st.cache_data.clear() # 데이터 갱신
                return count, f"{count}개 단어의 난이도가 재조정되었습니다."
            else:
                return 0, "조정 대상이 없습니다."
                
        return 0, "조정 대상이 없습니다."

    except Exception as e:
        print(f"Level Adjust Error: {e}")
        return 0, f"오류 발생: {e}"