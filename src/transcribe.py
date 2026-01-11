import gc
import os
import re
import subprocess
from collections import Counter

from pydub import AudioSegment

from src import config
from src.notifications import play_sound


def extract_audio(video_path, output_wav):
    """Trích xuất âm thanh từ video"""
    command = [config.FFMPEG_PATH, "-i", video_path, "-ac", "1", "-ar", "16000", "-y", output_wav, "-vn"]
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print(f"✅ Âm thanh đã trích xuất thành công: {output_wav}")
        return output_wav
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi trích xuất âm thanh: {e}")
        play_sound("error")
        return None


def extract_audioTIKTOK(video_path, audio_path):
    """Trích xuất âm thanh từ video"""
    command = [config.FFMPEG_PATH, "-i", video_path, "-ac", "1", "-ar", "16000", "-y", audio_path, "-vn"]
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print(f"✅ Âm thanh đã trích xuất thành công: {audio_path}")
        return audio_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi trích xuất âm thanh: {e}")
        play_sound("error")
        return None


def split_audio(audio_path, chunk_length_ms=180000, max_chunks=None):
    """Chia file audio thành các đoạn nhỏ; giới hạn số đoạn nếu max_chunks được đặt."""
    try:
        audio = AudioSegment.from_file(audio_path)
        chunks = []
        for idx, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
            if max_chunks is not None and idx >= max_chunks:
                break
            end_ms = start_ms + chunk_length_ms
            chunk = audio[start_ms:end_ms]
            chunk_path = f"{audio_path}_chunk_{idx}.wav"
            chunk.export(chunk_path, format="wav")
            chunks.append(chunk_path)
        return chunks
    except Exception as e:
        print(f"❌ Lỗi khi chia nhỏ file âm thanh: {e}")
        play_sound("error")
        return []


def get_audio_duration(audio_path):
    """Lấy thời lượng của file audio (đơn vị giây)."""
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000
    except Exception as e:
        print(f"❌ Lỗi khi lấy thời lượng file audio: {e}")
        play_sound("error")
        return None


def detect_repetition(transcript):
    if not transcript:
        return False

    # ✅ Điều kiện đặc biệt: chứa từ khoá quảng bá spam
    spam_keywords = [
        "Hãy subscribe cho kênh Ghiền Mì Gõ để",
        "hãy subscribe cho kênh ghiền mì gõ để",
        "kênh Ghiền Mì Gõ",
    ]

    for spam in spam_keywords:
        if spam.lower() in transcript.lower():
            print(f"⚠️ Phát hiện nội dung spam hoặc lặp dạng quảng bá: '{spam}'")
            play_sound("warning")
            return True

    words = transcript.split()
    sentences = re.split(r"[\n.!?]", transcript)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 🔹 Phát hiện câu lặp liên tiếp
    repeat_threshold = 3  # Nếu một câu giống nhau lặp liên tiếp 3 lần → lỗi
    repeat_count = 1
    last_sentence = None

    for sentence in sentences:
        if sentence == last_sentence:
            repeat_count += 1
        else:
            repeat_count = 1
        last_sentence = sentence

        if repeat_count >= repeat_threshold:
            print(f"⚠️ Phát hiện câu lặp liên tiếp {repeat_count} lần: {sentence}")
            play_sound("warning")
            return False

    # 🔹 Giữ lại kiểm tra tổng thể
    sentence_counts = Counter(sentences)
    repeated_sentences = sum(1 for count in sentence_counts.values() if count > 2)
    if len(sentences) > 0 and (repeated_sentences / len(sentences)) > 0.1:
        print("⚠️ Phát hiện lỗi: Quá nhiều câu bị lặp lại!")
        play_sound("warning")
        return False

    return False


