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

# --- 1. [REFACTORED] DB 모듈 임포트 ---
import database as db

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

# --- 3. [REMOVED] 구글 시트 관련 헬퍼 함수 ---
# get_worksheet, read_sheet_to_df 함수는 삭제됨

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

# --- 5. [REFACTORED] 데이터 로딩 ---
@st.cache_data(ttl=3600) # DB에서 읽으므로 TTL 증가 (1시간)
def load_data():
    """voca_db 전체 로드"""
    return db.load_all_vocab()

def load_user_progress(username):
    """사용자의 학습 진도 로드"""
    return db.load_user_progress(username)

def save_progress(username, progress_df):
    """진도 저장"""
    return db.save_user_progress(username, progress_df)

# --- 6. [REFACTORED] 학습 로그 ---
def batch_log_study_results(log_buffer):
    """학습 로그 일괄 저장"""
    return db.batch_log_study_results(log_buffer)

def load_study_log(username):
    """특정 유저 학습 로그 로드"""
    return db.load_study_log(username)

# --- 7. [REFACTORED] 사용자 정보 ---
def get_user_info(username):
    """DB에서 사용자 정보 가져오기"""
    user_data = db.get_user_info(username)
    if user_data:
        # level이 None, NaN, "" 이면 None으로 통일
        lv = user_data.get('level')
        if pd.isna(lv) or str(lv).strip() == '':
            final_lv = None
        else:
            try: final_lv = int(lv)
            except: final_lv = 1 # 혹시 모를 오류 방지
        user_data['level'] = final_lv
    return user_data

def register_user(username, password, name):
    """DB에 사용자 등록"""
    hashed_pw = make_hashes(password)
    return db.register_user(username, hashed_pw, name)

def update_user_level(username, new_level):
    """DB에서 사용자 레벨 업데이트"""
    return db.update_user_level(username, new_level)

def reset_user_password(username, new_password_str="1234"):
    """DB에서 사용자 비밀번호 초기화"""
    hashed_pw = make_hashes(new_password_str)
    return db.reset_user_password(username, hashed_pw)

def get_all_users():
    """모든 사용자 정보 로드 (관리자용)"""
    return db.get_all_users()

def get_all_study_logs():
    """모든 학습 로그 로드 (관리자용)"""
    return db.get_all_study_logs()


# --- 8. SRS 스케줄링 (로직 동일) ---
def update_schedule(word_id, is_correct, progress_df, today):
    # 컬럼이 없는 경우를 대비하여 초기화
    for col in ['fail_count', 'interval']:
        if col not in progress_df.columns: progress_df[col] = 0
    for col in ['last_reviewed', 'next_review']:
        if col not in progress_df.columns: progress_df[col] = pd.NaT

    def _to_int(x, default=0):
        try: return int(float(x)) if pd.notna(x) else default
        except: return default

    def _next_step(cur_days):
        # 현재 단계(일)를 기반으로 다음 복습일 계산
        if cur_days not in SRS_STEPS_DAYS:
            # SRS 표준 단계에 없으면, 현재 단계보다 작은 가장 가까운 표준 단계로 맞춤
            cur_days = max([s for s in SRS_STEPS_DAYS if s <= cur_days], default=1)
        if cur_days == 1: return 3
        if cur_days == 3: return 7
        if cur_days == 7: return 14
        return 60 # 최종 단계

    # word_id가 progress_df에 있는지 확인
    if word_id in progress_df['word_id'].values:
        idx = progress_df[progress_df['word_id'] == word_id].index[0]
        progress_df.loc[idx, 'last_reviewed'] = today
        cur_fail = _to_int(progress_df.loc[idx, 'fail_count'], 0)
        cur_interval = _to_int(progress_df.loc[idx, 'interval'], 0)

        if is_correct:
            # 정답
            if cur_fail > 0: # 이전에 틀린 적이 있다면
                if cur_interval <= 0: cur_interval = 1
                new_interval = _next_step(cur_interval)
                progress_df.loc[idx, 'interval'] = int(new_interval)
                progress_df.loc[idx, 'next_review'] = _add_months(today, 2) if new_interval >= 60 else today + timedelta(days=int(new_interval))
            else: # 한번도 안 틀렸으면 바로 최종 단계
                progress_df.loc[idx, 'interval'] = 60
                progress_df.loc[idx, 'next_review'] = _add_months(today, 2)
        else:
            # 오답
            progress_df.loc[idx, 'fail_count'] = int(cur_fail) + 1
            progress_df.loc[idx, 'interval'] = 1 # 간격 초기화
            progress_df.loc[idx, 'next_review'] = today + timedelta(days=1)
    else:
        # 새로운 단어
        new_row = {
            'word_id': word_id,
            'last_reviewed': today,
            'interval': 60 if is_correct else 1,
            'fail_count': 0 if is_correct else 1,
            'next_review': _add_months(today, 2) if is_correct else today + timedelta(days=1)
        }
        progress_df = pd.concat([progress_df, pd.DataFrame([new_row])], ignore_index=True)
    
    return progress_df


# --- 9. 기타 유틸 (로직 동일) ---
AUDIO_DIR = "tts_audio"

def get_audio_filepath(word_id):
    """지정된 단어 ID에 대한 오디오 파일 경로를 반환합니다."""
    return os.path.join(AUDIO_DIR, f"{word_id}.mp3")

