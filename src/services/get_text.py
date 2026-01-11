import gc
import os
import re
from typing import Callable

from docx import Document
from docx.shared import Pt, RGBColor

from src import browser_client
from src import config
from src import download
from src import transcribe
from src.notifications import play_sound


class GetTextService:
    def __init__(self, logger: Callable[[str], None] | None = None):
        self.logger = logger or (lambda message: print(message))
        self._link_counter = 0

    def log(self, message: str):
        self.logger(message)

    def configure_runtime(
        self,
        model_name: str,
        use_title_mode: bool,
        title_submode: str,
        max_chunks: int,
    ):
        config.USE_TITLE_MODE = use_title_mode
        config.TITLE_MODE_SUBMODE = title_submode
        config.MAX_CHUNKS_RUNTIME = max(1, int(max_chunks))
        config.MODEL_NAME = model_name

    def initialize_whisper(self):
        import torch as _torch
        import whisper as _whisper

        config.torch = _torch
        config.whisper = _whisper
        config.device = "cuda" if config.torch.cuda.is_available() else "cpu"
        self.log(f"✅ Whisper sẽ chạy trên {'GPU' if config.device=='cuda' else 'CPU'}")

    def load_model(self, selected_model: str):
        if config.model is None or selected_model != config.MODEL_NAME:
            self.log(f"🔄 Đang tải model '{selected_model}'...")
            if config.model is not None:
                del config.model
                if config.device == "cuda":
                    config.torch.cuda.empty_cache()
                gc.collect()

            config.MODEL_NAME = selected_model
            config.model = config.whisper.load_model(config.MODEL_NAME, download_root=config.WHISPER_MODEL_PATH).to(
                config.device
            )
            self.log(f"✅ Đã tải model '{config.MODEL_NAME}' thành công")

    def restart_firefox(self):
        return browser_client.restart_firefox()

    def clean_link(self, line: str, fallback_index: int | None = None):
        match = re.match(r"^\s*(\d+)[\.\s]+\s*(https?://\S+)", line)
        if match:
            return int(match.group(1)), match.group(2)

        if fallback_index is not None:
            return fallback_index, line.strip()

        self._link_counter += 1
        return self._link_counter, line.strip()

    def check_title_blacklist(self, title: str):
        if not title or title == "Không thể lấy tiêu đề":
            return False

        title_clean = title.split("#")[0].strip() if "#" in title else title
        title_lower = title_clean.lower()

        for keyword in config.BLACKLIST_KEYWORDS:
            keyword_lower = keyword.lower()
            if keyword_lower in title_lower:
                self.log(
                    f"⚠️ Tiêu đề '{title}' chứa từ khóa cấm '{keyword}' (phần kiểm tra: '{title_clean}'), bỏ qua video."
                )
                return True
        return False

    def save_refined_text(self, refined_text: str | None, video_number: int):
        refined_text_filename = f"refined_text_{video_number}.txt"
        refined_text_path = os.path.join(config.OUTPUT_VIDEO_DIR, refined_text_filename)

        with open(refined_text_path, "w", encoding="utf-8") as f:
            if refined_text is None:
                self.log("⚠ Không có refined_text, bỏ qua xử lý văn bản.")
                refined_text = ""
            formatted_refined_text = refined_text.replace(". ", ".\n")
            f.write(formatted_refined_text)

    def download_video(self, link: str, video_number: int, browser):
        is_local_file = os.path.exists(link) and os.path.isfile(link)
        if is_local_file:
            self.log(f"📁 Phát hiện file local: {link}")
            title = os.path.splitext(os.path.basename(link))[0]
            video_path = link
            audio_filename = f"audio_{video_number}.wav"
            audio_path = os.path.join(config.OUTPUT_VIDEO_DIR, audio_filename)
            return title, video_path, audio_path, is_local_file

        checklinktiktok = 1 if download.is_tiktok_link(link) else 0
        self.log(f"{link} -> TikTok: {checklinktiktok}")

        title = download.get_video_title_facebook(link, browser)
        if config.CHECK_TITLE_BLACKLIST and self.check_title_blacklist(title):
            self.log(f"⛔ Bỏ qua video {video_number} do tiêu đề không phù hợp.")
            return None

        fb_video_url = None
        if checklinktiktok == 0:
            fb_video_url = download.get_facebook_video_url(link)
            if not fb_video_url:
                return None

        video_filename = f"video_{video_number}.mp4"
        video_path = os.path.join(config.OUTPUT_VIDEO_DIR, video_filename)

        if checklinktiktok == 0:
            self.log("\n🎥 ĐANG TẢI VIDEO LINK FACEBOOK")
            if not download.download_video(fb_video_url, video_path):
                return None

        if checklinktiktok == 1:
            self.log("\n🎥 ĐANG TẢI VIDEO LINK TIKTOK")
            if not download.download_videoTIKTOK(link, video_path):
                return None

        audio_filename = f"audio_{video_number}.wav"
        audio_path = os.path.join(config.OUTPUT_VIDEO_DIR, audio_filename)
        return title, video_path, audio_path, is_local_file

    def transcribe_audio(self, video_path: str, audio_path: str, video_number: int):
        if os.path.exists(video_path):
            self.log(f"🎥 Video đã sẵn sàng: {video_path}")
        else:
            self.log(f"❌ Lỗi! Video chưa được sẵn sàng tại {video_path}")
            return None, None

        if not transcribe.extract_audio(video_path, audio_path):
            return None, None

        if os.path.exists(audio_path):
            self.log(f"🎵 Âm thanh đã lưu tại: {audio_path}")
        else:
            self.log(f"❌ Lỗi! Âm thanh chưa được lưu vào {audio_path}")
            return None, None

        transcript = transcribe.transcribe_whisper(
            audio_path, use_chunks=config.USE_TITLE_MODE, max_chunks=config.MAX_CHUNKS_RUNTIME
        )
        transcript_filename = f"transcript_{video_number}.txt"
        transcript_path = os.path.join(config.OUTPUT_VIDEO_DIR, transcript_filename)
        with open(transcript_path, "w", encoding="utf-8") as f:
            if transcript is None:
                self.log("⚠ Không có transcript, bỏ qua xử lý văn bản.")
                transcript = ""
            formatted_transcript = transcribe.format_transcript_by_spaces(transcript, spaces_per_line=25)
            f.write(formatted_transcript)

        self.log(f"💾 Đã lưu transcript vào: {transcript_path}")
        return transcript, transcript_path

    def export_word(
        self,
        doc: Document,
        video_number: int,
        link: str,
        title: str,
        transcript: str | None,
        refined_text: str | None,
        title_suggestion: str | None = None,
    ):
        para = doc.add_paragraph()
        run = para.add_run(f"{video_number}. {link}")
        run.font.color.rgb = RGBColor(255, 0, 0)
        run.font.size = Pt(11)
        doc.add_paragraph(f"Tiêu đề: {title}")
        if title_suggestion:
            doc.add_paragraph(f"Tiêu đề gợi ý: {title_suggestion}")

        if transcript:
            if refined_text:
                doc.add_paragraph(f"Nội dung:\n{refined_text}")
            elif not config.USE_TITLE_MODE or (
                config.USE_TITLE_MODE and config.TITLE_MODE_SUBMODE == "content_only"
            ):
                doc.add_paragraph(f"Nội dung:\n{transcript}")
        else:
            doc.add_paragraph("Nội dung: (Video quá dài để lấy nội dung)")

        doc.add_paragraph("=" * 40)

        try:
            doc.save(config.OUTPUT_WORD_FILE)
            self.log("💾 Đã lưu kết quả thành công!")
        except Exception as e:
            self.log(f"❌ Lỗi khi lưu file Word: {e}")
        finally:
            self.log("✅ Hoàn thành xử lý video, tiếp tục với video tiếp theo!")

    def process_video(self, index: int, link: str, doc: Document, driver, browser):
        video_number, link = self.clean_link(link, index)
        link = link.strip().strip('"').strip("'")
        video_number = video_number if video_number is not None else index
        self.log(f"\n🎥 Đang xử lý video {video_number}: {link}")

        download_result = self.download_video(link, video_number, browser)
        if not download_result:
            return None
        title, video_path, audio_path, is_local_file = download_result

        transcript, transcript_path = self.transcribe_audio(video_path, audio_path, video_number)
        if transcript is None:
            return transcript_path

        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
                self.log(f"🗑️ Đã xóa file âm thanh: {audio_path}")
        except Exception as e:
            self.log(f"⚠️ Không thể xóa audio: {e}")

        if not is_local_file and os.path.exists(video_path):
            try:
                os.remove(video_path)
                self.log(f"🗑️ Đã xóa file video: {video_path}")
            except Exception as e:
                self.log(f"⚠️ Không thể xóa video: {e}")

        gc.collect()
        if config.device == "cuda":
            config.torch.cuda.empty_cache()

        if config.USE_TITLE_MODE:
            self.log("📁 Chế độ chia nhỏ: sẽ xử lý GPT sau khi nhận diện xong tất cả...")
            refined_text = None
            title_suggestion = None
        elif transcript:
            self.log(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
            refined_text = browser_client.send_to_chatgpt(driver, transcript)
            self.save_refined_text(refined_text, video_number)
            title_suggestion = None
        else:
            self.log(f"⚠️ Video {video_number} không có transcript, bỏ qua gửi đến ChatGPT.")
            refined_text = "Dây là video quá dài để lấy nội dung."
            title_suggestion = None

        self.export_word(doc, video_number, link, title, transcript, refined_text, title_suggestion)
        return transcript_path

    def process_videos(self):
        doc = Document()
        doc.save(config.OUTPUT_WORD_FILE)

        driver = browser_client.global_driver

        need_gpt = (not config.USE_TITLE_MODE) or (
            config.USE_TITLE_MODE and config.TITLE_MODE_SUBMODE != "content_only"
        )

        if need_gpt:
            with browser_client.DRIVER_LOCK:
                in_progress = browser_client.FIREFOX_INIT_IN_PROGRESS

            if (driver is None or not browser_client.is_driver_alive(driver)) and in_progress:
                self.log("⏳ Firefox đang khởi động (thread nền). Đang chờ...")
                browser_client.FIREFOX_INIT_EVENT.wait(timeout=90)
                driver = browser_client.global_driver

            if driver is None or not browser_client.is_driver_alive(driver):
                self.log("🌐 Chưa có Firefox/driver. Tự mở Firefox để dùng GPT...")
                driver = browser_client.init_firefox()
                browser_client.global_driver = driver

        with open(config.LINKS_FILE, "r", encoding="utf-8") as file:
            links = [line.strip() for line in file.readlines() if line.strip()]

        for idx, raw_line in enumerate(links, start=1):
            video_number, _ = self.clean_link(raw_line)
            self.log(f"🔄 Đang xử lý video {idx}/{len(links)} (ID={video_number})...")

            if config.USE_TITLE_MODE:
                transcript_file = self.process_video(idx, raw_line, doc, None, None)
            else:
                transcript_file = self.process_video(idx, raw_line, doc, driver, driver)

            if config.USE_TITLE_MODE and transcript_file and os.path.exists(transcript_file):
                with open(transcript_file, "r", encoding="utf-8") as f:
                    current_transcript = f.read().strip()

                if current_transcript:
                    if config.TITLE_MODE_SUBMODE == "content_only":
                        self.log(f"\n📝 Chế độ Nội dung: đã lưu transcript cho video {idx}, bỏ qua gửi GPT.")
                        try:
                            os.remove(transcript_file)
                            self.log(f"🗑️ Đã xóa file transcript: {transcript_file}")
                        except Exception as e:
                            self.log(f"⚠️ Không thể xóa transcript: {e}")
                        continue

                    self.log(f"\n📝 Đang xử lý GPT cho video {idx}...")
                    self.log("🔄 Sử dụng Firefox đã được mở từ khi khởi động...")

                    self.log(f"\n🎯 Yêu cầu 1: Gợi ý 5 tiêu đề cho video {idx}...")
                    title_prompt = (
                        "Dựa trên nội dung video sau, hãy đề xuất 5 tiêu đề hấp dẫn, phù hợp cho kênh Haio6VietSub. "
                        "Mỗi tiêu đề trên một dòng, không ghi số thứ tự:\n\n" + current_transcript
                    )
                    titles_result = browser_client.send_to_chatgpt(driver, title_prompt, mode="raw")
                    if titles_result:
                        para = doc.add_paragraph()
                        para_run = para.add_run(f"🎯 5 Tiêu đề gợi ý cho video {idx}:")
                        para_run.bold = True
                        doc.add_paragraph(titles_result)

                    if config.TITLE_MODE_SUBMODE == "title_only":
                        doc.save(config.OUTPUT_WORD_FILE)
                        try:
                            os.remove(transcript_file)
                            self.log(f"🗑️ Đã xóa file transcript: {transcript_file}")
                        except Exception as e:
                            self.log(f"⚠️ Không thể xóa transcript: {e}")
                        self.log(f"✅ Video {idx}: Chế độ Tiêu đề - đã xong sau Yêu cầu 1.")
                        continue

                    self.log(f"\n📝 Yêu cầu 2: Viết mô tả video {idx} và hashtag...")
                    desc_prompt = (
                        "Viết mô tả video (1-2 đoạn ngắn gọn) và thêm 5-10 hashtag phù hợp cho kênh Haio6VietSub, "
                        "dựa trên nội dung:\n\n" + current_transcript
                    )
                    desc_result = browser_client.send_to_chatgpt(driver, desc_prompt, mode="raw")
                    if desc_result:
                        para = doc.add_paragraph()
                        para_run = para.add_run(f"📝 Mô tả + Hashtag cho video {idx}:")
                        para_run.bold = True
                        doc.add_paragraph(desc_result)

                    self.log(f"\n🏷️ Yêu cầu 3: Viết thẻ tag cho video {idx} (tối đa 500 kí tự)...")
                    tag_prompt = (
                        "Viết một danh sách các thẻ tag mô tả video này, tối đa 500 kí tự, phù hợp cho kênh Haio6VietSub, "
                        "ngăn cách bằng dấu phẩy. Dựa trên nội dung:\n\n" + current_transcript
                    )
                    tag_result = browser_client.send_to_chatgpt(driver, tag_prompt, mode="raw")
                    if tag_result:
                        para = doc.add_paragraph()
                        para_run = para.add_run(f"🏷️ Tags cho video {idx}:")
                        para_run.bold = True
                        doc.add_paragraph(tag_result)

                    doc.save(config.OUTPUT_WORD_FILE)

                    try:
                        os.remove(transcript_file)
                        self.log(f"🗑️ Đã xóa file transcript: {transcript_file}")
                    except Exception as e:
                        self.log(f"⚠️ Không thể xóa transcript: {e}")

                    self.log(f"✅ Đã lưu kết quả video {idx} vào {config.OUTPUT_WORD_FILE}")

                    gc.collect()
                    if config.device == "cuda":
                        config.torch.cuda.empty_cache()

        self.log("\n🧹 Giải phóng bộ nhớ...")

        if config.model is not None:
            del config.model
            config.model = None

        if config.model2 is not None:
            del config.model2
            config.model2 = None

        if config.device == "cuda":
            config.torch.cuda.empty_cache()
        gc.collect()

        self.log("✅ Bộ nhớ đã được giải phóng.")
        self.log("🎉 Hoàn thành tất cả video! Kết quả đã lưu vào final_result.docx")
        play_sound("success")
