import streamlit as st
import pandas as pd
import os
import random
from datetime import datetime, timedelta
import altair as alt 
import utils 
import streamlit.components.v1 as components
import time

# --- 화면 렌더링 함수 (메인 진입점) ---
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
                padding: 15px;
                border-radius: 10px;
                text-align: center;
                font-size: 1.2em !important;
                margin-bottom: 15px;
                color: #31333F;
                font-weight: 500;
                line-height: 1.5;
            }
            /* [NEW] 모바일 당겨서 새로고침 방지 (Overscroll Prevention) */
            html, body {
                overscroll-behavior-y: contain !important;
            }
            /* [NEW] Streamlit 기본 Footer 및 햄버거 메뉴 숨기기 */
            footer {visibility: hidden; display: none !important;}
            #MainMenu {visibility: hidden; display: none !important;}
            header {visibility: hidden; display: none !important;}
            [data-testid="stHeader"] {visibility: hidden; display: none !important;}
            [data-testid="stToolbar"] {visibility: hidden; display: none !important;}
            .stApp > header {display: none !important;}
            .stApp > footer { display: none !important; }
            
            /* [NEW] Streamlit Cloud 전용 요소 숨기기 (Manage App 버튼 등) */
            .stAppDeployButton { display: none !important; }
            [data-testid="stDecoration"] { display: none !important; }
            [data-testid="stStatusWidget"] { display: none !important; }
            
            /* 하단 고정 링크 (Made with Streamlit 등) 타겟팅 */
            a[href*="streamlit.io"] { display: none !important; }
            a[href*="share.streamlit.io"] { display: none !important; }
            button[kind="header"] { display: none !important; }
            .viewerBadge_container__1QSob { display: none !important; }
            .styles_viewerBadge__1yB5_ { display: none !important; }
            
            /* [STRONG] 하단 고정 요소 강제 숨김 (우측 하단 아이콘들) */
            div[style*="position: fixed"][style*="bottom:"] { display: none !important; }
            #root > div:nth-child(1) > div > div > div > div > section[data-testid="stSidebar"] > div > div:nth-child(2) { display: none !important; }
            
            /* Streamlit Cloud Toolbar & Footer Kill List */
            [data-testid="manage-app-button"] { display: none !important; }
            div[class*="st-emotion-cache"] { z-index: 0; } /* 본문이 위로 오도록 */
            
            /* iframe으로 삽입되는 외부 요소들(혹시 모를) 숨김 시도 */
            iframe[title="streamlit-footer"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    # [NEW] 새로고침/뒤로가기 방지 및 하단 버튼 강제 제거 스크립트
    components.html("""
        <script>
            // 1. 뒤로가기 방지
            try {
                window.parent.addEventListener('beforeunload', function (e) {
                    e.preventDefault();
                    e.returnValue = ''; 
                });
            } catch (err) {
                console.log("Prevention Script Error: " + err);
            }

            // 2. [Mobile Fix] Streamlit Cloud UI 강제 제거 (0.3초마다 실행)
            function killStreamlitUI() {
                try {
                    // (1) 텍스트/링크 기반 제거
                    const anchors = window.parent.document.querySelectorAll('a');
                    anchors.forEach(a => {
                        if (a.href.includes('streamlit.io')) {
                            a.style.display = 'none';
                            a.style.visibility = 'hidden';
                        }
                    });

                    // (2) 클래스/ID 기반 제거
                    const targets = [
                        '.stAppDeployButton', 
                        '[data-testid="stHeader"]', 
                        '[data-testid="stToolbar"]', 
                        '[data-testid="manage-app-button"]',
                        'div[class*="viewerBadge"]',
                        'button[kind="header"]'
                    ];
                    
                    targets.forEach(selector => {
                        const elements = window.parent.document.querySelectorAll(selector);
                        elements.forEach(el => {
                            el.style.display = 'none';
                            el.style.visibility = 'hidden';
                        });
                    });
                    
                    // (3) 현재 문서(iframe 내부)에서도 한번 더 수행
                    targets.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            el.style.display = 'none';
                            el.style.visibility = 'hidden';
                        });
                    });

                } catch (e) {
                    console.log("UI Cleaner Error: " + e);
                }
            }
            
            setInterval(killStreamlitUI, 300);
        </script>
    """, height=0)
    
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
    input_key = f"quiz_in_{st.session_state.current_idx}_{st.session_state.retry_mode}_{st.session_state.get('gave_up_mode', False)}"
    user_input = st.session_state.get(input_key, "").strip()

    if user_input:
        is_correct = user_input.lower() == target.lower()
        
        # [속도 개선] API 호출 제거 -> 메모리 버퍼링 및 로컬 상태 관리
        if is_correct:
            # [NEW] 포기 모드(정답 보고 따라 치기)인 경우 -> 성공 처리하되 로그는 남기지 않음 (이미 실패로 기록됨)
            if st.session_state.get('gave_up_mode', False):
                 st.session_state.quiz_state = "success"
                 st.session_state.last_result = "gave_up" # 결과 화면 메시지용
                 st.session_state.gave_up_mode = False # 모드 해제
                 return

            if st.session_state.is_first_attempt:
                # 1. 학습 로그 버퍼링
                if 'study_log_buffer' not in st.session_state: st.session_state.study_log_buffer = []
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 로그 포맷: [timestamp, date, word_id, username, level, is_correct]
                st.session_state.study_log_buffer.append([
                    timestamp, str(today), int(curr_q['id']), username, int(curr_q['level']), 1
                ])
                
                # 2. 오답 노트 관리 (로컬 메모리) - 정답 시 제거
                if 'pending_wrongs_local' not in st.session_state: st.session_state.pending_wrongs_local = set()
                if curr_q['id'] in st.session_state.pending_wrongs_local:
                    st.session_state.pending_wrongs_local.remove(curr_q['id'])
                
                # 3. 진행 중인 세션 관리 (로컬 메모리)
                if 'pending_session_local' not in st.session_state: st.session_state.pending_session_local = set()
                
                if st.session_state.get("quiz_mode") == "normal":
                    if curr_q['id'] in st.session_state.pending_session_local:
                        st.session_state.pending_session_local.remove(curr_q['id'])

            # [속도 개선] 메모리 상의 progress_df 사용
            if 'user_progress_df' not in st.session_state:
                st.session_state.user_progress_df = utils.load_user_progress(username)
            
            if st.session_state.is_first_attempt and st.session_state.get("quiz_mode") == "normal":
                st.session_state.user_progress_df = utils.update_schedule(curr_q['id'], True, st.session_state.user_progress_df, today)
            
            st.session_state.quiz_state = "success"
            st.session_state.last_result = "correct"
        else:
            # 오답 시 로직 변경: 바로 틀림 처리하지 않고 재시도 기회 부여 (Typos friendly)
            st.session_state.retry_mode = True
            st.session_state.last_wrong_input = user_input # [NEW] 오답 내용 보존

def give_up_callback(username, curr_q, today):
    """모름/포기 버튼 클릭 시 처리"""
    # 1. 학습 로그 (오답=0)
    if 'study_log_buffer' not in st.session_state: st.session_state.study_log_buffer = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.study_log_buffer.append([
        timestamp, str(today), int(curr_q['id']), username, int(curr_q['level']), 0
    ])
    
    # 2. 오답 노트 추가
    if 'pending_wrongs_local' not in st.session_state: st.session_state.pending_wrongs_local = set()
    st.session_state.pending_wrongs_local.add(curr_q['id'])
    
    # 3. 세션 목록에서 제거 (완료됨)
    if 'pending_session_local' not in st.session_state: st.session_state.pending_session_local = set()
    if st.session_state.get("quiz_mode") == "normal":
        if curr_q['id'] in st.session_state.pending_session_local:
            st.session_state.pending_session_local.remove(curr_q['id'])

    # 4. 진도표 업데이트 (Fail)
    if 'user_progress_df' not in st.session_state:
        st.session_state.user_progress_df = utils.load_user_progress(username)
        
    if st.session_state.get("quiz_mode") == "normal":
        st.session_state.user_progress_df = utils.update_schedule(curr_q['id'], False, st.session_state.user_progress_df, today)
        
    # 5. 오답 리스트 추가 (재학습용)
    st.session_state.wrong_answers.append(curr_q)
    st.session_state.is_first_attempt = False
    
    # [CHANGE] 정답 공개 후 '따라 치기' 모드로 전환 (바로 넘어가지 않음)
    st.session_state.gave_up_mode = True
    st.session_state.quiz_state = "answering" # 여전히 입력 상태 유지
    st.session_state.retry_mode = False # 에러 메시지 초기화


def submit_level_test_answer():
    user_input = st.session_state.test_input.strip()
    if not user_input:
        return 
    
    current_q = st.session_state.current_question
    target = current_q['target_word']
    
    if user_input.lower() == target.lower():
        st.session_state.level_test_state = 'success'
        st.session_state.level_test_result = 'correct'
        st.session_state.level_test_retry = False
    else:
        st.session_state.level_test_retry = True
        st.session_state.last_wrong_input = user_input

def pass_level_test_question():
    st.session_state.level_test_state = 'success'
    st.session_state.level_test_result = 'pass'
    st.session_state.level_test_retry = False

def proceed_to_next_level_question():
    """다음 레벨 계산 및 문제 로드 (기존 process_level_test_step 로직 이동)"""
    idx = len(st.session_state.test_history) + 1 
    current_q = st.session_state.current_question
    current_level = st.session_state.current_test_level
    
    # 결과 가져오기 ('correct' or 'pass')
    result_type = st.session_state.level_test_result
    
    # 2. 기록 저장
    # 사용자 입력값: 정답이면 정답 단어, Pass면 "PASS", Retry 중 맞춘 경우도 정답 단어
    final_input = current_q['target_word'] if result_type == 'correct' else "PASS"
    
    st.session_state.test_history.append({
        'q_num': idx,
        'level': current_level,
        'word': current_q['target_word'],
        'user_input': final_input,
        'result': 'correct' if result_type == 'correct' else 'wrong', # 알고리즘용 (Pass는 Wrong 취급)
        'q_id': current_q['id']
    })
    
    # 3. 다음 레벨 계산 (알고리즘)
    is_correct = (result_type == 'correct')
    is_pass = (result_type == 'pass')
    
    step = 0
    if idx <= 7: step = 4
    elif idx <= 22: step = 2
    else: step = 1
    
    next_level = current_level
    
    if is_correct:
        bonus = 0
        if 8 <= idx <= 22:
            if len(st.session_state.test_history) >= 2:
                prev_res = st.session_state.test_history[-2]['result']
                if prev_res == 'correct':
                    bonus = 1 
        
        final_step = step + bonus
        
        if current_level == 15 and idx <= 22:
            can_pass_gate = False
            if len(st.session_state.test_history) >= 2:
                prev_log = st.session_state.test_history[-2]
                if prev_log['level'] == 15 and prev_log['result'] == 'correct':
                    can_pass_gate = True
            
            if can_pass_gate:
                next_level += final_step
            else:
                pass 
        else:
            next_level += final_step
            
    elif is_pass:
        drop = step / 2.0
        next_level -= drop
    else:
        # Retry 하다가 Pass한 경우도 여기 포함됨 (is_pass 로직상)
        # 만약 로직이 복잡해지면 'wrong' 처리를 명확히 해야 함
        next_level -= step
        
    next_level = int(round(next_level))
    next_level = max(1, min(30, next_level))
    
    # 4. 조기 종료 체크
    if idx <= 15 and current_level <= 3 and (not is_correct):
        recent_fails = 0
        for log in st.session_state.test_history[-3:]:
            if log['level'] <= 3 and log['result'] in ['wrong', 'pass']:
                recent_fails += 1
        
        if recent_fails >= 3:
            st.session_state.early_stop = True
            st.session_state.final_level_result = 1
            st.session_state.test_input = ""
            st.session_state.level_test_state = 'answering'
            return

    st.session_state.current_test_level = next_level
    st.session_state.test_input = ""
    st.session_state.level_test_state = 'answering' # 상태 리셋
    st.session_state.level_test_retry = False
    
    if idx >= 30:
        last_8_logs = st.session_state.test_history[-8:]
        avg_lv = sum(log['level'] for log in last_8_logs) / len(last_8_logs)
        st.session_state.final_level_result = int(round(avg_lv))
    else:
        exclude_ids = [h.get('q_id') for h in st.session_state.test_history if 'q_id' in h]
        next_q = utils.get_random_question(next_level, exclude_ids)
        st.session_state.current_question = next_q

def go_next_question():
    st.session_state.current_idx += 1
    st.session_state.quiz_state = "answering" 
    st.session_state.is_first_attempt = True
    st.session_state.retry_mode = False

def handle_session_end(username, progress_df, today):
    df = utils.load_data()
    user_info = utils.get_user_info(username)
    current_level = int(user_info['level']) if user_info and pd.notna(user_info['level']) else 1
    
    # [속도 개선] 세트 종료 시 일괄 저장 (진도표, 학습 로그, 상태 관리)
    with st.spinner("학습 기록을 저장 중입니다..."):
        # 1. 진도표 저장
        if 'user_progress_df' in st.session_state:
            utils.save_progress(username, st.session_state.user_progress_df)
        
        # 2. 학습 로그 일괄 저장
        if 'study_log_buffer' in st.session_state and st.session_state.study_log_buffer:
            utils.batch_log_study_results(st.session_state.study_log_buffer)
            st.session_state.study_log_buffer = [] # 버퍼 비우기
            
        # 3. 상태 관리 (Pending Wrongs & Session) DB 동기화
        updates = {}
        
        # Pending Wrongs
        if 'pending_wrongs_local' in st.session_state:
            new_wrongs_str = ",".join(str(x) for x in st.session_state.pending_wrongs_local)
            updates['pending_wrongs'] = new_wrongs_str
            
        # Pending Session
        if 'pending_session_local' in st.session_state:
            new_session_str = ",".join(str(x) for x in st.session_state.pending_session_local)
            updates['pending_session'] = new_session_str
            
        if updates:
            utils.update_user_dynamic_fields(username, updates)

    # 학습 로그 분석 (구글 시트)
    # [NEW] 방어 구간 & 연패 방지 로직 적용
    
    # 1. 현재 세션의 문제 수 확인
    session_qs_count = len(st.session_state.quiz_list) if 'quiz_list' in st.session_state else 0
    
    # 데이터가 DB에 반영되었으므로 다시 로드 (캐시 무효화됨)
    study_log_df = utils.load_study_log(username)
    
    # 유저 최신 상태 가져오기
    # 캐시 갱신을 위해 force reload가 필요할 수 있으나, batch_log_study_results에서 bump했으므로 get_user_info도 갱신될 것임
    # (users 시트는 수정 안했으니 캐시 유지될 수도 있음 -> qs_count 등 읽어야 하므로...)
    # user_info는 이미 위에서 가져왔지만, 최신 qs_count가 필요함.
    # 하지만 qs_count는 users 시트에만 있고, study_log 저장 시 users 시트는 안 건드림.
    # 따라서 기존 user_info 사용해도 무방 (이전 qs_count)
    
    current_qs_count = user_info.get('qs_count', 0)
    fail_streak = user_info.get('fail_streak', 0)
    level_shield = user_info.get('level_shield', 3)
    
    total_qs_accumulated = current_qs_count + session_qs_count
    
    if total_qs_accumulated >= 50:
        # 평가 진행
        # 최근 50개 로그 가져오기 (현재 레벨)
        if not study_log_df.empty:
            current_level_logs = study_log_df[study_log_df['level'] == current_level]
            if len(current_level_logs) >= 50:
                target_logs = current_level_logs.tail(50)
                correct_count = target_logs['is_correct'].sum()
                total_q = 50 # 고정
                
                new_level, new_streak, new_shield, msg = utils.evaluate_level_update(
                    current_level, correct_count, total_q, fail_streak, level_shield
                )
                
                # 나머지 카운트 (55개 풀었으면 5개 남김)
                remainder_qs = total_qs_accumulated % 50
                
                # DB 업데이트
                updates = {
                    'level': new_level,
                    'fail_streak': new_streak,
                    'level_shield': new_shield,
                    'qs_count': remainder_qs
                }
                utils.update_user_dynamic_fields(username, updates)
                
                # 결과 메시지 출력
                if new_level != current_level:
                    st.balloons()
                    with st.container(border=True):
                        st.markdown(f"<h1 style='text-align: center; color: #FFD700;'>LEVEL UPDATE</h1>", unsafe_allow_html=True)
                        st.markdown(f"<h3 style='text-align: center;'>{msg}</h3>", unsafe_allow_html=True)
                        st.write(f"Level {current_level} ➡ Level {new_level}")
                        if st.button("확인", key="btn_lv_change", use_container_width=True):
                            st.session_state.page = 'dashboard'
                            st.rerun()
                    return # 여기서 중단하고 사용자 반응 대기
                else:
                    # 레벨 유지 시
                    st.info(f"📊 레벨 평가 결과: {msg} (다음 평가까지: {50 - remainder_qs}문제)")
            else:
                # 로그가 부족한 경우 (혹시 모를 예외)
                 utils.update_user_dynamic_fields(username, {'qs_count': total_qs_accumulated})
        else:
             utils.update_user_dynamic_fields(username, {'qs_count': total_qs_accumulated})
             
    else:
        # 평가 기준 미달 -> 카운트만 누적
        utils.update_user_dynamic_fields(username, {'qs_count': total_qs_accumulated})
        st.success(f"📈 레벨 평가 진행 중: {total_qs_accumulated} / 50 문제")

    # 세트 완료 화면
    batch_size = st.session_state.batch_size

    # 세트 완료 화면
    batch_size = st.session_state.batch_size
    
    if st.session_state.wrong_answers:
        st.session_state.quiz_list = st.session_state.wrong_answers
        st.session_state.wrong_answers = []
        st.session_state.current_idx = 0
        st.session_state.retry_mode = False
        st.session_state.quiz_state = "answering"
        st.session_state.quiz_mode = "wrong_review"
        st.rerun()

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.balloons()
        with st.container(border=True):
                st.markdown("<h2 style='text-align: center;'>🎉 세트 완료!</h2>", unsafe_allow_html=True)
                st.markdown("<p style='text-align: center; color: gray;'>수고하셨습니다!</p>", unsafe_allow_html=True)
                
                if st.button(f"🔥 {batch_size}문제 더 도전!", type="primary", use_container_width=True):
                    if 'quiz_list_offset' not in st.session_state: st.session_state.quiz_list_offset = batch_size
                    offset = st.session_state.quiz_list_offset
                    
                    if offset < len(st.session_state.full_quiz_list):
                        next_batch = st.session_state.full_quiz_list[offset : offset + batch_size]
                        st.session_state.quiz_list = next_batch
                        st.session_state.quiz_list_offset += batch_size
                        st.session_state.current_idx = 0
                        st.session_state.retry_mode = False
                        st.session_state.is_first_attempt = True
                        st.session_state.quiz_state = "answering"
                        st.session_state.quiz_mode = "normal"
                        st.rerun()
                    else:
                        # 더 이상 문제가 없으면 초기화
                        keys_to_delete = ['full_quiz_list', 'quiz_list', 'current_idx', 'wrong_answers', 'quiz_list_offset']
                        for k in keys_to_delete:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()

                st.write("")
                if st.button("🏠 대시보드로 돌아가기", use_container_width=True):
                    st.session_state.page = 'dashboard'
                    st.rerun()

def show_login_page():
    # [NEW] 가입 완료 팝업 모드
    if st.session_state.get('signup_success_popup', False):
        with st.container(border=True):
            st.markdown("<br><h2 style='text-align: center;'>✅ 가입 완료되었습니다</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: gray;'>엔터를 누르면 로그인 화면으로 이동합니다.</p>", unsafe_allow_html=True)
            
            if st.button("확인 (Enter)", type="primary", use_container_width=True, key="btn_signup_ok"):
                st.session_state.signup_success_popup = False
                st.session_state.login_menu_choice = "로그인" 
                st.rerun()
            
            utils.focus_element("button")
        return

    # [MOBILE OPTIMIZED] 중앙 정렬 컨테이너 사용
    with st.container(border=True):
        st.markdown("<h1 style='text-align: center;'>🔐 학생 로그인</h1>", unsafe_allow_html=True)
        menu = ["로그인", "회원가입"]
        choice = st.selectbox("메뉴", menu, key="login_menu_choice")
        
        if choice == "로그인":
            if 'signup_success' in st.session_state: del st.session_state['signup_success']
            username = st.text_input("아이디")
            password = st.text_input("비밀번호", type='password')
            
            if st.button("로그인", use_container_width=True):
                user_info = utils.get_user_info(username)
                if user_info:
                    # 비밀번호 검증
                    if utils.check_hashes(password, user_info['password']):
                        st.session_state.logged_in = True
                        st.session_state.username = username
                        st.session_state.page = 'dashboard'
                        st.success(f"환영합니다!")
                        st.rerun()
                    else:
                        st.error("비밀번호가 틀렸습니다.")
                else:
                    st.error("등록되지 않은 학생입니다.")
        
        elif choice == "회원가입":
            st.info("📢 학원생만 가입 가능합니다. 선생님께 인증 코드를 문의하세요.")
            input_code = st.text_input("가입 인증 코드", type="password", placeholder="학원 인증 코드를 입력하세요")
            new_user = st.text_input("아이디 (ID)")
            new_realname = st.text_input("이름 (실명)")
            new_password = st.text_input("비밀번호", type='password')
            new_password_confirm = st.text_input("비밀번호 확인", type='password')
            
            if st.button("가입하기", use_container_width=True):
                # 시스템 설정 로드
                config = utils.get_system_config()
                if input_code != config.get('signup_code', ''):
                    st.error("❌ 가입 인증 코드가 틀렸습니다.")
                elif new_password != new_password_confirm:
                    st.error("❌ 비밀번호가 다릅니다.")
                elif not new_user or not new_password:
                    st.warning("필수 정보를 입력해주세요.")
                else:
                    # 구글 시트에 가입 요청
                    result = utils.register_user(new_user, new_password, new_realname)
                    if result == "SUCCESS":
                        st.session_state.signup_success_popup = True
                        st.rerun()
                    elif result == "EXIST":
                        st.warning("이미 존재하는 아이디입니다.")
                    else:
                        st.error("가입 중 오류가 발생했습니다.")

    with st.sidebar:
        st.divider()
        if st.button("👨‍🏫 선생님 전용"):
            st.session_state.show_admin_login = True
            
    if st.session_state.get('show_admin_login', False):
        with st.sidebar:
            with st.container(border=True):
                st.subheader("관리자 로그인")
                admin_pw = st.text_input("비밀번호", type="password", key="side_admin_pw")
                if st.button("접속", key="btn_side_admin"):
                    config = utils.get_system_config()
                    if admin_pw == config.get('admin_pw', ''):
                        st.session_state.page = 'admin'
                        st.session_state.show_admin_login = False
                        st.rerun()
                    else:
                        st.error("비밀번호 오류")

    # [MOBILE KEYBOARD FIX] 하단 여백 추가 (키보드가 올라왔을 때 스크롤 가능하도록)
    st.markdown("<div style='height: 40vh;'></div>", unsafe_allow_html=True)

def show_admin_page():
    st.title("👨‍🏫 선생님 관리 대시보드 (DB 연동됨)")
    
    if st.button("⬅ 나가기 (로그인 화면)", type="secondary"):
        st.session_state.page = 'login'
        st.rerun()
        
    st.divider()
    
    tab1, tab2, tab3, tab4 = st.tabs(["👥 학생 관리", "🏆 학습 랭킹", "⚖️ 단어 DB 관리", "⚙️ 시스템 설정"])
    
    with tab1:
        st.subheader("학생 명단 및 비밀번호 초기화")
        users = utils.get_all_users()
        if not users.empty:
            st.dataframe(users[['username', 'name', 'level']], use_container_width=True)
            
            st.write("---")
            st.subheader("🛠 학생 정보 수정")
            
            # 학생 선택
            selected_user_id = st.selectbox("수정할 학생 선택", users['username'].tolist())
            
            if selected_user_id:
                # 선택된 학생의 현재 정보 가져오기
                current_info = users[users['username'] == selected_user_id].iloc[0]
                
                with st.form("edit_student_form"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        new_id = st.text_input("아이디 (ID)", value=current_info['username'])
                    with c2:
                        new_name = st.text_input("이름", value=current_info['name'])
                    with c3:
                        new_level = st.number_input("레벨", min_value=1, max_value=30, value=int(current_info['level']) if pd.notna(current_info['level']) and str(current_info['level']).isdigit() else 1)
                        
                    submit_edit = st.form_submit_button("💾 정보 수정 저장")
                    
                    if submit_edit:
                        if not new_id or not new_name:
                            st.warning("아이디와 이름은 필수입니다.")
                        else:
                            res = utils.update_student_info(selected_user_id, new_id, new_name, new_level)
                            if res == "SUCCESS":
                                st.success("✅ 학생 정보가 수정되었습니다.")
                                time.sleep(1)
                                st.rerun()
                            elif res == "DUPLICATE":
                                st.error("❌ 이미 존재하는 아이디입니다.")
                            else:
                                st.error(f"❌ 수정 실패: {res}")

            st.write("---")
            st.subheader("🔐 비밀번호 초기화")
            col_sel, col_btn = st.columns([3, 1])
            with col_sel:
                # 위에서 선택한 학생을 기본값으로 사용
                reset_target = st.text_input("초기화 대상 (자동 입력)", value=selected_user_id, disabled=True)
            with col_btn:
                st.write("")
                if st.button("비밀번호 '1234'로 초기화", type="primary"):
                    success = utils.reset_user_password(selected_user_id, '1234')
                    if success:
                        st.success(f"✅ {selected_user_id} 학생 비밀번호 초기화 완료!")
                    else:
                        st.error("초기화 실패")
        else:
            st.info("가입된 학생이 없습니다.")

    with tab2:
        st.subheader("🏆 학습 활동 랭킹 (Top 5)")
        all_logs = utils.get_all_study_logs()
        
        users = utils.get_all_users()
        total_users = len(users) if not users.empty else 0
            
        if not all_logs.empty:
            ranking = all_logs['username'].value_counts().head(5).reset_index()
            ranking.columns = ['학생 ID', '문제 풀이 수']
            
            if not users.empty:
                name_map = dict(zip(users['username'], users['name']))
                ranking['이름'] = ranking['학생 ID'].map(name_map).fillna(ranking['학생 ID'])
            
            c1, c2 = st.columns(2)
            c1.metric("총 가입 학생", f"{total_users}명")
            c2.metric("학습 기록 보유", f"{all_logs['username'].nunique()}명")

            chart = alt.Chart(ranking).mark_bar().encode(
                x=alt.X('문제 풀이 수', title='총 풀이 횟수'),
                y=alt.Y('이름', sort='-x', title='학생 이름', axis=alt.Axis(titleAngle=0, titlePadding=20)),
                tooltip=['이름', '문제 풀이 수']
            ).properties(title='🏆 학생별 학습 현황')
            st.altair_chart(chart, use_container_width=True)
            
            st.dataframe(ranking[['이름', '문제 풀이 수']], use_container_width=True)
        else:
            st.info("아직 학습 기록이 없습니다.")

    with tab3:
        st.subheader("단어 난이도 자동 조정")
        st.info("학생들의 오답 데이터를 분석하여 단어 레벨(1~30)을 자동 조정합니다.")
        if st.button("🚀 레벨 조정 실행", type="primary"):
            count, msg = utils.adjust_level_based_on_stats()
            st.info(f"결과: {msg}")

    with tab4:
        st.subheader("⚙️ 시스템 보안 설정")
        
        # 설정 로드
        config = utils.get_system_config()
        
        with st.container(border=True):
            st.markdown("#### 🔐 보안 코드 관리")
            st.info("여기서 변경하면 즉시 반영됩니다.")
            
            with st.form("admin_config_form"):
                new_signup_code = st.text_input("학원생 가입 인증 코드", value=config.get('signup_code', ''))
                new_admin_pw = st.text_input("관리자 비밀번호", value=config.get('admin_pw', ''), type='password')
                
                if st.form_submit_button("💾 설정 저장하기", type="primary"):
                    if not new_signup_code or not new_admin_pw:
                        st.warning("값을 입력해주세요.")
                    else:
                        s1 = utils.update_system_config('signup_code', new_signup_code)
                        s2 = utils.update_system_config('admin_pw', new_admin_pw)
                        
                        if s1 and s2:
                            st.success("✅ 설정이 안전하게 저장되었습니다.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ 저장 실패 (네트워크 오류)")

        st.divider()
        st.subheader("🧪 시스템 테스트 설정")
        st.caption("테스트 목적으로만 사용하세요.")
        
        current_state = st.session_state.get('is_tomorrow_mode', False)
        is_tomorrow = st.checkbox("시간 여행 모드 (내일 날짜로 인식)", value=current_state)
        
        if is_tomorrow != current_state:
            st.session_state.is_tomorrow_mode = is_tomorrow
            st.rerun()
            
        if st.session_state.get('is_tomorrow_mode', False):
            fake_today = utils.get_korea_today() + timedelta(days=1)
            st.info(f"🕒 현재 시스템은 **{fake_today}** 날짜로 동작 중입니다.")

def show_level_test_page():
    st.markdown("""
        <style>
            .stTextInput input {
                font-size: 20px !important;
                padding: 10px !important;
            }
            .success-sentence-box {
                background-color: #f0f2f6;
                padding: 15px;
                border-radius: 10px;
                text-align: center;
                font-size: 1.2em !important;
                margin-bottom: 15px;
                color: #31333F;
                font-weight: 500;
                line-height: 1.5;
            }
        </style>
    """, unsafe_allow_html=True)

    # --- 초기화 ---
    if 'test_history' not in st.session_state:
        st.session_state.test_history = []
        st.session_state.current_test_level = 8 
        st.session_state.early_stop = False
        st.session_state.current_question = utils.get_random_question(8, [])
        st.session_state.final_level_result = None
        st.session_state.level_test_state = 'answering' # answering, success
        st.session_state.level_test_retry = False
        st.session_state.level_test_result = None # correct, pass

    # --- 결과 화면 (테스트 완료 시) ---
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
                    del st.session_state.test_history
                    del st.session_state.current_test_level
                    del st.session_state.current_question
                    del st.session_state.final_level_result
                    if 'early_stop' in st.session_state: del st.session_state.early_stop
                    if 'level_test_state' in st.session_state: del st.session_state.level_test_state
                    st.rerun()
                    
                if st.button("🔄 재시험", use_container_width=True):
                    keys = ['test_history', 'current_test_level', 'current_question', 'final_level_result', 'early_stop', 'level_test_state']
                    for k in keys:
                        if k in st.session_state: del st.session_state[k]
                    st.rerun()
        return

    # --- 문제 진행 화면 ---
    q = st.session_state.current_question
    idx = len(st.session_state.test_history) + 1
    cur_lv = st.session_state.current_test_level
    target = q['target_word']
    
    # 진행 단계 표시
    stage_name = ""
    if idx <= 7: stage_name = "1단계: 탐색"
    elif idx <= 22: stage_name = "2단계: 정밀 접근"
    else: stage_name = "3단계: 최종 검증"
    
    # TTS 오디오 가져오기
    audio_data = utils.text_to_speech(q['id'], q['sentence_en'])

    # UI 렌더링 (show_quiz_page 스타일 차용)
    _, col, _ = st.columns([1, 2, 1]) # 모바일 최적화 레이아웃
    with col:
        st.write(f"**Level Test {idx} / 30**")
        st.progress(idx / 30)
        st.caption(f"현재 난이도: {stage_name} (Lv.{cur_lv})")
        
        if st.session_state.level_test_state == 'answering':
            with st.container(border=True):
                st.subheader(f"💡 뜻: {q['meaning']}")
                st.write(f"📖 해석: {q['sentence_ko']}")
                masked = utils.get_masked_sentence(q['sentence_en'], target, q.get('root_word'))
                st.info(f"### {masked}")
            
            if st.session_state.level_test_retry:
                st.warning("❌ 틀렸습니다. 다시 시도해보세요!")
                
            # 입력창
            default_val = st.session_state.get('last_wrong_input', "") if st.session_state.level_test_retry else ""
            st.text_input("정답 입력", value=default_val, key="test_input", on_change=submit_level_test_answer, label_visibility="collapsed", placeholder="정답 입력 후 Enter")
            
            st.write("")
            if st.button("🤷‍♂️ 잘 모르겠어요 (Pass)", type="secondary", use_container_width=True, on_click=pass_level_test_question):
                pass
            
            utils.focus_element("input")

        elif st.session_state.level_test_state == 'success':
            # 결과 화면 (정답 or 포기 후 정답 공개)
            with st.container(border=True):
                if st.session_state.level_test_result == 'pass':
                    st.error(f"❌ 아쉽네요. 정답은 **{target}** 입니다.")
                else:
                    st.success(f"✅ 정답! **{target}**")
                
                highlighted_html = utils.get_highlighted_sentence(q['sentence_en'], target)
                st.markdown(f"""<div class="success-sentence-box">{highlighted_html}</div>""", unsafe_allow_html=True)
                
                if audio_data:
                    st.audio(audio_data, format='audio/mp3', autoplay=True)
            
            if st.button("다음 문제 ➡ (Enter)", type="primary", use_container_width=True, on_click=proceed_to_next_level_question):
                pass
            
            utils.focus_element("button")

def show_dashboard_page():
    username = st.session_state.username
    user_info = utils.get_user_info(username)
    realname = user_info['name'] if user_info else username
    user_level = int(user_info['level']) if user_info and pd.notna(user_info['level']) else 1
    
    progress_df = utils.load_user_progress(username)
    real_today = utils.get_korea_today()

    # [MOBILE OPTIMIZED] 메인 컬럼 제거
    st.markdown(f"<h1 style='text-align: center;'>👋 안녕하세요.<br>{realname} 학생!</h1>", unsafe_allow_html=True)
    st.markdown(f"<h4 style='text-align: center; color: #4e8cff;'>현재 레벨: Lv.{user_level}</h4>", unsafe_allow_html=True)
    st.write("") 

    total_learned = len(progress_df)
    long_term_count = len(progress_df[progress_df['interval'] > 14])
    # 오늘 날짜보다 '작거나 같은'(<=) 리뷰 대상 단어 (오늘 이미 한 것은 제외)
    if 'next_review' in progress_df.columns:
        target_mask = progress_df['next_review'] <= real_today
        if 'last_reviewed' in progress_df.columns:
            not_reviewed_today = progress_df['last_reviewed'] != real_today
            review_count = len(progress_df[target_mask & not_reviewed_today])
        else:
            review_count = len(progress_df[target_mask])
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

    st.divider()
    with st.expander("⚙️ 계정 및 설정 관리"):
        if st.button("🔄 레벨 테스트 다시 보기", use_container_width=True):
            keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
            for k in keys_to_delete:
                if k in st.session_state: del st.session_state[k]
            st.session_state.is_level_testing = True
            st.rerun()
        st.caption("⚠️ 주의: 결과에 따라 새로운 레벨이 부여됩니다.")
        
        st.write("---")
        st.subheader("🔐 비밀번호 변경")
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
        
        st.write("---")
        if st.button("🚪 로그아웃", type="secondary", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.page = 'login'
            if 'signup_success' in st.session_state: del st.session_state['signup_success']
            # 세션 초기화
            for k in list(st.session_state.keys()):
                if k not in ['logged_in', 'page']: del st.session_state[k]
            st.rerun()

def show_quiz_page():
    try:
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

        # [MOBILE OPTIMIZED] 컬럼 제거하고 컨테이너 사용 (CSS로 중앙 정렬됨)
        st.markdown("<h2 style='text-align: center;'>🚀 일등급 영어 단어 챌린지</h2>", unsafe_allow_html=True)
        st.write("")

        if 'full_quiz_list' not in st.session_state:
            with st.spinner("문제 데이터를 불러오는 중입니다..."):
                    # [NEW] 1. 강제 오답 노트 확인 (Forced Review)
                    pending_wrongs_str = user_info.get('pending_wrongs', '')
                    pending_ids = [int(x) for x in pending_wrongs_str.split(',') if x.strip().isdigit()]
                    
                    # [로컬 상태 초기화]
                    st.session_state.pending_wrongs_local = set(pending_ids)
                    
                    # [NEW] 2. 중단된 세션 확인 (Resume Session)
                    pending_session_str = user_info.get('pending_session', '')
                    session_ids = [int(x) for x in pending_session_str.split(',') if x.strip().isdigit()]
                    
                    # [로컬 상태 초기화]
                    st.session_state.pending_session_local = set(session_ids)
                    
                    # [NEW] 유효성 검사: 실제로 DB에 존재하는 문제인지 확인
                    resume_q = []
                    if session_ids:
                        resume_q = df[df['id'].isin(session_ids)].to_dict('records')

                    if pending_ids:
                        # 강제 복습 모드 진입
                        review_q = df[df['id'].isin(pending_ids)].to_dict('records')
                        random.shuffle(review_q)
                        
                        st.session_state.full_quiz_list = review_q
                        st.session_state.quiz_list = review_q 
                        st.session_state.current_idx = 0
                        st.session_state.wrong_answers = []
                        st.session_state.retry_mode = False
                        st.session_state.is_first_attempt = True
                        st.session_state.quiz_state = "answering"
                        st.session_state.quiz_mode = "forced_review"
                        
                        st.warning("⚠️ 지난 학습에서 완료하지 못한 오답이 있습니다. 이를 먼저 해결해야 합니다!")

                    elif session_ids and resume_q:
                         # 세션 이어하기 모드 (문제 목록이 유효할 때만)
                        # 순서는 섞는 게 학습 효과에 좋음 (또는 저장된 순서 유지? DB엔 집합으로 저장됨 -> 섞자)
                        random.shuffle(resume_q)
                        
                        st.session_state.full_quiz_list = resume_q
                        st.session_state.quiz_list = resume_q
                        st.session_state.current_idx = 0
                        st.session_state.wrong_answers = []
                        st.session_state.retry_mode = False
                        st.session_state.is_first_attempt = True
                        st.session_state.quiz_state = "answering"
                        st.session_state.quiz_mode = "normal"
                        st.session_state.batch_size = len(resume_q)
                        
                        st.info(f"🔄 지난 세션을 이어서 진행합니다. ({len(resume_q)}문제 남음)")

                    else:
                        # 3. 새로운 학습 세트 생성 (기존 로직)
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
                            
                            # [FIX] 복습량 폭탄 방지: 한 번에 최대 50개까지만 로드
                            if len(review_ids) > 50:
                                review_ids = review_ids[:50]
                            
                            review_q = df[df['id'].isin(review_ids)].to_dict('records')
                        
                        # 2. 신규 학습 단어
                        learned_ids = progress_df['word_id'].tolist() if 'word_id' in progress_df.columns else []
                        unlearned_df = df[~df['id'].isin(learned_ids)]
                        
                        new_q = []
                        if not unlearned_df.empty:
                            needed_new = batch_size
                            
                            # [FIX] 신규 단어 출제 범위 제한 (현재 레벨 ±1)
                            # 사용자가 Level 5라면 Level 4~6 범위에서만 출제
                            min_lv = max(1, user_level - 1)
                            max_lv = min(30, user_level + 1)
                            
                            # 1차 범위 (±1)
                            candidate_df = unlearned_df[unlearned_df['level'].between(min_lv, max_lv)]
                            
                            # 단어가 부족하면 2차 범위 (±2) 확장
                            if len(candidate_df) < needed_new:
                                min_lv_2 = max(1, user_level - 2)
                                max_lv_2 = min(30, user_level + 2)
                                candidate_df = unlearned_df[unlearned_df['level'].between(min_lv_2, max_lv_2)]
                                
                            # 그래도 부족하면 전체에서 (안전장치)
                            if len(candidate_df) < needed_new:
                                candidate_df = unlearned_df
                            
                            # 우선순위: 현재 레벨(60%) -> 나머지(40%) (범위 내에서)
                            # 이렇게 하면 범위 내에서도 자기 레벨을 더 많이 봄.
                            current_pool = candidate_df[candidate_df['level'] == user_level]
                            other_pool = candidate_df[candidate_df['level'] != user_level]
                            
                            count_current = int(needed_new * 0.6) # 60% 비중
                            
                            samples_current = current_pool.sample(n=min(len(current_pool), count_current)).to_dict('records')
                            
                            # 나머지는 other_pool에서 채우되, current가 부족했다면 other에서 더 채움
                            needed_other = needed_new - len(samples_current)
                            samples_other = other_pool.sample(n=min(len(other_pool), needed_other)).to_dict('records')
                            
                            new_q = samples_current + samples_other
                            
                            # 만약 아직도 부족하면 (other_pool도 부족) -> 다시 전체 unlearned에서 채움 (안전장치)
                            if len(new_q) < needed_new:
                                current_ids = [x['id'] for x in new_q]
                                rest_df = unlearned_df[~unlearned_df['id'].isin(current_ids)]
                                more = needed_new - len(new_q)
                                if not rest_df.empty:
                                    new_q += rest_df.sample(n=min(len(rest_df), more)).to_dict('records')
                        
                        random.shuffle(review_q)
                        random.shuffle(new_q)
                        combined = review_q + new_q
                        
                        # [데이터 안전성] 세션 상태 즉시 저장 -> 로컬 상태 업데이트 + 초기 저장
                        session_ids_to_save = [q['id'] for q in combined]
                        st.session_state.pending_session_local = set(session_ids_to_save)
                        utils.manage_session_state(username, 'set', session_ids_to_save)
                        
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
        
        # [MOBILE LAYOUT FIX] Sticky Header Approach
        st.markdown("""
        <style>
            /* Sticky Header Style */
            .sticky-header {
                position: -webkit-sticky; /* Safari */
                position: sticky;
                top: 0;
                background-color: white;
                z-index: 999;
                padding: 10px 0 15px 0;
                border-bottom: 2px solid #f0f2f6;
            }
            /* Hide Streamlit Header for more space */
            header { visibility: hidden; }
            .block-container { padding-top: 1rem; }
            
            /* Input field styling */
            div[data-testid="stTextInput"] input {
                font-size: 1.1rem;
                padding: 10px;
            }
        </style>
        """, unsafe_allow_html=True)

        progress_pct = (idx / len(st.session_state.quiz_list)) * 100
        
        if st.session_state.quiz_state == "answering":
            # Hint & Error Logic
            hint_html = ""
            if st.session_state.get('gave_up_mode', False):
                 hint_html = f"<div style='color: #d9534f; font-weight: bold; margin-top: 10px;'>❌ 정답: {target}<br><span style='font-size:0.8em; color:gray;'>(위 정답을 똑같이 입력하세요)</span></div>"
                 masked_sentence = utils.get_masked_sentence(curr_q['sentence_en'], target, curr_q.get('root_word')) 
            else:
                 masked_sentence = utils.get_masked_sentence(curr_q['sentence_en'], target, curr_q.get('root_word'))

            error_html = ""
            if st.session_state.retry_mode and not st.session_state.get('gave_up_mode', False):
                error_html = f"<div style='background: #f8d7da; color: #721c24; padding: 8px; border-radius: 5px; margin-top: 10px; font-weight: bold;'>❌ 틀렸습니다. 다시 시도!</div>"

            # Construct HTML (Left-aligned to prevent code block rendering)
            sticky_content = f"""
<div class="sticky-header">
<div style="font-size: 0.85em; color: #666; display: flex; justify-content: space-between; margin-bottom: 5px;">
<span>Question {idx + 1}</span>
<span>{len(st.session_state.quiz_list)}</span>
</div>
<div style="width: 100%; background-color: #e9ecef; height: 6px; border-radius: 3px; margin-bottom: 15px;">
<div style="width: {progress_pct}%; background-color: #ff4b4b; height: 6px; border-radius: 3px;"></div>
</div>
<div style="font-size: 1.2em; font-weight: bold; color: #333; margin-bottom: 5px;">💡 {curr_q['meaning']}</div>
<div style="font-size: 1em; color: #555;">📖 {curr_q['sentence_ko']}</div>
<div style="background: #e8f0fe; color: #1a73e8; padding: 12px; border-radius: 8px; margin-top: 12px; font-weight: 500; font-size: 1.1em; line-height: 1.4;">
{masked_sentence}
</div>
{hint_html}
{error_html}
</div>
"""
            st.markdown(sticky_content, unsafe_allow_html=True)

            # Input Field (Natural Flow)
            input_key = f"quiz_in_{idx}_{st.session_state.retry_mode}_{st.session_state.get('gave_up_mode', False)}"
            default_val = st.session_state.get('last_wrong_input', "") if (st.session_state.retry_mode and not st.session_state.get('gave_up_mode', False)) else ""
            
            placeholder_text = "정답 입력 후 엔터" if not st.session_state.get('gave_up_mode', False) else "위 정답을 똑같이 입력 후 엔터"
            
            st.text_input("정답 입력", value=default_val, key=input_key, label_visibility="collapsed", placeholder=placeholder_text, 
                          on_change=check_answer_callback, args=(username, curr_q, target, today))
            
            # Pass Button (Natural Flow)
            if not st.session_state.get('gave_up_mode', False):
                if st.button("🤷‍♂️ 정답을 모르겠어요 (Pass)", type="secondary", use_container_width=True, 
                             on_click=give_up_callback, args=(username, curr_q, today)):
                    pass
                
            utils.focus_element("input")

        elif st.session_state.quiz_state == "success":
            st.write(f"**Question {idx + 1} / {len(st.session_state.quiz_list)}**")
            st.progress(progress_pct / 100)
            with st.container(border=True):
                # 결과에 따른 메시지 분기
                if st.session_state.get("last_result") == "gave_up":
                    st.error(f"❌ 아쉽네요. 정답은 **{target}** 입니다.")
                else:
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


    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")
        # import traceback
        # st.code(traceback.format_exc()) # 디버깅용 상세 로그
        if st.button("🏠 대시보드로 복구"):
            st.session_state.page = 'dashboard'
            st.rerun()

if __name__ == "__main__":
    main()