import yt_dlp
import re
from docx import Document

def get_facebook_titles_from_list(url_list):
    """
    Trả về danh sách (link, tiêu đề) theo thứ tự.
    """
    results = []

    for url in url_list:
        print(f"🔍 Đang xử lý: {url}")
        try:
            with yt_dlp.YoutubeDL() as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', '').strip()
                description = info.get('description', '').strip()
                print(f"📄 Đã lưu file Word: {title}")
                print(f"📄 Đã lưu file Word: {description}")
                
                # Nếu tiêu đề bị cắt ngắn (có dấu ba chấm), lấy mô tả
                if title.endswith('...') and description:
                    title = description.split('\n')[0].strip()
                    if len(title) > 150:
                        title = title[:150] + '...'

                # Làm sạch tiêu đề
                title_cleaned = re.sub(r'^.*?views', '', title, flags=re.IGNORECASE)
                title_cleaned = re.sub(r'^.*?reactions?', '', title_cleaned, flags=re.IGNORECASE)
                title_cleaned = re.sub(r'[\\/*?:"<>|]', '', title_cleaned).strip()

                print(f"✅ Tiêu đề đã làm sạch: {title_cleaned}")
                results.append((url, title_cleaned))
        except Exception as e:
            print(f"❌ Lỗi khi lấy tiêu đề từ {url}: {e}")
            results.append((url, "Không thể lấy tiêu đề"))

    return results

def save_to_word_ordered(results, filename="Facebook_Video_Titles.docx"):
    doc = Document()
    doc.add_heading("Tiêu đề video Facebook", 0)

    for url, title in results:
        doc.add_paragraph(url)
        doc.add_paragraph(title)
        doc.add_paragraph("")  # Dòng trống giữa các cặp

    doc.save(filename)
    print(f"📄 Đã lưu file Word: {filename}")

# Ví dụ sử dụng
if __name__ == "__main__":
    url_list = [
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7501013961236696327?is_from_webapp=1&sender_device=pc",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7497314190848281863?is_from_webapp=1&sender_device=pc",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7496942803688197393?is_from_webapp=1&sender_device=pc",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7496567095505767688",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7496103398920490260",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7495814074551323912",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7495422475589782792",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7494913376628395271",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7494595831840935186",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7494150432453889288",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7493901431821307143",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7493460378710527239",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7493092201677737223",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7492482931382914322",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7492095973036920071",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7491733228676517138",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7491356537030511890",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7490990305634782471",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7490262123868654853",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7489496179227626757",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7488929614123896070",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7488260017108323590",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7487661538917076229",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7487295732135808261",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7486518516250709255",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7486159821541149960",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7485809277811182856",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7485430384545533204",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7485057557304790293",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7484695412318702869",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7484268322263977236",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7482850779892616469",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7482265944383950101",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7481708412640742676",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7481708412640742676",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7479875645229616405",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7479489598691740946",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7478763656130415880",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7478384124076494098",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7477647872708889864",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7477268475296091413",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7475027304247299349",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7474303898333875463",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7473909022907714837",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7473548894215884052",
        "https://www.tiktok.com/@thincanbangchuyenhoa/video/7472052752370240786"
    ]

    results = get_facebook_titles_from_list(url_list)
    save_to_word_ordered(results)
