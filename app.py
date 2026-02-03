import streamlit as st
import pandas as pd
import os
import random
from datetime import datetime, timedelta
import altair as alt 
import utils 
import streamlit.components.v1 as components
import time

# --- 화면 렌더링 함수 ---
def main():
    st.set_page_config(
        page_title="일등급 단어 마스터", 
        page_icon="📝", 
        layout="wide", 
        initial_sidebar_state="expanded" 
    )

    st.markdown("""
        <style>
            .stDeployButton { display: none !important; visibility: hidden !important; }
            .center-text { text-align: center; margin-bottom: 20px; }
            .success-sentence-box {
                background-color: #f0f2f6;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
                font-size: 1.8em !important;
                margin-bottom: 20px;
                color: #31333F;
                font-weight: 500;
            }
        </style>
    """, unsafe_allow_html=True)
    
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    
    if 'page' not in st.session_state:
        st.session_state.page = 'login'

    # 라우팅
    if st.session_state.page == 'admin':
        show_admin_page()
    elif not st.session_state.logged_in:
        show_login_page()
    else:
        # 로그인 상태라면 최신 유저 정보 가져오기 (레벨 등 동기화)
        if 'username' in st.session_state:
            user_info = utils.get_user_info(st.session_state.username)
            # 유저 정보가 없거나(삭제됨) 레벨이 비어있으면 레벨테스트로
            if user_info and (user_info['level'] is None or pd.isna(user_info['level']) or str(user_info['level']) == ''):
                 st.session_state.is_level_testing = True
                 show_level_test_page()
            elif st.session_state.get('is_level_testing', False):
                show_level_test_page()
            elif st.session_state.get('page') == 'quiz':
                show_quiz_page()
            else:
                show_dashboard_page()

# --- 콜백 (화면 상태 변경) ---
def check_answer_callback(username, curr_q, target, today):
    input_key = f"quiz_in_{st.session_state.current_idx}_{st.session_state.retry_mode}"
    user_input = st.session_state.get(input_key, "").strip()

    if user_input:
        is_correct = user_input.lower() == target.lower()
        
        if st.session_state.is_first_attempt:
             # [속도 개선] 즉시 저장하지 않고 버퍼에 추가
             if 'study_log_buffer' not in st.session_state: st.session_state.study_log_buffer = []
             timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
             # 로그 포맷: [timestamp, date, word_id, username, level, is_correct]
             st.session_state.study_log_buffer.append([
                 timestamp, str(today), int(curr_q['id']), username, int(curr_q['level']), 1 if is_correct else 0
             ])

        if is_correct:
            # [속도 개선] 메모리 상의 progress_df 사용
            if 'user_progress_df' not in st.session_state:
                st.session_state.user_progress_df = utils.load_user_progress(username)
            
            if st.session_state.is_first_attempt and st.session_state.get("quiz_mode") == "normal":
                st.session_state.user_progress_df = utils.update_schedule(curr_q['id'], True, st.session_state.user_progress_df, today)
            st.session_state.quiz_state = "success"
        else:
            if st.session_state.is_first_attempt:
                if 'user_progress_df' not in st.session_state:
                    st.session_state.user_progress_df = utils.load_user_progress(username)
                
                if st.session_state.get("quiz_mode") == "normal":
                    st.session_state.user_progress_df = utils.update_schedule(curr_q['id'], False, st.session_state.user_progress_df, today)
                st.session_state.wrong_answers.append(curr_q)
                st.session_state.is_first_attempt = False
            st.session_state.retry_mode = True

def submit_level_test_answer():
    user_input = st.session_state.test_input.strip()
    if not user_input:
        return # 빈 입력 무시
    
    process_level_test_step(user_input, is_pass=False)

def pass_level_test_question():
    process_level_test_step("", is_pass=True)

