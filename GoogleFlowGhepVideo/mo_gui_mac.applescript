-- Launcher macOS cho shortcut "Ghép video Flow.app" (tạo: osacompile -o "Ghép video Flow.app" mo_gui_mac.applescript,
-- rồi đổi icon .app thành ghep_video.ico). Chạy python qua symlink "Ghep video Flow" để Dock hiện đúng tên app.
do shell script "export PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"; cd /Users/dr/bachoiAI/GetLinktoText/GoogleFlowGhepVideo && { [ -e '../venv/bin/Ghep video Flow' ] || ln -s python '../venv/bin/Ghep video Flow'; } && nohup '../venv/bin/Ghep video Flow' app_gui.py > /tmp/ghep_video_flow.log 2>&1 &"
