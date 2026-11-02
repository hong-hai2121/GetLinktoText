import tkinter as tk
from GetTextFromLink import GetTextApp

root = tk.Tk()
root.withdraw()  # don't show the main window
app = GetTextApp(root)

# Simulate toggles
app.on_view_links()
# process pending tkinter callbacks (so self.log's after(0, ...) runs)
root.update()
links_content = app.links_text.get("1.0", "end").strip()
print("LINKS_CONTENT_START:\n", links_content[:500])

app.on_view_result()
root.update()
result_content = app.result_text.get("1.0", "end").strip()
print("RESULT_CONTENT_START:\n", result_content[:500])

app.on_view_log()
root.update()
log_content = app.log_text.get("1.0", "end").strip()
print("LOG_CONTENT_END:\n", log_content.splitlines()[-10:])

root.destroy()
