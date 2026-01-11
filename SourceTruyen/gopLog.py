import os
from pathlib import Path

# =========================
# CẤU HÌNH
# =========================
CLEANED_DIR = r"SourceTruyen/Cleaned"
OUTPUT_LOG_FILE = r"SourceTruyen/Cleaned/ALL_ERRORS_COMBINED.log"

def collect_and_merge_logs():
    """Gộp tất cả các file *_log.txt thành 1 file với header cho mỗi file."""
    
    cleaned_path = Path(CLEANED_DIR)
    if not cleaned_path.exists():
        print(f"❌ Không tìm thấy thư mục: {CLEANED_DIR}")
        return
    
    # Tìm tất cả file log
    log_files = sorted(cleaned_path.glob("*_log.txt"))
    
    if not log_files:
        print(f"❌ Không tìm thấy file log nào trong: {CLEANED_DIR}")
        return
    
    print(f"📁 Tìm thấy {len(log_files)} file log")
    
    # Gộp tất cả log vào 1 file
    total_errors = 0
    with open(OUTPUT_LOG_FILE, "w", encoding="utf-8") as out_file:
        out_file.write("=" * 80 + "\n")
        out_file.write("TỔNG HỢP TẤT CẢ LỖI TỪ CÁC FILE TRANSLATED\n")
        out_file.write(f"Tổng số file log: {len(log_files)}\n")
        out_file.write("=" * 80 + "\n\n")
        
        for log_file in log_files:
            # Đọc nội dung file log
            try:
                with open(log_file, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                
                # Nếu file log có nội dung (có lỗi)
                if content:
                    file_name = log_file.name
                    error_count = content.count("⚠️")
                    total_errors += error_count
                    
                    # Viết header cho file này
                    out_file.write("\n" + "=" * 80 + "\n")
                    out_file.write(f"📄 FILE: {file_name}\n")
                    out_file.write(f"   SRT tương ứng: {file_name.replace('_log.txt', '.srt')}\n")
                    out_file.write(f"   Số lỗi: {error_count}\n")
                    out_file.write("-" * 80 + "\n\n")
                    
                    # Viết nội dung lỗi
                    out_file.write(content)
                    out_file.write("\n\n")
                    
                    print(f"✅ {file_name}: {error_count} lỗi")
                else:
                    print(f"   {log_file.name}: Không có lỗi")
                    
            except Exception as e:
                print(f"❌ Lỗi khi đọc {log_file.name}: {e}")
        
        # Viết tổng kết cuối file
        out_file.write("\n" + "=" * 80 + "\n")
        out_file.write(f"📊 TỔNG KẾT\n")
        out_file.write(f"   - Tổng số file log đã kiểm tra: {len(log_files)}\n")
        out_file.write(f"   - Tổng số lỗi tìm thấy: {total_errors}\n")
        out_file.write("=" * 80 + "\n")
    
    print(f"\n🎉 Đã gộp tất cả log vào: {OUTPUT_LOG_FILE}")
    print(f"📊 Tổng số lỗi: {total_errors}")
    
    return OUTPUT_LOG_FILE

if __name__ == "__main__":
    output_file = collect_and_merge_logs()
    if output_file:
        print(f"\n💡 Mở file để xem: {output_file}")
