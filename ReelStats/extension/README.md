# ReelStats — Extension gom link video Facebook

Extension Chrome (Manifest V3) cuộn trang Facebook và gom danh sách video/bài viết,
xuất ra CSV hoặc `reel_links.txt` để chạy tiếp `GetReelStats.py`.

Extension tự nhận **2 chế độ** theo URL và hiện rõ trên popup:

| Chế độ | Trang | Gom được |
|---|---|---|
| **Thước phim / video** | `/search/videos`, `/<page>/reels/`, `/<page>/videos/` | thẻ video: link, tiêu đề, **lượt xem**, thời lượng, ngày, page |
| **Bài viết** | `/search/top/`, `/search/posts/`, trang cá nhân, nhóm, feed | bài viết: link bài, tác giả, thời gian, nội dung, **cảm xúc / bình luận / chia sẻ**, và link video nếu bài có video |

## Cài đặt

1. Mở `chrome://extensions`.
2. Bật **Chế độ dành cho nhà phát triển** (góc trên bên phải).
3. Bấm **Tải tiện ích đã giải nén** → chọn thư mục
   `d:\Python\GetLinktoText\ReelStats\extension`.
4. Ghim icon ReelStats ra thanh công cụ cho tiện.

Sau khi cài, **tải lại (F5)** các tab Facebook đang mở — tab mở từ trước chưa có
content script (popup vẫn tự tiêm được, nhưng F5 chắc ăn hơn).

## Dùng

1. Mở một trong các trang:
   - `facebook.com/<page>/reels/` — chế độ video
   - `facebook.com/<page>/videos/` — chế độ video
   - `facebook.com/search/videos?q=<từ khoá>` — chế độ video
   - `facebook.com/search/top/?q=<từ khoá>` — chế độ bài viết (tab **Tất cả**)
   - `facebook.com/search/posts/?q=<từ khoá>` — chế độ bài viết
2. Bấm icon ReelStats → chỉnh tuỳ chọn nếu cần → **Bắt đầu**.
   Trang sẽ tự cuộn. **Cuộn một lần là gom một lần** — popup hiện luôn danh sách
   vừa gom và ghi xuống `chrome.storage.local` ngay sau mỗi lần cuộn, không đợi
   tới cuối. Có thể đóng popup, việc gom vẫn chạy trong tab (mở lại popup để xem
   tiếp); nút xuất file dùng được ngay giữa chừng.
