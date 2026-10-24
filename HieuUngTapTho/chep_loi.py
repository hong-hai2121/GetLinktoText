import os, sys, json
from faster_whisper import WhisperModel
wav, out = sys.argv[1], sys.argv[2]
try:
    m = WhisperModel("large-v3", device="cuda", compute_type="float16")
except Exception as e:
    print("cuda lỗi, dùng cpu:", e); m = WhisperModel("large-v3", device="cpu", compute_type="int8")
segs, info = m.transcribe(wav, language="vi", word_timestamps=True, vad_filter=True, beam_size=5)
res = []
for s in segs:
    res.append({"start": s.start, "end": s.end, "text": s.text.strip(),
                "words": [{"s": w.start, "e": w.end, "w": w.word} for w in s.words]})
    print(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text.strip()}", flush=True)
json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
sys.stdout.flush(); os._exit(0)
