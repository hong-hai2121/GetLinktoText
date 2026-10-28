# Hiệu ứng video bài tập — yêu cầu và cách làm

Tài liệu này để mang sang máy khác: chép nguyên thư mục `HieuUngTapTho` (có cả file model 30 MB) rồi làm theo phần "Cài trên máy mới".
Nếu dùng Claude ở máy mới, đưa file này cho Claude đọc trước khi gửi video.

---

## 1. Yêu cầu của người dùng (bắt buộc giữ)

1. **Không làm phụ đề lời nói.** Chỉ xuất MỘT bản video không phụ đề. Chữ trên hình chỉ là thẻ bước và nhãn minh họa ngắn, không chép nguyên câu nói. Chỉ làm bản phụ đề karaoke khi được hỏi rõ.
2. **Hiệu ứng phải khớp cái người xem nghe và thấy.** Mốc giờ lấy theo lời hướng dẫn có sẵn trong video. Chuyển động trên hình (cung biên độ, vệt sáng, bong bóng thở) bám theo động tác THẬT đo được từng khung, không vẽ theo kịch bản tưởng tượng.
3. **Không đếm số lần nếu video làm không đủ.** Ví dụ lời nói "10 lần" mà người tập chỉ làm 7 hay 9 lần thì KHÔNG đặt bộ đếm. Chỉ đếm khi video làm đủ số lần như lời nói. Thẻ chữ vẫn được ghi "khoảng 10 lần mỗi bên" vì đó là lời nói.
4. **Kết quả ghi ra thư mục Downloads**, tên `<tên video>_hieu_ung_<YYYYmmdd_HHMMSS>.mp4`. Không sửa video gốc. Không để file tạm trong thư mục dự án.
5. **Video mở đầu / nói chuyện (không có động tác):** chỉ làm hiệu ứng đơn giản. Gồm thẻ trên cùng đổi theo ý chính, nhãn đứng riêng, danh sách tích, thẻ cảnh báo.
6. **Kiểm tra khung hình nguồn trước khi làm.** Có lần video nguồn bị lỗi ghép khung: 4 góc đen, lộ một video khác ở dải trên/dưới. Gặp lỗi như vậy thì báo người dùng trước, không tự sửa. Người dùng sẽ gửi lại bản sạch.
7. Ở bài mèo-bò người dùng chốt: **cúi đầu = HÍT VÀO, ngửa đầu = THỞ RA**. Chiều này ngược với cách dạy thông thường, nhưng làm đúng theo ý người dùng.
8. Có thể được gửi nhiều video liền nhau, nói "làm tương tự các yêu cầu trước". Khi đó áp dụng đủ các quy tắc trên mà không cần hỏi lại.

---

## 2. Các file trong thư mục

| File | Việc |
|---|---|
| `phan_tich.py` | Đo tư thế từng khung (MediaPipe Pose), cả điểm gộp lẫn điểm riêng từng bên `_l` / `_r`, cùng đường lưng và bụng từ mặt nạ người. Ra file `.npz`. |
| `chep_loi.py` | Chép lời kèm mốc giờ từng chữ (faster-whisper large-v3). Ra file `loi.json`. |
| `do_bung.py` | Đo nhịp bụng phồng/xẹp bằng dòng quang học, dùng cho bài thở bụng. |
| `dung_theo_loi.py` | Trình dựng chính. Đọc kịch bản `kich_ban/<tên>.json` rồi vẽ hiệu ứng. Đầu file có danh sách đủ các loại hiệu ứng và tham số. |
| `dung.py` | Trình dựng riêng của bài mèo-bò; `dung_theo_loi.py` cũng dùng chung vài hàm vẽ trong file này. |
| `kich_ban/*.json` | Kịch bản đã làm cho từng video, dùng làm mẫu cho video mới. |
| `pose_landmarker_heavy.task` | Model tư thế (tự tải nếu thiếu). |

---

## 3. Cài trên máy mới (Windows)

