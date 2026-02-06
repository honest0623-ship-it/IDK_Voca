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
import database as db

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
    """시스템 설정 가져오기 (SQLite)"""
    return db.get_system_config()

def update_system_config(key, new_value):
    """설정값 업데이트 (SQLite)"""
    if db.update_system_config(key, new_value):
        st.cache_data.clear() # 캐시 초기화
        return True
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
    """voca_db 로딩 (SQLite)"""
    return db.load_all_vocab()

def load_user_progress(username):
    """사용자의 학습 진도 로드 (SQLite)"""
    return db.load_user_progress(username)

def save_progress(username, progress_df):
    """진도 저장 (SQLite)"""
    return db.save_user_progress(username, progress_df)

def save_progress_fast(username, progress_df):
    """진도 저장 (SQLite - Fast Alias)"""
    return db.save_user_progress(username, progress_df)

def save_progress_single(username, word_id, row_data):
    """단일 단어 진도 저장 (Optimized)
       row_data: Series or dict containing 'last_reviewed', 'next_review', 'interval', 'fail_count'
    """
    try:
        lr = row_data.get('last_reviewed')
        nr = row_data.get('next_review')
        iv = row_data.get('interval', 0)
        fc = row_data.get('fail_count', 0)
        return db.update_single_user_progress(username, word_id, lr, nr, iv, fc)
    except Exception as e:
        print(f"Wrapper Error: {e}")
        return False

def log_study_result(username, word_id, level, is_correct):
    today = get_korea_today()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, str(today), int(word_id), username, int(level), 1 if is_correct else 0]
    db.batch_log_study_results([row])


def batch_log_study_results(rows):
    """학습 로그를 여러 행 한 번에 append (SQLite)"""
    return db.batch_log_study_results(rows)


def load_study_log(username):
    """사용자 학습 로그 로드 (SQLite)"""
    return db.load_study_log(username)

def get_all_study_logs():
    """모든 학습 로그 로드 (관리자용 - SQLite)"""
    return db.get_all_study_logs()

def get_all_users():
    """모든 사용자 정보 로드 (관리자용 - SQLite)"""
    return db.get_all_users()

def get_user_info(username):
    """사용자 정보 가져오기 (SQLite)"""
    return db.get_user_info(username)

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
    """사용자 동적 필드 업데이트 (SQLite)"""
    return db.update_user_dynamic_fields(username, updates)

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
    """사용자 등록 (SQLite)"""
    hashed_pw = make_hashes(password)
    return db.register_user(username, hashed_pw, name)

def update_user_level(username, new_level):
    """사용자 레벨 업데이트 (SQLite)"""
    db.update_user_level(username, new_level)


def reset_user_password(username, new_password):
    """비밀번호 초기화 (SQLite)"""
    hashed_pw = make_hashes(new_password)
    return db.reset_user_password(username, hashed_pw)

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
        # [방어 로직] 혹시 문자열이면 날짜 객체로 변환
        if isinstance(prev_last_reviewed, str):
            prev_last_reviewed = pd.to_datetime(prev_last_reviewed, errors='coerce').date()
            
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
    
    # [FIX] 품질 개선: "The word '...' is important." 같은 더미 문장 제외 우선순위 적용
    # 정규식으로 더미 패턴 확인 (The word '...' is important.)
    dummy_pattern = r"^The word '.*' is important\.$"
    good_candidates = candidates[~candidates['sentence_en'].str.contains(dummy_pattern, regex=True, na=False)]
    
    if not good_candidates.empty:
        return good_candidates.sample(n=1).iloc[0].to_dict()
        
    return candidates.sample(n=1).iloc[0].to_dict()

def text_to_speech(word_id, text):
    """
    1) 텍스트 해시 기반 파일명 확인: tts_audio/{word_id}_{hash}.mp3
    2) 있으면 반환
    3) 없으면:
       - 기존 해당 word_id의 구버전/다른 해시 파일 삭제 (청소)
       - gTTS 생성 후 저장
       - 반환
    """
    # 폴더 확보
    if not os.path.exists("tts_audio"):
        try:
            os.makedirs("tts_audio")
        except: pass
        
    # 텍스트 해시 생성 (내용 변경 감지용)
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
    filename = f"{word_id}_{text_hash}.mp3"
    file_path = f"tts_audio/{filename}"
    
    # 1. 현재 텍스트와 일치하는 캐시 파일이 있으면 반환
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                return f.read()
        except:
            pass

    # 2. 없으면 새로 생성해야 함. 그 전에 구버전 파일 청소
    # (예: 101.mp3 또는 101_oldhash.mp3)
    try:
        for f in os.listdir("tts_audio"):
            # 해당 ID로 시작하는 파일 찾기
            if f.startswith(f"{word_id}.") or f.startswith(f"{word_id}_"):
                # 현재 필요한 파일이 아니면 삭제
                if f != filename:
                    try:
                        os.remove(os.path.join("tts_audio", f))
                    except:
                        pass
    except:
        pass

    # 3. gTTS로 생성 후 저장
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
    """
    JS를 이용해 지정된 요소(input 또는 button)에 포커스를 강제로 위치시킴.
    """
    components.html(
        f"""
        <script>
            try {{
                setTimeout(function() {{
                    var targets = window.parent.document.querySelectorAll('{ "input[type=text]" if target_type == "input" else "button" }');
                    if (targets.length > 0) {{
                        // 가장 마지막 요소에 포커스 (보통 현재 활성화된 컴포넌트)
                        targets[targets.length - 1].focus();
                    }}
                }}, 300);
            }} catch(e) {{
                console.log("Focus Error: " + e);
            }}
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
            if db.batch_update_vocab_levels(updates):
                st.cache_data.clear() # 데이터 갱신
                return len(updates), f"{len(updates)}개 단어의 난이도가 재조정되었습니다."
            else:
                return 0, "DB 업데이트 실패"
                
        return 0, "조정 대상이 없습니다."

    except Exception as e:
        print(f"Level Adjust Error: {e}")
        return 0, f"오류 발생: {e}"

def update_student_info(old_username, new_username, new_name, new_level):
    """학생 정보 수정 (ID, 이름, 레벨) - SQLite"""
    return db.update_student_info(old_username, new_username, new_name, new_level)

def delete_student(username):
    """학생 삭제 (관련 기록 Cascade 삭제)"""
    return db.delete_student(username)

def add_word(target_word, meaning, level, sentence_en, sentence_ko, root_word):
    """단어 추가"""
    return db.add_word(target_word, meaning, level, sentence_en, sentence_ko, root_word)

def update_word(word_id, target_word, meaning, level, sentence_en, sentence_ko, root_word):
    """단어 수정"""
    return db.update_word(word_id, target_word, meaning, level, sentence_en, sentence_ko, root_word)

def delete_word(word_id):
    """단어 삭제"""
    return db.delete_word(word_id)

def process_excel_upload(file):
    """엑셀 파일 업로드 처리"""
    try:
        df = pd.read_excel(file)
        # 컬럼 이름 공백 제거
        df.columns = [str(c).strip() for c in df.columns]
        
        if 'target_word' not in df.columns or 'meaning' not in df.columns:
            return False, "엑셀 파일에 'target_word'와 'meaning' 컬럼이 반드시 있어야 합니다."
            
        added, updated = db.bulk_upsert_words(df)
        return True, f"✅ 처리 완료: {added}개 추가, {updated}개 수정됨"
    except Exception as e:
        return False, f"오류 발생: {e}"