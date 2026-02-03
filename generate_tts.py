import os
import pandas as pd
from gtts import gTTS
from tqdm import tqdm
import database as db

# 오디오 파일을 저장할 디렉터리
AUDIO_DIR = "tts_audio"

def generate_tts_files():
    """
    voca_db의 모든 문장에 대한 TTS 오디오 파일을 생성합니다.
    이미 파일이 존재하면 건너뜁니다.
    """
    if not os.path.exists(AUDIO_DIR):
        os.makedirs(AUDIO_DIR)
        print(f"'{AUDIO_DIR}' 디렉터리를 생성했습니다.")

    print("데이터베이스에서 단어 목록을 불러옵니다...")
    vocab_df = db.load_all_vocab()

    if vocab_df.empty:
        print("오디오를 생성할 단어가 없습니다.")
        return

    print(f"총 {len(vocab_df)}개의 단어에 대한 오디오 파일 생성을 시작합니다...")

    # tqdm을 사용하여 진행률 표시
    for _, row in tqdm(vocab_df.iterrows(), total=vocab_df.shape[0], desc="오디오 파일 생성 중"):
        word_id = row['id']
        sentence = row['sentence_en']
        
        # 파일명 형식: {word_id}.mp3
        output_path = os.path.join(AUDIO_DIR, f"{word_id}.mp3")

        # 파일이 이미 존재하면 건너뛰기
        if os.path.exists(output_path):
            continue

        if not sentence or pd.isna(sentence):
            continue

        try:
            # gTTS를 사용하여 오디오 생성
            tts = gTTS(text=sentence, lang='en', slow=False)
            tts.save(output_path)
        except Exception as e:
            print(f"ID {word_id}의 오디오 생성 중 오류 발생: {e}")
            # 오류 발생 시 빈 파일이라도 생성하여 다음 번에 다시 시도하지 않도록 할 수 있음
            # 또는 오류 로그를 남길 수 있음
            pass

    print("오디오 파일 생성이 완료되었습니다.")

if __name__ == "__main__":
    generate_tts_files()