Cần **ffmpeg** trên PATH, có encoder NVENC / QSV / AMF thì nhanh hơn. Không có thì tự dùng libx264.
Font Segoe UI có sẵn trên Windows. Font này có đủ dấu tiếng Việt, nhưng KHÔNG có ký tự ✓ ★.

Hai môi trường Python 3.11, đặt cạnh thư mục tool (`..\venv_lamdep` và `..\venv`). Tách hai môi trường vì mediapipe xung đột numpy với các gói khác:

```bash
python -m venv venv_lamdep
```

```bash
venv_lamdep\Scripts\pip install mediapipe opencv-contrib-python numpy pillow
```

```bash
python -m venv venv
```

```bash
venv\Scripts\pip install faster-whisper opencv-python numpy pillow matplotlib
```

Bản đang chạy: mediapipe 1.1.1 / opencv 5.0 (venv_lamdep), faster-whisper 1.2.1 / opencv 4.10 / numpy 1.26.4 (venv).
Model Whisper large-v3 tự tải lần đầu, khoảng 3 GB, chạy bằng CUDA nếu có.

---

## 4. Quy trình cho một video mới

Chạy trong thư mục `HieuUngTapTho`. Thư mục tạm có thể là bất kỳ đâu, ví dụ `D:\tam\v1`.

**B1. Kiểm tra video:** độ phân giải, thời lượng, góc đen, chỗ cắt cảnh, đoạn im lặng.

```bash
ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,width,height,nb_frames -of compact=p=0 "video.mov"
```

**B2. Chép lời để lấy mốc giờ** (không dùng làm phụ đề):

```bash
ffmpeg -y -i "video.mov" -vn -ac 1 -ar 16000 D:\tam\v1\audio.wav
```

```bash
..\venv\Scripts\python.exe -I -X utf8 chep_loi.py D:\tam\v1\audio.wav D:\tam\v1\loi.json
```

Phải có `-X utf8`, không thì lỗi in tiếng Việt. Whisper hay nghe nhầm, cần sửa lại khi viết thẻ chữ: "rũi" là "duỗi", "chán" là "trán", "sơn bánh chè" là "xương bánh chè", "cúi đăng sưng" là "gối đang sưng", "dãn cơ xoa đùi" là "giãn cơ sau đùi", "ngồi dưới chân" là "ngồi duỗi chân".

**B3. Đo tư thế:**

```bash
..\venv_lamdep\Scripts\python.exe -X utf8 phan_tich.py "video.mov" D:\tam\v1\pt.npz
```

Từ file `pt.npz`, xác định chân nào đang tập (`ankle_l` hay `ankle_r`) và mốc từng lần nâng: đỉnh là cực tiểu y của mắt cá. Đếm số lần để quyết định có dùng bộ đếm hay không, theo quy tắc 3.

**B4. Viết kịch bản** `kich_ban/<tên video>.json`. Chép từ kịch bản mẫu gần giống nhất:

| Loại video | Mẫu |
|---|---|
| Ngồi duỗi chân, gập duỗi cổ chân (đồng hồ biên độ) | `1024.json` |
| Ép gối gồng đùi, đếm theo ngón tay | `222.json` |
| Duỗi gối trên gối kê, đổi chân 2 lượt | `1024(4).json` |
| Nằm nghiêng nâng chân dưới, không đếm | `1024(7).json` |
| Nằm nghiêng nâng chân trên, giữ hông thẳng | `1024(8).json` |
| Kéo dây giãn bắp chuối + giãn cơ sau đùi | `1024(6).json` |
| Mở đầu nói chuyện, video dọc | `1024(5).json` |
| Thở bụng 2 hít 1 thở | `4444444444444.json` (chạy kèm `--bung`) |
| Gác chân lên tường, video không tiếng | `333333.json` |
| Tư thế em bé | `2222aaa.json` |

**B5. Xuất khung mẫu để xem bố cục**, sửa kịch bản tới khi không đè chữ, không che mặt:

```bash
..\venv_lamdep\Scripts\python.exe -X utf8 dung_theo_loi.py "video.mov" D:\tam\v1\pt.npz "kich_ban\<tên>.json" --mau 60,300,600,900 --ra D:\tam\v1\mau
```

