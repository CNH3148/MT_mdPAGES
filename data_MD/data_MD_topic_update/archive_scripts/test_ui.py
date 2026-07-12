"""Test pygetwindow"""
import sys
import pygetwindow as gw

sys.stdout.reconfigure(encoding='utf-8')

print("All windows:")
for w in gw.getAllWindows():
    if w.title:
        print(f" - {w.title}")

ai_windows = [w for w in gw.getAllWindows() if 'Google AI Studio' in w.title or 'Chrome' in w.title]
if ai_windows:
    print(f"Activating: {ai_windows[0].title}")
    try:
        ai_windows[0].activate()
        print("Activated!")
    except Exception as e:
        print(f"Failed to activate: {e}")
