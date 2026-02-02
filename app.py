import streamlit as st
import pandas as pd
import os
import random
from datetime import timedelta
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
             utils.log_study_result(username, curr_q['id'], curr_q['level'], is_correct)

        if is_correct:
            progress_df = utils.load_user_progress(username) 
            if st.session_state.is_first_attempt and st.session_state.get("quiz_mode") == "normal":
                progress_df = utils.update_schedule(curr_q['id'], True, progress_df, today)
                utils.save_progress(username, progress_df)
            st.session_state.quiz_state = "success"
        else:
            if st.session_state.is_first_attempt:
                progress_df = utils.load_user_progress(username)
                if st.session_state.get("quiz_mode") == "normal":
                    progress_df = utils.update_schedule(curr_q['id'], False, progress_df, today)
                    utils.save_progress(username, progress_df)
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
    _, col, _ = st.columns([1, 2, 1])
    with col:
        if st.session_state.wrong_answers:
            st.warning(f"오답 {len(st.session_state.wrong_answers)}개를 재학습합니다.")
            if st.button("오답 노트 시작", use_container_width=True):
                st.session_state.quiz_list = st.session_state.wrong_answers
                st.session_state.wrong_answers = []
                st.session_state.current_idx = 0
                st.session_state.retry_mode = False
                st.session_state.quiz_state = "answering"
                st.session_state.quiz_mode = "wrong_review"
                st.rerun()
        else:
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
                    # 구글 시트에서 전체 유저 목록 가져와서 확인
                    users = utils.read_sheet_to_df('users')
                    if users.empty:
                        st.error("등록된 학생이 없습니다.")
                    else:
                        hashed_psw = utils.make_hashes(password)
                        if username in users['username'].values:
                            user_row = users[users['username'] == username].iloc[0]
                            # 비밀번호 검증
                            if hashed_psw == str(user_row['password']):
                                st.session_state.logged_in = True
                                st.session_state.username = username
                                st.session_state.page = 'dashboard'
                                st.success(f"환영합니다!")
                                st.rerun()
                            else: st.error("비밀번호가 틀렸습니다.")
                        else: st.error("등록되지 않은 학생입니다.")
            
            elif choice == "회원가입":
                st.info("📢 학원생만 가입 가능합니다. 선생님께 인증 코드를 문의하세요.")
                input_code = st.text_input("가입 인증 코드", type="password", placeholder="학원 인증 코드를 입력하세요")
                new_user = st.text_input("아이디 (ID)")
                new_realname = st.text_input("이름 (실명)")
                new_password = st.text_input("비밀번호", type='password')
                new_password_confirm = st.text_input("비밀번호 확인", type='password')
                
                if st.button("가입하기", use_container_width=True):
                    if input_code != utils.SIGNUP_SECRET_CODE:
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
                    if admin_pw == utils.ADMIN_PASSWORD:
                        st.session_state.page = 'admin'
                        st.session_state.show_admin_login = False
                        st.rerun()
                    else:
                        st.error("비밀번호 오류")