3. Khi xong, bấm:
   - **Tải CSV** — đủ 13 cột, có BOM nên Excel đọc đúng tiếng Việt.
   - **reel_links.txt** — chỉ link Reel, mỗi dòng 1 link. Lưu vào thư mục
     `ReelStats\` rồi chạy `GetReelStats.py` / `reel_gui.py`.
   - **Chép link** — copy toàn bộ URL vào clipboard.
   - **Tải Trang** — CSV 2 cột `page, page_url`, mỗi trang 1 dòng đã lọc trùng
     (link chuẩn hoá: bỏ `/` thừa, `web.`/`m.`, tham số — giống `gop_csv.py`).

Kết quả lần chạy gần nhất được giữ trong `chrome.storage.local`, mở lại popup
vẫn xuất được mà không cần gom lại. Dòng kết quả ghi rõ **từ khoá** của dữ liệu
đang giữ, để khỏi nhầm với lần chạy trước.

## Chạy từ khoá khác

Bấm **Xóa kết quả** (bấm lần thứ hai để xác nhận) → xoá cả dữ liệu trong
`chrome.storage.local` lẫn bộ nhớ tạm trong tab. Sau đó mở từ khoá mới rồi
**Bắt đầu**.

Không xoá cũng không sao: mỗi lần **Bắt đầu** là gom lại từ đầu, và popup ẩn kết
quả cũ ngay khi chạy để tránh bấm nhầm *Tải CSV* ra dữ liệu từ khoá trước. Xoá
tay chỉ cần khi muốn dọn sạch hẳn.

## Tuỳ chọn

| Mục | Ý nghĩa |
|---|---|
| Chờ mỗi lần cuộn | Thời gian đợi FB nạp thêm, ms. Mạng chậm thì tăng lên 2500–3000. |
| Chỉ lấy Reel | Bỏ qua video `/watch/`, chỉ giữ `/reel/`. |
| Lấy số người theo dõi | Hover lên tên tác giả để FB vẽ thẻ thông tin rồi đọc số. Chậm — xem mục dưới. |

## Số người theo dõi

Facebook không in sẵn số người theo dõi trong feed; nó chỉ vẽ thẻ thông tin
(hover-card) khi chuột rê lên tên tác giả. Extension giả lập đúng chuỗi sự kiện
chuột (`pointerover → mouseover → mouseenter → mousemove`) lên **chính thẻ `<a>`
của Facebook** — không tự tạo link thay được, vì handler gắn vào component React
của họ. Sau đó `MutationObserver` bắt các node mới chèn vào DOM và tìm chuỗi
`N người theo dõi`.

**Chỉ chạy ở chế độ bài viết.** Trang thước phim/video không hover (làm phiên gom
chậm hẳn) — popup khoá luôn ô tuỳ chọn và nút Thử khi đang ở trang đó. Vẫn lấy
đủ `page` / `page_url`, nên số người theo dõi lấy sau bằng công cụ riêng chạy
trên danh sách trang là được.

- Mỗi trang/tác giả chỉ hover **một lần**, kết quả áp cho mọi bài của trang đó.
- Hover ngay trong vòng cuộn, vì feed ảo hoá — cuộn qua là thẻ `<a>` biến mất.
- Mỗi lần hover chờ tối đa 2,5 giây, nghỉ 0,4 giây rồi mới hover tiếp.
- Bấm **Thử lấy người theo dõi** để kiểm tra nhanh trên tên đầu tiên đang hiện,
  trước khi chạy cả phiên dài.

Cảnh báo thật: hover nhiều = bắn nhiều request tới Facebook. Với danh sách vài
trăm trang, nên để nguyên nhịp mặc định, đừng giảm thời gian nghỉ.

Không có giới hạn số video hay số lần cuộn. Extension chỉ dừng khi:

1. Facebook hiện banner hết kết quả (`Đã hết kết quả`, `Bạn đã xem hết`,
   `End of results`…) → trạng thái *"đã hết kết quả"*.
2. Bấm **Dừng** → giữ nguyên phần đã gom.
3. Chốt chặn: 8 vòng liên tiếp mà trang **không dài thêm** và **không có video
   mới** → trạng thái *"Facebook không nạp thêm"* (phòng khi FB không hiện banner).

Cứ thêm 25 video là kết quả được lưu vào `chrome.storage.local` một lần, nên
lỡ đóng tab giữa chừng vẫn còn phần đã gom.

## Cột trong CSV

`kind, id, type, url, video_url, title, page, page_url, followers, duration,
duration_sec, date, views, views_text, reactions, comments, shares, description,
thumb`

- `kind`: `video` (thẻ video) | `post` (bài viết).
- `type`: `reel` | `video` | `watch` | `post`. Trang search trộn cả reel lẫn video
  watch; bài viết có reel đính kèm thì `type` = `reel`.
- `url`: với bài viết là **link bài**, với thẻ video là link video.
  `video_url` chỉ có ở bài viết kèm video.
- `page` / `page_url`: chủ thẻ video, hoặc tác giả bài viết.
- `followers`: chỉ có khi bật tuỳ chọn *Lấy số người theo dõi*; rỗng nghĩa là
  chưa hover được hoặc thẻ thông tin không hiện mục đó.
- `views`: số nguyên đã quy đổi — `"1,7 triệu"` → `1700000`, `"712K"` → `712000`,
  `"12.345"` → `12345`. Bài viết thường không có `views`, bù lại có
  `reactions` / `comments` / `shares`.
- Danh sách sắp xếp giảm dần theo `views`.

## Ghi chú kỹ thuật

- Feed Facebook **ảo hoá**: item cũ bị gỡ khỏi DOM khi cuộn, nên extension gom
  dữ liệu sau *mỗi* lần cuộn thay vì quét một lần ở cuối.
- Ở chế độ video, sau khi duyệt `div[role="article"]` còn **quét vét toàn trang**
  `a[href*="/reel/"]`, `/watch/`, `/videos/`. Lưới thước phim `/<page>/reels/`
  chỉ là các ô link, không có `role="article"` — thiếu bước này thì gom ra 0 mục.
  Video ở lưới không có sẵn tên chủ trang nên `page` / `page_url` suy từ URL trang
  đang mở và tiêu đề tab.
- Lượt xem đọc từ `aria-label` của thẻ tiêu đề và dòng `ngày · N lượt xem`.
  Không đoán theo "span nào có số" — span đó thường là thời lượng (`2:58`).
- Class CSS của Facebook bị làm rối và đổi liên tục; code chỉ bám vào
  `div[role="article"]`, `div[aria-posinset]`, `a[href]`, `aria-label`,
  `[data-ad-rendering-role]` và `span[dir="auto"]` nên bền hơn. Nếu một ngày FB đổi
  cấu trúc, chỗ cần sửa là `parseArticle()` (video) / `parsePost()` (bài viết).
- Ở feed bài viết, FB chống copy bằng cách chèn ký tự vô hình (`U+034F`,
  zero-width) và **span mồi ẩn** vào giữa chữ. Code dùng `innerText` (bỏ span ẩn
  theo CSS) rồi `clean()` lọc nốt ký tự vô hình, nên nội dung lấy ra là chữ thật.
- Link trong feed bài viết dính tham số theo dõi (`__cft__[0]`, `__tn__`…);
  `cleanUrl()` gỡ hết cho gọn. Link `/stories/…` trên avatar **không** bị nhầm là
  link bài viết.

## File

| File | Vai trò |
|---|---|
| `manifest.json` | Khai báo MV3, quyền, content script. |
| `scraper.js` | Content script: cuộn, bóc dữ liệu, lưu `chrome.storage.local`. |
| `popup.html` / `popup.js` | Giao diện: tuỳ chọn, tiến độ, xuất CSV/TXT/clipboard. |