def process_level_test_step(user_input, is_pass):
    idx = len(st.session_state.test_history) + 1 # 현재 문항 번호 (1~30)
    current_q = st.session_state.current_question
    current_level = st.session_state.current_test_level
    
    # 1. 정답 확인
    is_correct = False
    if not is_pass:
        is_correct = user_input.lower() == current_q['target_word'].lower()
    
    # 2. 기록 저장
    st.session_state.test_history.append({
        'q_num': idx,
        'level': current_level,
        'word': current_q['target_word'],
        'user_input': user_input if not is_pass else "PASS",
        'result': 'correct' if is_correct else ('pass' if is_pass else 'wrong')
    })
    
    # 3. 다음 레벨 계산 (알고리즘 핵심)
    # [1단계] 광범위 탐색 (Q1 ~ Q7) -> Step 4
    # [2단계] 정밀 접근 (Q8 ~ Q22) -> Step 2 (+Bonus)
    # [3단계] 최종 검증 (Q23 ~ Q30) -> Step 1
    
    step = 0
    if idx <= 7: step = 4
    elif idx <= 22: step = 2
    else: step = 1
    
    next_level = current_level
    
    if is_correct:
        # 가속도 로직 (2단계에서 연속 정답 시 +3)
        bonus = 0
        if 8 <= idx <= 22:
            # 이전 문제도 정답이었는지 확인
            if len(st.session_state.test_history) >= 2:
                prev_res = st.session_state.test_history[-2]['result']
                if prev_res == 'correct':
                    bonus = 1 # 기본 step 2 + 1 = 3
        
        final_step = step + bonus
        
        # Gatekeeper: Lv 15 -> 16 진입 시 (2단계)
        if current_level == 15 and idx <= 22:
            # 이전 기록 확인: 이번이 Lv 15에서의 '첫' 정답이라면 대기
            # (직전 문제가 Lv 15였고 정답이었어야 통과)
            can_pass_gate = False
            if len(st.session_state.test_history) >= 2:
                prev_log = st.session_state.test_history[-2]
                if prev_log['level'] == 15 and prev_log['result'] == 'correct':
                    can_pass_gate = True
            
            if can_pass_gate:
                next_level += final_step
            else:
                pass # 레벨 유지 (한 번 더 검증)
        else:
            next_level += final_step
            
    elif is_pass:
        # 모름 버튼: 하락 폭 50%
        drop = step / 2.0
        next_level -= drop
    else:
        # 오답
        next_level -= step
        
    # 범위 제한 (1~30)
    next_level = int(round(next_level))
    next_level = max(1, min(30, next_level))
    
    # 4. 조기 종료 (Early Stop) 체크
    # Q1~Q15 구간에서, Lv 3 이하 문제를 연속 3번 이상 틀리거나 모를 때
    if idx <= 15 and current_level <= 3 and (not is_correct):
        # 최근 3개 기록 확인
        recent_fails = 0
        for log in st.session_state.test_history[-3:]:
            if log['level'] <= 3 and log['result'] in ['wrong', 'pass']:
                recent_fails += 1
        
        if recent_fails >= 3:
            st.session_state.early_stop = True
            st.session_state.final_level_result = 1
            st.session_state.test_input = "" # 입력 초기화
            return

    # 5. 다음 상태 설정
    st.session_state.current_test_level = next_level
    st.session_state.test_input = "" # 입력 초기화
    
    # 30번 문제까지 풀었으면 종료
    if idx >= 30:
        # 최종 레벨 산출: [3단계] Q23~Q30 (마지막 8개)의 평균 '출제 레벨'
        last_8_logs = st.session_state.test_history[-8:]
        avg_lv = sum(log['level'] for log in last_8_logs) / len(last_8_logs)
        st.session_state.final_level_result = int(round(avg_lv))
    else:
        # 다음 문제 로드
        exclude_ids = [log.get('q_id') for log in st.session_state.test_history if 'q_id' in log] # q_id 저장 필요.. 아차 위에서 안했네. utils 수정없이 여기서 해결
        # 위 history에 q_id가 없으므로 word로 제외하거나, 그냥 중복 허용? 
        # -> utils.get_random_question에 exclude_ids 기능 넣었으니 활용.
        # history 저장 시 q_id 추가해야 함. (아래 코드 수정)
        
        # history 마지막 항목에 q_id 업데이트 (꼼수)
        st.session_state.test_history[-1]['q_id'] = current_q['id']
        
        exclude_ids = [h.get('q_id') for h in st.session_state.test_history if 'q_id' in h]
        next_q = utils.get_random_question(next_level, exclude_ids)
        st.session_state.current_question = next_q