def transcribe_whisper(audio_path, use_chunks=False, max_chunks=None):
    """Nhận diện giọng nói bằng Whisper; hỗ trợ chia nhỏ và chỉ lấy max_chunks đoạn đầu."""

    print("📝 Đang kiểm tra thời lượng file âm thanh...")

    duration = get_audio_duration(audio_path)
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None

    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    if not use_chunks and duration > 900:
        print("❌ File audio dài hơn 15 phút, không thể nhận diện.")
        return None

    # Xóa model2 khi quay lại medium (an toàn hơn: set None + giải phóng VRAM)
    if config.model2 is not None:
        print("🗑️ Đang xóa model large-v3 khỏi bộ nhớ GPU để quay lại medium...")
        try:
            config.model2 = None
        except Exception as e:
            print(f"⚠️ Không thể xóa model2: {e}")
        try:
            if config.device == "cuda":
                config.torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
        print("✅ Model large-v3 đã được xóa.")

    # Đảm bảo model medium có sẵn
    if config.model is None:
        print("🔄 Đang tải lại model medium...")
        config.model = config.whisper.load_model(config.MODEL_NAME, download_root=config.WHISPER_MODEL_PATH).to(
            config.device
        )
        print("✅ Model medium đã tải thành công.")

    def transcribe_one(path):
        result_local = config.model.transcribe(path, language="vi")
        text_local = result_local["text"]
        if detect_repetition(text_local):
            print("🔄 Phát hiện lỗi lặp từ, chuyển sang model 'large-v3'...")
            model_name2 = "large-v3"
            if config.model2 is None:
                print("⏳ Đang tải model large-v3 (lần đầu tiên sẽ mất 5-10 phút, vui lòng chờ...)...")
                print("🗑️ Giải phóng model medium để tiết kiệm VRAM...")
                del config.model
                config.model = None
                config.model2 = None

                config.torch.cuda.empty_cache()
                gc.collect()
                try:
                    config.model2 = config.whisper.load_model(model_name2, download_root=config.WHISPER_MODEL_PATH).to(
                        config.device
                    )
                    print("✅ Model large-v3 đã tải thành công!")
                except Exception as e:
                    print(f"❌ Lỗi khi tải model large-v3: {e}")
                    print("⚠️ Quay lại model medium...")
                    config.model = config.whisper.load_model(
                        config.MODEL_NAME, download_root=config.WHISPER_MODEL_PATH
                    ).to(config.device)
                    return text_local.strip()
            print("🔄 Đang nhận diện lại với model large-v3...")
            text_local = config.model2.transcribe(path, language="vi")["text"]
            config.torch.cuda.empty_cache()
            gc.collect()
        return text_local.strip()

    if use_chunks:
        max_take = max_chunks if (max_chunks and max_chunks > 0) else config.DEFAULT_MAX_CHUNKS
        chunk_paths = split_audio(audio_path, chunk_length_ms=config.CHUNK_LENGTH_MS, max_chunks=max_take)
        full_text_parts = []
        for idx, chunk_path in enumerate(chunk_paths, start=1):
            print(f"🧩 Đang xử lý đoạn {idx}/{len(chunk_paths)}: {chunk_path}")
            try:
                text_chunk = transcribe_one(chunk_path)
                full_text_parts.append(text_chunk)
            except Exception as e:
                print(f"❌ Lỗi khi xử lý đoạn {idx}: {e}")
            finally:
                try:
                    if os.path.exists(chunk_path):
                        os.remove(chunk_path)
                        print(f"🗑️ Đã xóa chunk: {chunk_path}")
                except Exception as e:
                    print(f"⚠️ Không thể xóa {chunk_path}: {e}")
                gc.collect()
                if config.device == "cuda":
                    config.torch.cuda.empty_cache()
        return " ".join(full_text_parts).strip()

    # Không chia nhỏ
    print("📝 Đang nhận diện giọng nói bằng Whisper ...")
    transcript = transcribe_one(audio_path)

    gc.collect()
    if config.device == "cuda":
        config.torch.cuda.empty_cache()

    return transcript


def format_transcript_by_spaces(transcript, spaces_per_line=15):
    """Định dạng transcript để xuống dòng sau mỗi 15 dấu cách."""
    space_count = 0
    formatted_text = ""

    for char in transcript:
        formatted_text += char
        if char == " ":
            space_count += 1
        if space_count == spaces_per_line:
            formatted_text += "\n"
            space_count = 0

    return formatted_text
