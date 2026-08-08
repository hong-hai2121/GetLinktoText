import gc
import os
import re
import subprocess
from collections import Counter

from pydub import AudioSegment

from src import config
from src.notifications import play_sound

# Tham số cho faster-whisper (engine mặc định) — có vad_filter để lọc khoảng lặng.
_FW_OPTS = dict(
    language="vi",
    task="transcribe",
    condition_on_previous_text=False,
    temperature=config.TEMPERATURE_FALLBACK,
    beam_size=5,
    initial_prompt="Đây là nội dung tiếng Việt.",
    no_speech_threshold=0.6,
    compression_ratio_threshold=2.4,
    log_prob_threshold=config.LOG_PROB_THRESHOLD,
    repetition_penalty=config.REPETITION_PENALTY,
    no_repeat_ngram_size=config.NO_REPEAT_NGRAM_SIZE,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
)

# Tham số cho openai-whisper (bỏ vad_filter/vad_parameters — không hỗ trợ; fp16 thêm lúc gọi).
# Engine này không có repetition_penalty/no_repeat_ngram_size, và ngưỡng tên là logprob_threshold.
_OPENAI_OPTS = dict(
    language="vi",
    task="transcribe",
    condition_on_previous_text=False,
    temperature=config.TEMPERATURE_FALLBACK,
    beam_size=5,
    initial_prompt="Đây là nội dung tiếng Việt.",
    no_speech_threshold=0.6,
    compression_ratio_threshold=2.4,
    logprob_threshold=config.LOG_PROB_THRESHOLD,
)

_PUNCT = " \t\r\n.,!?;:…\"'“”‘’()-–—"


def _reload_model_if_needed():
    """Nạp lại model theo engine nếu bị giải phóng (config.model is None)."""
    if config.model is not None:
        return
    if config.TRANSCRIBE_ENGINE == "openai":
        print(f"🔄 Đang tải lại large-v3.pt (openai-whisper): {config.WHISPER_MODEL_FILE}")
        config.model = config.whisper.load_model(
            config.WHISPER_MODEL_FILE, device=config.device
        )
    else:
        print(f"🔄 Đang tải lại large-v3 (CT2) trên {config.device}/{config.compute_type}")
        config.model = config.WhisperModel(
            config.FW_MODEL_DIR, device=config.device, compute_type=config.compute_type
        )
    print("✅ Model đã tải lại thành công.")


def collapse_repetitions(text, max_repeat=None, max_phrase_len=6):
    """Rút gọn chuỗi từ/cụm từ lặp liên tiếp do Whisper kẹt vòng lặp.

    "giả giả giả ... giả" -> "giả giả giả". Lưới an toàn cuối cùng: tham số giải mã đã
    chặn phần lớn vòng lặp, nhưng segment ở nhiệt độ cao nhất vẫn có thể lọt.
    """
    if max_repeat is None:
        max_repeat = config.MAX_WORD_REPEAT
    words = text.split()
    total = len(words)
    if total < 2:
        return text

    # So khớp bỏ qua hoa/thường và dấu câu: "giả" và "giả." là cùng một từ khi xét lặp
    keys = [w.lower().strip(_PUNCT) or w.lower() for w in words]
    out = []
    i = 0
    while i < total:
        best_len, best_reps = 1, 1
        for plen in range(1, max_phrase_len + 1):
            if i + 2 * plen > total:
                break
            unit = keys[i:i + plen]
            reps = 1
            j = i + plen
            while j + plen <= total and keys[j:j + plen] == unit:
                reps += 1
                j += plen
            if reps >= 2 and reps * plen > best_reps * best_len:
                best_len, best_reps = plen, reps
        if best_reps > 1:
            # Từ đơn: giữ tối đa max_repeat lần. Cụm nhiều từ: lặp từ 3 lần trở lên
            # gần như chắc chắn là ảo giác, giữ lại 2 cho an toàn.
            keep = max_repeat if best_len == 1 else 2
            keep = min(best_reps, keep)
            out.extend(words[i:i + best_len * keep])
            i += best_len * best_reps
        else:
            out.append(words[i])
            i += 1

    if len(out) < total:
        print(f"🧹 Đã dọn {total - len(out)} từ lặp do model kẹt vòng lặp.")
    return " ".join(out)


def _segments_to_text(segments) -> str:
    return collapse_repetitions(" ".join(seg.text.strip() for seg in segments))


def extract_audio(video_path, output_wav):
    command = [config.FFMPEG_PATH, "-i", video_path, "-ac", "1", "-ar", "16000", "-y", "-vn", output_wav]
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print(f"✅ Âm thanh đã trích xuất thành công: {output_wav}")
        return output_wav
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi trích xuất âm thanh: {e}")
        play_sound("error")
        return None