def show_level_test_page():
    st.markdown("""
        <style>
            .stTextInput input {
                font-size: 20px !important;
                padding: 10px !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # --- 초기화 ---
    if 'test_history' not in st.session_state:
        st.session_state.test_history = []
        st.session_state.current_test_level = 8 # 시작 레벨 8
        st.session_state.early_stop = False
        # 첫 문제 로드
        st.session_state.current_question = utils.get_random_question(8, [])
        st.session_state.final_level_result = None

    # --- 결과 화면 ---
    if st.session_state.final_level_result is not None:
        final_lv = st.session_state.final_level_result
        if final_lv < 1: final_lv = 1
        
        _, col, _ = st.columns([1, 2, 1])
        with col:
            st.balloons()
            with st.container(border=True):
                if st.session_state.early_stop:
                    st.markdown(f"<h2 style='text-align: center;'>🛑 테스트 조기 종료</h2>", unsafe_allow_html=True)
                    st.info("기초부터 탄탄히 다져봅시다! (Lv.1 배정)")
                else:
                    st.markdown(f"<h2 style='text-align: center;'>🎉 테스트 완료!</h2>", unsafe_allow_html=True)
                    st.markdown(f"<h4 style='text-align: center;'>당신의 레벨은 <b>Lv.{final_lv}</b> 입니다.</h4>", unsafe_allow_html=True)
                
                st.write("---")
                if st.button("✅ 이 레벨로 시작하기", type="primary", use_container_width=True):
                    utils.update_user_level(st.session_state.username, final_lv)
                    st.success(f"레벨 {final_lv}로 설정되었습니다!")
                    time.sleep(1)
                    st.session_state.is_level_testing = False
                    st.session_state.page = 'dashboard'
                    # 세션 정리
                    del st.session_state.test_history
                    del st.session_state.current_test_level
                    del st.session_state.current_question
                    del st.session_state.final_level_result
                    if 'early_stop' in st.session_state: del st.session_state.early_stop
                    st.rerun()
                    
                if st.button("🔄 재시험", use_container_width=True):
                    del st.session_state.test_history
                    del st.session_state.current_test_level
                    del st.session_state.current_question
                    del st.session_state.final_level_result
                    if 'early_stop' in st.session_state: del st.session_state.early_stop
                    st.rerun()
                    
            # 상세 기록 (디버깅/확인용)
            with st.expander("📝 상세 기록 보기"):
                history_df = pd.DataFrame(st.session_state.test_history)
                if not history_df.empty:
                    st.dataframe(history_df[['q_num', 'level', 'word', 'result']], use_container_width=True)
        return

    # --- 문제 진행 화면 ---
    q = st.session_state.current_question
    idx = len(st.session_state.test_history) + 1
    cur_lv = st.session_state.current_test_level
    
    # 진행 단계 표시
    stage_name = ""
    if idx <= 7: stage_name = "1단계: 탐색"
    elif idx <= 22: stage_name = "2단계: 정밀 접근"
    else: stage_name = "3단계: 최종 검증"
    
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.progress(idx / 30)
        st.caption(f"문제 {idx} / 30 ({stage_name} - Lv.{cur_lv})")
        
        with st.container(border=True):
            st.subheader(f"💡 뜻: {q['meaning']}")
            st.write(f"📖 해석: {q['sentence_ko']}")
            masked = utils.get_masked_sentence(q['sentence_en'], q['target_word'], q.get('root_word'))
            st.markdown(f"<div style='background:#f0f2f6; padding:15px; border-radius:10px; font-size:1.2em; font-weight:bold;'>{masked}</div>", unsafe_allow_html=True)
        
        st.text_input("정답 입력", key="test_input", on_change=submit_level_test_answer, label_visibility="collapsed", placeholder="정답 입력 후 Enter")
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("제출 (Enter)", type="primary", use_container_width=True, on_click=submit_level_test_answer):
                pass
        with c2:
            if st.button("🤷‍♂️ 잘 모르겠어요 (Pass)", use_container_width=True, on_click=pass_level_test_question):
                pass
        
        utils.focus_element("input")

def show_dashboard_page():
    username = st.session_state.username
    user_info = utils.get_user_info(username)
    realname = user_info['name'] if user_info else username
    user_level = int(user_info['level']) if user_info and pd.notna(user_info['level']) else 1
    
    progress_df = utils.load_user_progress(username)
    real_today = utils.get_korea_today()

    with st.sidebar:
        st.title(f"👤 {realname}")
        st.subheader(f"LEVEL {user_level}")
        st.divider()
        
        if st.button("🔄 레벨 테스트 다시 보기", use_container_width=True):
            keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
            for k in keys_to_delete:
                if k in st.session_state: del st.session_state[k]
            st.session_state.is_level_testing = True
            st.rerun()
        
        st.caption("⚠️ 주의: 결과에 따라 새로운 레벨이 부여됩니다.")

        st.divider()
        with st.expander("🔐 비밀번호 변경"):
            with st.form("change_pw_form"):
                current_pw = st.text_input("현재 비밀번호", type="password")
                new_pw = st.text_input("새 비밀번호", type="password")
                confirm_pw = st.text_input("새 비밀번호 확인", type="password")
                
                if st.form_submit_button("변경하기"):
                    if new_pw != confirm_pw:
                        st.error("새 비밀번호가 일치하지 않습니다.")
                    elif not new_pw:
                        st.error("비밀번호를 입력하세요.")
                    else:
                        user_info = utils.get_user_info(username)
                        if user_info and utils.check_hashes(current_pw, user_info['password']):
                            if utils.reset_user_password(username, new_pw):
                                st.success("변경 완료! 다시 로그인하세요.")
                                time.sleep(1.5)
                                st.session_state.logged_in = False
                                st.session_state.page = 'login'
                                st.rerun()
                            else:
                                st.error("변경 실패 (시스템 오류)")
                        else:
                            st.error("현재 비밀번호가 틀렸습니다.")
            
        st.write("")
        if st.button("로그아웃", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.page = 'login'
            if 'signup_success' in st.session_state: del st.session_state['signup_success']
            # 세션 초기화
            for k in list(st.session_state.keys()):
                if k not in ['logged_in', 'page']: del st.session_state[k]
            st.rerun()

    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        st.markdown(f"<h1 style='text-align: center;'>👋 안녕하세요, {realname} 학생!</h1>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='text-align: center; color: #4e8cff;'>현재 레벨: Lv.{user_level}</h4>", unsafe_allow_html=True)
        st.write("") 

        total_learned = len(progress_df)
        long_term_count = len(progress_df[progress_df['interval'] > 14])
        # 오늘 날짜보다 '작거나 같은'(<=) 리뷰 대상 단어
        if 'next_review' in progress_df.columns:
            review_count = len(progress_df[progress_df['next_review'] <= real_today])
        else:
            review_count = 0

        with st.container(border=True):
            st.markdown("##### 📊 나의 학습 현황")
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("총 단어", f"{total_learned}개")
            with c2: st.metric("마스터", f"{long_term_count}개")
            with c3: st.metric("오늘 복습", f"{review_count}개", delta_color="inverse")

        st.write("") 
        with st.container(border=True):
            st.markdown("##### 🎯 오늘의 목표 설정")
            if 'batch_size' not in st.session_state: st.session_state.batch_size = 5
            
            with st.form("goal_setting_form"):
                batch_option = st.slider("한 번에 학습할 문제 수", 1, 30, st.session_state.batch_size, 1)
                st.write("")
                start_btn = st.form_submit_button("🚀 학습 시작하기", type="primary", use_container_width=True)
            
            if start_btn:
                with st.spinner("학습 데이터를 준비 중입니다..."):
                    # [속도 개선] 미리 데이터 로드하여 세션에 저장
                    st.session_state.user_progress_df = utils.load_user_progress(username)
                    st.session_state.study_log_buffer = []
                    st.session_state.batch_size = batch_option
                    keys_to_delete = ['full_quiz_list', 'quiz_list', 'current_idx', 'wrong_answers', 'quiz_list_offset']
                    for k in keys_to_delete:
                        if k in st.session_state: del st.session_state[k]
                    st.session_state.page = 'quiz'
                    st.rerun()

def show_quiz_page():
    username = st.session_state.username
    df = utils.load_data()
    if df is None: 
        st.error("DB 연결 오류")
        return

    user_info = utils.get_user_info(username)
    user_level = int(user_info['level']) if user_info and pd.notna(user_info['level']) else 1
    
    # [속도 개선] 세션에 저장된 데이터 사용
    if 'user_progress_df' not in st.session_state:
        st.session_state.user_progress_df = utils.load_user_progress(username)
    progress_df = st.session_state.user_progress_df
    
    real_today = utils.get_korea_today()
    if st.session_state.get('is_tomorrow_mode', False):
        today = real_today + timedelta(days=1)
    else:
        today = real_today

    batch_size = st.session_state.batch_size

    with st.sidebar:
        if st.button("🏠 홈으로 (대시보드)"):
            st.session_state.page = 'dashboard'
            st.rerun()
        st.divider()
        st.caption(f"학습 세트: {batch_size}문항")
        if st.session_state.get('is_tomorrow_mode', False):
            st.warning("⚠️ 미래 시점 테스트")

    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        st.markdown("<h2 style='text-align: center;'>🚀 일등급 영어 단어 챌린지</h2>", unsafe_allow_html=True)
        st.write("")

        if 'full_quiz_list' not in st.session_state:
            with st.spinner("문제 데이터를 불러오는 중입니다..."):
                # 1. 오늘 복습할 단어
                today_reviewed = []
                if 'last_reviewed' in progress_df.columns:
                    today_reviewed = progress_df[progress_df['last_reviewed'] == today]['word_id'].tolist()
                
                review_q = []
                if 'next_review' in progress_df.columns:
                    review_ids = progress_df[
                        (progress_df['next_review'] <= today) & 
                        (~progress_df['word_id'].isin(today_reviewed))
                    ]['word_id'].tolist()
                    review_q = df[df['id'].isin(review_ids)].to_dict('records')
                
                # 2. 신규 학습 단어
                learned_ids = progress_df['word_id'].tolist() if 'word_id' in progress_df.columns else []
                unlearned_df = df[~df['id'].isin(learned_ids)]
                
                new_q = []
                if not unlearned_df.empty:
                    # 레벨 비율 조정 (현재 레벨 50%, 하위 20%, 상위 30%)
                    lv_current = unlearned_df[unlearned_df['level'] == user_level]
                    lv_lower = unlearned_df[unlearned_df['level'] < user_level]
                    lv_higher = unlearned_df[unlearned_df['level'] > user_level]
                    
                    needed_new = batch_size 
                    
                    count_current = int(needed_new * 0.5)
                    count_lower = int(needed_new * 0.2)
                    count_higher = needed_new - count_current - count_lower
                    
                    samples_current = lv_current.sample(n=min(len(lv_current), count_current)).to_dict('records')
                    samples_lower = lv_lower.sample(n=min(len(lv_lower), count_lower)).to_dict('records')
                    samples_higher = lv_higher.sample(n=min(len(lv_higher), count_higher)).to_dict('records')
                    
                    new_q = samples_current + samples_lower + samples_higher
                    
                    # 부족하면 나머지에서 채움
                    if len(new_q) < needed_new:
                        remaining_ids = [q['id'] for q in new_q]
                        rest_df = unlearned_df[~unlearned_df['id'].isin(remaining_ids)]
                        more_needed = needed_new - len(new_q)
                        additional_samples = rest_df.sample(n=min(len(rest_df), more_needed)).to_dict('records')
                        new_q += additional_samples
                
                random.shuffle(review_q)
                random.shuffle(new_q)
                combined = review_q + new_q
                
                # 퀴즈 리스트 세팅
                st.session_state.full_quiz_list = combined
                st.session_state.quiz_list = combined[:batch_size]
                st.session_state.current_idx = 0
                st.session_state.wrong_answers = []
                st.session_state.retry_mode = False
                st.session_state.is_first_attempt = True
                st.session_state.quiz_state = "answering"
                st.session_state.quiz_mode = "normal"

        if not st.session_state.quiz_list:
             st.info("👏 오늘의 모든 학습을 완료했습니다!")
             if st.button("🏠 대시보드로 돌아가기", use_container_width=True):
                 st.session_state.page = 'dashboard'
                 st.rerun()
             return

        if st.session_state.current_idx >= len(st.session_state.quiz_list):
            handle_session_end(username, progress_df, today)
            return

        idx = st.session_state.current_idx
        curr_q = st.session_state.quiz_list[idx]
        target = curr_q['target_word']
        
        # TTS 오디오 가져오기 (파일이 없으면 생성)
        audio_data = utils.text_to_speech(curr_q['id'], curr_q['sentence_en'])
        
        st.write(f"**Question {idx + 1} / {len(st.session_state.quiz_list)}**")
        st.progress((idx) / len(st.session_state.quiz_list))

        if st.session_state.quiz_state == "answering":
            with st.container(border=True):
                st.subheader(f"💡 뜻: {curr_q['meaning']}")
                st.write(f"📖 해석: {curr_q['sentence_ko']}")
                masked_sentence = utils.get_masked_sentence(curr_q['sentence_en'], target, curr_q.get('root_word'))
                st.info(f"### {masked_sentence}")

            if st.session_state.retry_mode:
                st.error(f"❌ 정답은 **{target}** 입니다. 다시 입력하세요.")

            input_key = f"quiz_in_{idx}_{st.session_state.retry_mode}"
            
            st.text_input("정답 입력:", key=input_key, label_visibility="collapsed", placeholder="정답 입력 후 엔터", 
                          on_change=check_answer_callback, args=(username, curr_q, target, today))
            utils.focus_element("input")

        elif st.session_state.quiz_state == "success":
            with st.container(border=True):
                root = curr_q.get('root_word', '')
                if root and isinstance(root, str) and root.strip() and root.lower() != target.lower():
                    st.success(f"✅ 정답! **{target}** (원형: {root})")
                else:
                    st.success(f"✅ 정답! **{target}**")
                
                highlighted_html = utils.get_highlighted_sentence(curr_q['sentence_en'], target)
                st.markdown(f"""<div class="success-sentence-box">{highlighted_html}</div>""", unsafe_allow_html=True)
                
                if audio_data:
                    st.audio(audio_data, format='audio/mp3', autoplay=True)

            if st.button("다음 문제 ➡ (Enter)", type="primary", key=f"next_btn_{idx}", use_container_width=True, on_click=go_next_question):
                pass
            utils.focus_element("button")

if __name__ == "__main__":
    main()
