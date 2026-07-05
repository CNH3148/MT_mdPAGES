import time
import pygetwindow as gw
import pyautogui
import pyperclip

print("5 秒後將嘗試把 Google AI Studio 帶到最上層，並貼上測試文字。請保持 Chrome 開啟...")
time.sleep(5)

pyperclip.copy("這是來自 pyautogui 的全自動 OS 級貼上測試")

windows = [w for w in gw.getAllWindows() if 'Google AI' in w.title or 'Chrome' in w.title]
if windows:
    win = windows[0]
    print(f"找到視窗: {win.title}")
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
    except Exception as e:
        print(f"Activate failed: {e}")
    
    time.sleep(1)
    # 模擬原生鍵盤貼上
    pyautogui.hotkey('ctrl', 'v')
    print("已送出 Ctrl+V")
    time.sleep(1)
else:
    print("找不到 Chrome 視窗")