def get_audio_duration(audio_path):
    """Lấy thời lượng file audio bằng ffprobe — không load file vào RAM."""
    if config.FFPROBE_PATH:
        try:
            result = subprocess.run(
                [
                    config.FFPROBE_PATH, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return float(result.stdout.strip())
        except Exception as e:
            print(f"❌ Lỗi khi lấy thời lượng file audio: {e}")
            play_sound("error")
            return None
    # Fallback khi ffprobe không có trong PATH
    try:
        return len(AudioSegment.from_file(audio_path)) / 1000
    except Exception as e:
        print(f"❌ Lỗi khi lấy thời lượng file audio: {e}")
        play_sound("error")
        return None


def split_audio(audio_path, chunk_length_ms=180000, max_chunks=None):
    """Chia file audio thành các đoạn nhỏ bằng ffmpeg — không load toàn bộ file vào RAM."""
    try:
        duration = get_audio_duration(audio_path)
        if duration is None:
            return []
        chunk_length_s = chunk_length_ms / 1000
        chunks = []
        start_s = 0.0
        idx = 0
        while start_s < duration:
            if max_chunks is not None and idx >= max_chunks:
                break
            chunk_path = f"{audio_path}_chunk_{idx}.wav"
            command = [
                config.FFMPEG_PATH, "-y",
                "-ss", str(start_s),
                "-t", str(chunk_length_s),
                "-i", audio_path,
                "-ac", "1", "-ar", "16000", "-vn",
                chunk_path,
            ]
            subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            chunks.append(chunk_path)
            start_s += chunk_length_s
            idx += 1
        return chunks
    except Exception as e:
        print(f"❌ Lỗi khi chia nhỏ file âm thanh: {e}")
        play_sound("error")
        return []


def detect_repetition(transcript):
    if not transcript:
        return False

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

    sentences = re.split(r"[\n.!?]", transcript)
    sentences = [s.strip() for s in sentences if s.strip()]

    repeat_threshold = 3
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

    sentence_counts = Counter(sentences)
    repeated_sentences = sum(1 for count in sentence_counts.values() if count > 2)
    if len(sentences) > 0 and (repeated_sentences / len(sentences)) > 0.1:
        print("⚠️ Phát hiện lỗi: Quá nhiều câu bị lặp lại!")
        play_sound("warning")
        return False

    return False


def transcribe_whisper(
    audio_path,
    use_chunks=False,
    max_chunks=None,
    save_chunk_transcripts=False,
    chunk_text_prefix=None,
):
    """Nhận diện giọng nói bằng faster-whisper; hỗ trợ chia nhỏ và giới hạn số đoạn."""

    print("📝 Đang kiểm tra thời lượng file âm thanh...")

    duration = get_audio_duration(audio_path)
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None

    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    if not use_chunks and duration > 900:
        print("ℹ️ File audio dài hơn 15 phút, sẽ chia nhỏ để nhận diện toàn bộ.")
        use_chunks = True
        max_chunks = None

    # Đảm bảo model large-v3 có sẵn (dự án chỉ dùng large-v3, không đổi model khác).
    _reload_model_if_needed()

    is_openai = config.TRANSCRIBE_ENGINE == "openai"
    fp16 = config.device == "cuda"

    def transcribe_one(path):
        if is_openai:
            result = config.model.transcribe(path, fp16=fp16, **_OPENAI_OPTS)
            return collapse_repetitions((result.get("text") or "").strip()).strip()
        segments, _ = config.model.transcribe(path, **_FW_OPTS)
        return _segments_to_text(segments).strip()

    if use_chunks:
        if max_chunks is None:
            max_take = None
        elif max_chunks > 0:
            max_take = max_chunks
        else:
            max_take = config.DEFAULT_MAX_CHUNKS
        chunk_paths = split_audio(audio_path, chunk_length_ms=config.CHUNK_LENGTH_MS, max_chunks=max_take)
        full_text_parts = []
        for idx, chunk_path in enumerate(chunk_paths, start=1):
            print(f"🧩 Đang xử lý đoạn {idx}/{len(chunk_paths)}: {chunk_path}")
            try:
                text_chunk = transcribe_one(chunk_path)
                full_text_parts.append(text_chunk)
                if save_chunk_transcripts and chunk_text_prefix:
                    chunk_txt_path = f"{chunk_text_prefix}_chunk_{idx}.txt"
                    with open(chunk_txt_path, "w", encoding="utf-8") as chunk_file:
                        chunk_file.write(text_chunk)
                    print(f"✅ Đã lưu transcript đoạn {idx}: {chunk_txt_path}")
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
                config.empty_cuda_cache()
        return " ".join(full_text_parts).strip()

    # Không chia nhỏ
    print("📝 Đang nhận diện giọng nói bằng Whisper ...")
    transcript = transcribe_one(audio_path)

    gc.collect()
    config.empty_cuda_cache()

    return transcript


def format_transcript_by_spaces(transcript, spaces_per_line=15):
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