def show_admin_page():
    st.title("👨‍🏫 선생님 관리 대시보드 (Google Sheets 연동됨)")
    
    if st.button("⬅ 나가기 (로그인 화면)", type="secondary"):
        st.session_state.page = 'login'
        st.rerun()
        
    st.divider()
    
    tab1, tab2, tab3, tab4 = st.tabs(["👥 학생 관리", "🏆 학습 랭킹", "⚖️ 단어 DB 관리", "⚙️ 시스템 설정"])
    
    with tab1:
        st.subheader("학생 명단 및 비밀번호 초기화")
        # 구글 시트에서 유저 목록 로드
        users = utils.read_sheet_to_df('users')
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
                        st.error("초기화 실패 (구글 시트 오류)")
        else:
            st.info("가입된 학생이 없습니다.")

    with tab2:
        st.subheader("🏆 학습 활동 랭킹 (Top 5)")
        # 구글 시트에서 학습 로그 로드
        all_logs = utils.read_sheet_to_df('study_log')
        
        total_users = 0
        users = utils.read_sheet_to_df('users')
        if not users.empty:
            total_users = len(users)
            
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
        st.subheader("⚙️ 시스템 테스트 설정")
        st.warning("⚠️ 이 설정은 테스트 목적으로만 사용하세요.")
        
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
    has_existing_level = user_info and pd.notna(user_info['level']) and str(user_info['level']) != '' and int(user_info['level']) > 0

    with st.sidebar:
        st.title("🎯 테스트 중")
        st.caption("집중해서 풀어보세요!")
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

    st.markdown("<h1 style='text-align: center;'>🎯 레벨 테스트</h1>", unsafe_allow_html=True)
    
    df = utils.load_data()
    if df is None: 
        st.error("데이터를 불러올 수 없습니다.")
        return

    if 'test_questions' not in st.session_state or 'level_test_state' not in st.session_state:
        # 레벨별 샘플링 (데이터가 부족할 수 있으므로 min 처리)
        q1 = df[df['level'] == 1].sample(n=min(3, len(df[df['level']==1]))).to_dict('records')
        q2 = df[df['level'] == 2].sample(n=min(4, len(df[df['level']==2]))).to_dict('records')
        q3 = df[df['level'] == 3].sample(n=min(3, len(df[df['level']==3]))).to_dict('records')
        
        # 만약 레벨 1,2,3 데이터가 너무 적으면 전체에서 랜덤 추출
        if len(q1) + len(q2) + len(q3) < 5:
            test_set = df.sample(n=min(10, len(df))).to_dict('records')
        else:
            test_set = q1 + q2 + q3
            
        random.shuffle(test_set)
        
        st.session_state.test_questions = test_set
        st.session_state.test_idx = 0
        st.session_state.test_score = 0
        st.session_state.test_results = []
        st.session_state.level_test_state = "answering" 
        if 'last_test_feedback' in st.session_state: del st.session_state['last_test_feedback']

    questions = st.session_state.test_questions
    idx = st.session_state.test_idx

    # 테스트 종료 처리
    if idx >= len(questions):
        score = st.session_state.test_score
        # 점수에 따른 레벨 배정 로직 (간단 버전)
        new_level = 1
        total_q = len(questions)
        if total_q > 0:
            ratio = score / total_q
            if ratio >= 0.8: new_level = 3
            elif ratio >= 0.5: new_level = 2
        
        user_info = utils.get_user_info(st.session_state.username)
        current_level = user_info['level'] if user_info and pd.notna(user_info['level']) else "없음"
        
        _, col, _ = st.columns([1, 2, 1])
        with col:
            with st.container(border=True):
                st.markdown(f"<h2 style='text-align: center;'>🎉 테스트 완료!</h2>", unsafe_allow_html=True)
                st.metric("총점", f"{score} / {len(questions)}")
                
                if 'last_test_feedback' in st.session_state and st.session_state.last_test_feedback:
                    fb = st.session_state.last_test_feedback
                    if fb['is_correct']: st.success(f"마지막 문제 정답! ({fb['word']})")
                    else: st.error(f"마지막 문제 오답! 정답은 {fb['word']} 입니다.")

                st.info(f"📋 **진단 결과:** \n기존 레벨: **{current_level}** \n추천 레벨: **Level {new_level}**")
                
                st.write("---")
                st.write("**이 결과를 적용하시겠습니까?**")
                
                col_y, col_n = st.columns(2)
                with col_y:
                    if st.button("✅ 예 (변경함)", type="primary", use_container_width=True):
                        utils.update_user_level(st.session_state.username, new_level)
                        st.success(f"레벨이 {new_level}로 변경되었습니다!")
                        time.sleep(1)
                        st.session_state.is_level_testing = False
                        st.session_state.page = 'dashboard'
                        # 초기화
                        keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
                        for k in keys_to_delete:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()
                        
                with col_n:
                    if st.button("❌ 아니오 (유지함)", use_container_width=True):
                        st.info("기존 레벨을 유지합니다.")
                        time.sleep(1)
                        st.session_state.is_level_testing = False
                        st.session_state.page = 'dashboard'
                        keys_to_delete = ['test_questions', 'test_idx', 'test_score', 'test_results', 'last_test_feedback', 'level_test_state']
                        for k in keys_to_delete:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()
                        
                st.divider()
                st.markdown("##### 📝 상세 채점표")
                results_data = []
                for i, res in enumerate(st.session_state.test_results):
                    icon = "✅" if res['is_correct'] else "❌"
                    results_data.append({"번호": i + 1, "결과": icon, "문제": res['word'], "정답": res['correct_answer'], "내 답": res['user_answer']})
                st.dataframe(pd.DataFrame(results_data), hide_index=True, use_container_width=True)
        return

    q = questions[idx]
    
    _, col, _ = st.columns([1, 2, 1])
    with col:
        if 'last_test_feedback' in st.session_state and st.session_state.last_test_feedback:
            fb = st.session_state.last_test_feedback
            label = "방금 문제" if st.session_state.get("level_test_state") == "feedback" else "이전 문제"
            if fb['is_correct']:
                st.success(f"✅ {label} 정답! ({fb['word']})")
            else:
                st.error(f"❌ {label} 오답! 정답은 **{fb['word']}** 입니다.")

        st.progress((idx + 1) / len(questions))
        st.write(f"**문제 {idx + 1} / {len(questions)}**")
        
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
            batch_option = st.slider("한 번에 학습할 문제 수", 1, 30, st.session_state.batch_size, 1)
            st.write("")
            if st.button("🚀 학습 시작하기", type="primary", use_container_width=True):
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
    
    progress_df = utils.load_user_progress(username)
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
        
        # TTS 생성
        tts_key = f"tts_{curr_q['id']}"
        if tts_key not in st.session_state:
            st.session_state[tts_key] = utils.text_to_speech(curr_q['sentence_en'])

        st.write(f"**Question {idx + 1} / {len(st.session_state.quiz_list)}**")
        st.progress((idx) / len(st.session_state.quiz_list))

        if st.session_state.quiz_state == "answering":
            with st.container(border=True):
                if st.session_state.get("quiz_mode") == "wrong_review":
                    st.warning("🔥 오답 재학습 중")
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
                
                if tts_key in st.session_state and st.session_state[tts_key]:
                    st.audio(st.session_state[tts_key], format='audio/mp3', autoplay=True)

            if st.button("다음 문제 ➡ (Enter)", type="primary", key=f"next_btn_{idx}", use_container_width=True, on_click=go_next_question):
                pass
            utils.focus_element("button")

if __name__ == "__main__":
    main()
