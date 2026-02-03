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

def check_level_test_answer_callback(curr_q):
    idx = st.session_state.test_idx
    input_key = f"test_in_{idx}"
    user_input = st.session_state.get(input_key, "").strip()

    if not user_input:
        return

    target = curr_q['target_word']
    is_correct = user_input.lower() == target.lower()

    if is_correct:
        st.session_state.test_score += 1

    st.session_state.test_results.append({
        "is_correct": is_correct,
        "word": target,
        "correct_answer": target,
        "user_answer": user_input
    })

    # 피드백 저장
    st.session_state.last_test_feedback = {
        "is_correct": is_correct,
        "word": target
    }
    st.session_state.level_test_state = "feedback"

def next_level_test_question():
    st.session_state.test_idx += 1
    st.session_state.level_test_state = "answering"

def go_next_question():
    st.session_state.current_idx += 1
    st.session_state.quiz_state = "answering" 
    st.session_state.is_first_attempt = True
    st.session_state.retry_mode = False

def handle_session_end(username, progress_df, today):
    df = utils.load_data()
    user_info = utils.get_user_info(username)
    current_level = int(user_info['level']) if user_info and pd.notna(user_info['level']) else 1
    
    # [속도 개선] 세트 종료 시 일괄 저장
    with st.spinner("학습 기록을 저장 중입니다..."):
        if 'user_progress_df' in st.session_state:
            utils.save_progress(username, st.session_state.user_progress_df)
        
        if 'study_log_buffer' in st.session_state and st.session_state.study_log_buffer:
            utils.batch_log_study_results(st.session_state.study_log_buffer)
            st.session_state.study_log_buffer = []

    # 학습 로그 분석 (구글 시트)
    study_log_df = utils.load_study_log(username)
    is_eligible_for_review = False
    
    if not study_log_df.empty:
        total_days = study_log_df['date'].nunique()
        total_count = len(study_log_df)
        if total_days >= utils.MIN_TRAIN_DAYS and total_count >= utils.MIN_TRAIN_COUNT:
            is_eligible_for_review = True
            
    # 레벨 다운/업 제안 로직
    if df is not None and is_eligible_for_review:
        # 최근 50문제 정답률 확인
        recent_logs = study_log_df[study_log_df['level'] <= current_level].tail(50)
        if len(recent_logs) >= 20:
            accuracy = recent_logs['is_correct'].mean()
            if accuracy < utils.LEVEL_DOWN_ACCURACY and current_level > 1:
                new_level = current_level - 1
                st.warning("🚧 기초 보강 제안")
                with st.container(border=True):
                    st.markdown(f"<h3 style='text-align: center;'>📉 Level Down 제안</h3>", unsafe_allow_html=True)
                    st.markdown(f"<p style='text-align: center;'>정답률 {accuracy*100:.1f}% 입니다.<br>Level {new_level}로 이동하시겠습니까?</p>", unsafe_allow_html=True)
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ 네, 이동", key="btn_down_yes", use_container_width=True):
                            utils.update_user_level(username, new_level)
                            st.session_state.page = 'dashboard'
                            st.rerun()
                    with c2:
                        if st.button("❌ 아니오", key="btn_down_no", use_container_width=True):
                            pass
                    return

        # 레벨업 조건 확인
        level_words = df[df['level'] == current_level]
        total_words = len(level_words)
        if total_words > 0:
            level_word_ids = level_words['id'].tolist()
            mastered_words = progress_df[
                (progress_df['word_id'].isin(level_word_ids)) & 
                (progress_df['interval'] >= utils.LEVEL_UP_INTERVAL_DAYS)
            ]
            mastered_count = len(mastered_words)
            target_count = min(total_words * utils.LEVEL_UP_RATIO, utils.LEVEL_UP_MIN_COUNT)
            
            if mastered_count >= target_count:
                new_level = current_level + 1
                # 다음 레벨 단어가 있는지 확인
                if not df[df['level'] == new_level].empty:
                    st.balloons()
                    with st.container(border=True):
                        st.markdown(f"<h1 style='text-align: center; color: #FFD700;'>🏆 LEVEL UP! 🏆</h1>", unsafe_allow_html=True)
                        st.markdown(f"<h3 style='text-align: center;'>축하합니다! Level {new_level} 승급!</h3>", unsafe_allow_html=True)
                        if st.button("🎉 계속하기", key="btn_up_yes", use_container_width=True):
                            utils.update_user_level(username, new_level)
                            st.rerun()
                    return

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
    _, col, _ = st.columns([1, 1, 1])
    with col:
        with st.container(border=True):
            st.markdown("<h1 style='text-align: center;'>🔐 학생 로그인</h1>", unsafe_allow_html=True)
            menu = ["로그인", "회원가입"]
            choice = st.selectbox("메뉴", menu)
            
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
                            st.success("✅ 가입완료되었습니다! 로그인 메뉴로 이동하세요.")
                            st.session_state.signup_success = True
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
            col_sel, col_btn = st.columns([3, 1])
            with col_sel:
                reset_user = st.selectbox("비밀번호 초기화할 학생 선택", users['username'].tolist())
            with col_btn:
                st.write("")
                if st.button("비밀번호 '1234'로 초기화", type="primary"):
                    success = utils.reset_user_password(reset_user)
                    if success:
                        st.success(f"✅ {reset_user} 학생 비밀번호 초기화 완료!")
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
                font-size: 24px !important;
                height: 50px !important;
                padding: 10px !important;
            }
        </style>
    """, unsafe_allow_html=True)

    user_info = utils.get_user_info(st.session_state.username)
    # 이미 레벨이 있는 경우(1 이상)
    has_existing_level = user_info and user_info['level'] is not None and user_info['level'] > 0

    with st.sidebar:
        st.title("🎯 레벨 테스트")
        st.caption("1~9단계 문제를 풀어보세요!")
        st.divider()
        
        if has_existing_level:
            if st.button("❌ 테스트 중단 (대시보드로)", use_container_width=True):
                st.session_state.is_level_testing = False
                st.session_state.page = 'dashboard'
                keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
                for k in keys_to_delete:
                    if k in st.session_state: del st.session_state[k]
                st.rerun()
        else:
            st.info("신규 가입자는 레벨 테스트를 완료해야 학습을 시작할 수 있습니다.")

    st.markdown("<h1 style='text-align: center;'>🎯 레벨 테스트 (Lv.1 ~ Lv.9)</h1>", unsafe_allow_html=True)
    
    df = utils.load_data()
    if df is None: 
        st.error("데이터를 불러올 수 없습니다.")
        return

    # --- 문제 출제 로직 (1~9레벨) ---
    if 'test_questions' not in st.session_state or 'level_test_state' not in st.session_state:
        test_set = []
        
        # 1레벨부터 9레벨까지 돌면서 1문제씩 뽑기
        for i in range(1, 10):
            level_data = df[df['level'] == i]
            if not level_data.empty:
                # 각 레벨에서 1문제 추출
                picked = level_data.sample(n=1).to_dict('records')
                test_set.extend(picked)
        
        # 만약 데이터가 너무 없어서(예: DB에 1레벨밖에 없음) 문제가 3개 미만이면 -> 전체에서 랜덤 보충
        if len(test_set) < 3:
            needed = 5 - len(test_set)
            remaining_df = df[~df['id'].isin([q['id'] for q in test_set])] # 이미 뽑은거 제외
            if not remaining_df.empty:
                extra = remaining_df.sample(n=min(len(remaining_df), needed)).to_dict('records')
                test_set.extend(extra)
            
        # 문제 섞기 (난이도 순으로 풀고 싶으면 아래 shuffle을 지우세요)
        # random.shuffle(test_set) 
        
        st.session_state.test_questions = test_set
        st.session_state.test_idx = 0
        st.session_state.test_score = 0
        st.session_state.test_results = []
        st.session_state.level_test_state = "answering" 
        if 'last_test_feedback' in st.session_state: del st.session_state['last_test_feedback']

    questions = st.session_state.test_questions
    
    # 문제가 하나도 안 뽑혔을 때 (DB 텅 빔)
    if not questions:
        st.warning("⚠️ 레벨 테스트를 위한 단어 데이터가 부족합니다. (voca_db를 채워주세요)")
        return

    idx = st.session_state.test_idx

    # --- 테스트 종료 및 결과 처리 ---
    if idx >= len(questions):
        score = st.session_state.test_score
        total_q = len(questions)
        
        # [점수 계산 로직]
        # 예: 9문제 중 1개 맞추면 Lv.1, 9개 다 맞추면 Lv.9
        # (문항 수가 적을 땐 맞춘 개수 = 레벨로 잡는 게 심플합니다)
        if total_q >= 9:
            new_level = max(1, score) # 최소 1레벨
        else:
            # 문제가 적을 땐 비율로 계산
            ratio = score / total_q
            new_level = max(1, int(ratio * 9))
            if new_level == 0: new_level = 1

        user_info = utils.get_user_info(st.session_state.username)
        current_level = user_info['level'] if user_info and user_info['level'] else "없음"
        
        _, col, _ = st.columns([1, 2, 1])
        with col:
            with st.container(border=True):
                st.markdown(f"<h2 style='text-align: center;'>🎉 테스트 완료!</h2>", unsafe_allow_html=True)
                st.metric("총점", f"{score} / {total_q}")
                
                if 'last_test_feedback' in st.session_state and st.session_state.last_test_feedback:
                    fb = st.session_state.last_test_feedback
                    if fb['is_correct']: st.success(f"마지막 문제 정답! ({fb['word']})")
                    else: st.error(f"마지막 문제 오답! 정답은 {fb['word']} 입니다.")

                st.info(f"📋 **진단 결과:** \n추천 레벨: **Level {new_level}**")
                
                st.write("---")
                st.write("**이 결과를 적용하시겠습니까?**")
                
                col_y, col_n = st.columns(2)
                with col_y:
                    if st.button("✅ 시작하기", type="primary", use_container_width=True):
                        utils.update_user_level(st.session_state.username, new_level)
                        st.success(f"레벨 {new_level}로 시작합니다!")
                        time.sleep(1)
                        st.session_state.is_level_testing = False
                        st.session_state.page = 'dashboard'
                        # 초기화
                        keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
                        for k in keys_to_delete:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()
                        
                with col_n:
                    if st.button("🔄 재시험", use_container_width=True):
                        keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
                        for k in keys_to_delete:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()
                        
                st.divider()
                st.markdown("##### 📝 상세 채점표")
                results_data = []
                for i, res in enumerate(st.session_state.test_results):
                    icon = "✅" if res['is_correct'] else "❌"
                    # 레벨 정보가 있으면 표시
                    q_word = res['word']
                    found_row = df[df['target_word'] == q_word]
                    lv_tag = ""
                    if not found_row.empty:
                        lv = found_row.iloc[0]['level']
                        lv_tag = f"(Lv.{lv})"
                        
                    results_data.append({
                        "번호": i + 1, 
                        "결과": icon, 
                        "문제": f"{q_word} {lv_tag}", 
                        "정답": res['correct_answer'], 
                        "내 답": res['user_answer']
                    })
                st.dataframe(pd.DataFrame(results_data), hide_index=True, use_container_width=True)
        return

    # --- 문제 표시 UI ---
    q = questions[idx]
    
    _, col, _ = st.columns([1, 2, 1])
    with col:
        # 진행 바
        st.progress((idx) / len(questions))
        st.caption(f"문제 {idx + 1} / {len(questions)} (Lv.{q['level']})")
        
        # 피드백 표시
        if 'last_test_feedback' in st.session_state and st.session_state.last_test_feedback:
            fb = st.session_state.last_test_feedback
            if fb['is_correct']:
                st.success(f"✅ 정답! ({fb['word']})")
            else:
                st.error(f"❌ 오답! 정답은 **{fb['word']}** 입니다.")

        with st.container(border=True):
            st.subheader(f"💡 뜻: {q['meaning']}")
            st.write(f"📖 해석: {q['sentence_ko']}")
            masked_sentence = utils.get_masked_sentence(q['sentence_en'], q['target_word'], q.get('root_word'))
            st.markdown(f"""
                <div style="
                    background-color: #f0f2f6; 
                    padding: 20px; 
                    border-radius: 10px; 
                    border-left: 5px solid #2196F3;
                    font-size: 26px; 
                    font-weight: bold; 
                    line-height: 1.5;
                    color: #333;
                    margin-bottom: 20px;">
                    {masked_sentence}
                </div>
            """, unsafe_allow_html=True)
        
        if st.session_state.level_test_state == "answering":
            st.text_input(
                "정답 입력", 
                key=f"test_in_{idx}", 
                label_visibility="collapsed", 
                placeholder="정답 입력 후 엔터 (제출)",
                on_change=check_level_test_answer_callback,
                args=(q,)
            )
            utils.focus_element("input")
        elif st.session_state.level_test_state == "feedback":
            if st.button("다음 문제 ➡ (Enter)", type="primary", use_container_width=True, on_click=next_level_test_question):
                pass
            utils.focus_element("button")

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