**B6. Xuất video đầy đủ** ra Downloads. Không truyền `--loi` để không có phụ đề:

```bash
..\venv_lamdep\Scripts\python.exe -X utf8 dung_theo_loi.py "video.mov" D:\tam\v1\pt.npz "kich_ban\<tên>.json"
```

---

## 5. Quy tắc bố cục đã rút ra

- **Video ngang 1440×1080:** thẻ trên cùng thu nhỏ `"the_tren": {"x": 30, "y": 30, "co": 0.75}`. Nếu bàn chân nâng lên góc trái trên thì dời thẻ và bộ đếm sang phải (`x` ≈ 690–715).
- **Video dọc 1080×1920:** thẻ trên cùng ở y=170, nằm trên đầu người nói. Thẻ và nhãn dưới ở y ≈ 1250–1700. `danh_sach` / `the_canh_bao` cần `co` ≈ 1.4 cho chữ đủ to.
- **Hiệu ứng gắn vào chân sắp nâng** (ví dụ "gót trên ngang gối dưới") phải tắt TRƯỚC lần nâng đầu tiên, không thì vệt bị kéo theo chân.
- **Điểm gối nhảy khi duỗi gối trên gối kê:** tâm đo biên độ dùng điểm CỐ ĐỊNH `[x, y]` = trung vị điểm gối của lượt đó.
- **Bài đổi chân:** dùng điểm riêng `ankle_l` / `ankle_r`, không dùng điểm gộp.
- **Cung biên độ cắt ngang chân kia** (nằm nghiêng): dùng `"cung": false` + `"chuoi": ["hip_x", "knee_x"]`.
- **Giữ tư thế lâu hơn thời lượng video** (ví dụ "giữ 15–20 giây" mà video chỉ 10 giây): dùng `dong_ho`, không đếm từng giây.
- **Lời nói có mà video không làm mẫu** (ví dụ đẩy bánh chè): minh họa bằng hiệu ứng `lac` (mũi tên dao động), không giả như đang làm.
- **Đoạn im lặng cuối video** dùng cho thẻ tóm tắt `danh_sach` "Các bước".

---

## 6. Các video đã làm (bộ bài tập đầu gối 8 động tác, Thạc sĩ Đức)

| File nguồn | Nội dung | Ghi chú |
|---|---|---|
| `1024(5).mov` | Mở đầu, video dọc | Hiệu ứng đơn giản |
| `1024.mov` | Động tác 1: gập duỗi cổ chân | Đồng hồ biên độ cổ chân |
| `222.mov` | Động tác 2: ép gối, gồng đùi | Đếm 1–10 theo ngón tay |
| `1024(4).mov` | Động tác 3: duỗi gối, kê gối dưới khoeo | 10 lần mỗi chân, có đếm. Bản `1024(2).mov` lỗi khung, bỏ |
| `dong tac 4.mov` | Động tác 4: nằm nghiêng nâng chân dưới | Bản cũ có đếm 9 lần |
| `1024(7).mov` | Động tác 4, bản quay xa | Không đếm (khoảng 7 lần) |
| `1024(8).mov` | Động tác 5: nằm nghiêng nâng chân trên | Không đếm (9 lần); nhấn mạnh giữ hông thẳng |
| `1024(6).mov` | Động tác 7: giãn bắp chuối bằng dây + xoa bánh chè; Động tác 8: giãn cơ sau đùi | Đếm giữ dây 10 giây |
| (chưa có) | Động tác 6 | Chưa nhận video |

Video khác cùng phiên: `1ddd.mov` (mèo-bò, dùng `dung.py`), `2222aaa.mov` (tư thế em bé), `333333.mov` (gác chân lên tường, không tiếng), `4444444444444.mov` (nằm thư giãn, thở bụng).

**Lưu ý:** bản `dong tac 4.mov` đã xuất trước khi có quy tắc "không đếm khi không đủ số lần", nên vẫn có bộ đếm 9 lần. Muốn bỏ bộ đếm thì xoá mục `"loai": "dem"` trong `kich_ban/dong tac 4.json` rồi xuất lại.
