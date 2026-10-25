#!/bin/zsh
# Mở cửa sổ "Ghép video Flow" trên macOS — file chạy của shortcut "Ghép video Flow.app" trên Desktop gọi thẳng script này
# (exec: python thay chỗ script trong CÙNG tiến trình, nên Dock hiện icon + tên của .app, không có cửa sổ Terminal/python thừa).
# Tạo .app: xem ghi chú trong app_gui.py (thư mục .app chỉ gồm Info.plist, icon và một script exec file này).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")" || exit 1
exec ../venv/bin/python app_gui.py > /tmp/ghep_video_flow.log 2>&1