def text_to_speech(word_id, text):
    """
    TTS 음성을 생성하거나, 이미 파일이 존재하면 로드합니다.
    - 파일이 있으면: 파일 내용을 읽어 반환 (빠름)
    - 파일이 없으면: gTTS로 생성하고 파일로 저장 후 내용 반환 (느림)
    """
    filepath = get_audio_filepath(word_id)

    # 오디오 파일이 이미 존재하면 파일에서 바로 읽기
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            return f.read()

    # 파일이 없으면 생성
    if not text or pd.isna(text):
        return None
        
    try:
        # 디렉터리가 없으면 생성
        if not os.path.exists(AUDIO_DIR):
            os.makedirs(AUDIO_DIR)

        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(filepath)
        
        # 저장 후 다시 읽어서 반환
        with open(filepath, 'rb') as f:
            return f.read()
            
    except Exception as e:
        print(f"TTS Error (ID: {word_id}): {e}")
        return None

def get_masked_sentence(sentence, target_word, root_word=None):
    """문장에서 단어 마스킹 처리"""
    if not isinstance(sentence, str): return sentence
    words_to_mask = [str(target_word)]
    if root_word and isinstance(root_word, str) and root_word.strip():
        words_to_mask.append(root_word.strip())
    # 긴 단어부터 마스킹해야 짧은 단어가 포함된 경우 제대로 처리됨
    words_to_mask.sort(key=len, reverse=True)
    escaped_words = [re.escape(w) for w in words_to_mask]
    pattern_str = '|'.join(escaped_words)
    pattern = re.compile(pattern_str, re.IGNORECASE)
    return pattern.sub(" [ ❓ ] ", sentence)

def get_highlighted_sentence(sentence, target_word):
    """문장에서 정답 단어 하이라이트"""
    if not isinstance(sentence, str): return sentence
    pattern = re.compile(re.escape(target_word), re.IGNORECASE)
    return pattern.sub(r"<span style='color: #E74C3C; font-weight: 900; font-size: 1.2em;'>\g<0></span>", sentence)

def focus_element(target_type="input"):
    """특정 UI 요소에 포커스"""
    # JS를 사용하여 Streamlit의 특정 요소에 포커스
    # 타임스탬프를 이용해 매번 다른 id를 가진 div를 만들어 재실행시에도 스크립트가 돌도록 함
    components.html(
        f"""
        <div id="focus_marker_{datetime.now().timestamp()}"></div>
        <script>
            setTimeout(function() {{
                var target = window.parent.document.querySelectorAll('{ "input[type=text]" if target_type == "input" else "button" }');
                if (target.length > 0) {{
                    // 가장 마지막에 렌더링된 요소에 포커스
                    target[target.length - 1].focus();
                }}
            }}, 200);
        </script>
        """,
        height=0
    )

def adjust_level_based_on_stats():
    """학생들 통계 기반으로 단어 레벨 자동 조정 (DB 연동 버전)"""
    st.info("학생들의 오답 데이터를 분석하여 단어 레벨(1~30)을 자동 조정합니다.")
    
    # 1. 모든 학습 로그와 단어 정보 로드
    all_logs = db.get_all_study_logs()
    all_vocab = db.load_all_vocab()

    if all_logs.empty or all_vocab.empty:
        return 0, "조정할 데이터가 부족합니다."

    # 2. 단어별 정답률 계산
    # word_id 별로 그룹화하여 총 시도 횟수와 오답 횟수 계산
    stats = all_logs.groupby('word_id')['is_correct'].agg(['count', lambda x: (x==0).sum()]).reset_index()
    stats.columns = ['word_id', 'total_try', 'total_wrong']
    
    # 정답률과 조정 점수 계산
    stats['accuracy'] = 1 - (stats['total_wrong'] / stats['total_try'])
    
    # 최소 5회 이상 시도된 단어만 대상으로 함
    stats = stats[stats['total_try'] >= 5]
    if stats.empty:
        return 0, "통계적으로 유의미한 데이터가 부족합니다 (단어별 최소 5회 이상 학습 필요)."

    # 3. 레벨 조정 로직
    # 정답률에 따라 레벨을 올리거나 내림
    # 예: 정답률 90% 이상 -> +1, 50% 미만 -> -1
    adjustments = []
    for _, row in stats.iterrows():
        word_id = row['word_id']
        accuracy = row['accuracy']
        
        current_level_series = all_vocab[all_vocab['id'] == word_id]['level']
        if current_level_series.empty: continue
        current_level = current_level_series.iloc[0]

        new_level = current_level
        if accuracy > 0.9 and current_level < 30:
            new_level = current_level + 1
        elif accuracy < 0.5 and current_level > 1:
            new_level = current_level - 1
        
        if new_level != current_level:
            adjustments.append({'id': word_id, 'new_level': new_level})
    
    if not adjustments:
        return 0, "레벨 조정이 필요한 단어가 없습니다."

    # 4. DB에 업데이트
    conn = db.get_db_connection()
    try:
        c = conn.cursor()
        for adj in adjustments:
            c.execute("UPDATE voca_db SET level = ? WHERE id = ?", (adj['new_level'], adj['id']))
        conn.commit()
        return len(adjustments), f"{len(adjustments)}개 단어의 레벨이 조정되었습니다."
    except Exception as e:
        return 0, f"DB 업데이트 실패: {e}"
    finally:
        conn.close()