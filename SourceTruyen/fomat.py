import os
import json

# Cấu hình thư mục
folder1 = r"C:\Users\PC\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\10"
folder2 = r"C:\Users\PC\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\10 - Copy"

def format_json_files(folder_path):
    """Format tất cả JSON files trong thư mục"""
    print(f"\n📁 Đang format thư mục: {folder_path}")
    
    count = 0
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            if filename.lower().endswith(('.json', '.json.bak', '.extra')):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    
                    print(f"   ✅ {filename}")
                    count += 1
                except Exception as e:
                    print(f"   ❌ {filename}: {e}")
    
    print(f"✨ Đã format {count} files\n")

if __name__ == "__main__":
    print("="*70)
    print("🔧 CHƯƠNG TRÌNH FORMAT JSON FILES")
    print("="*70)
    
    # Format cả 2 thư mục
    format_json_files(folder1)
    format_json_files(folder2)
    
    print("="*70)
    print("✅ HOÀN THÀNH!")
    print("="*70)

