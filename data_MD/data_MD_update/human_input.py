"""
human_input.py — 擬人化輸入模組
================================

針對 Google AI Studio (aistudio.google.com) 的 reCAPTCHA Enterprise
行為指紋偵測所設計。reCAPTCHA Enterprise 在事件層級偵測四個非人類訊號：

  1. click dwell（mousedown→mouseup 時長）：pyautogui ≈ 0ms，人類 50-150ms
  2. 時序熵：固定 time.sleep → σ≈0，人類 σ>0
  3. 滑鼠軌跡：直線等速無抖動 vs 貝茲曲線+鐘形速度+微抖動
  4. 點擊位置：精確幾何中心 vs 高斯散射

本模組把每個事件做到「物理層與人類不可區分」：

  - jsleep(min, max)        取代固定 time.sleep
  - human_move_to(x, y)     貝茲曲線軌跡 + 鐘形速度 + tremor + 偶爾過衝
  - human_click(x, y)       高斯散射 + 真實 dwell 50-150ms
  - human_press(key)        按鍵 dwell 60-120ms
  - human_hotkey(*keys)     修飾鍵組合（Ctrl+A/V/Enter 等）

底層優先使用 pydirectinput（SendInput API），失敗才退回 pyautogui。
SendInput 產生的事件在 Chrome 中比 pyautogui 的 mouse_event/keybd_event
更可能被視為真實硬體事件。
"""
from __future__ import annotations

import math
import random
import time
from typing import Iterable

# ── 底層引擎選擇 ──────────────────────────────────────────
# pydirectinput 基於 SendInput，事件品質優於 pyautogui 的 mouse_event。
# 但兩者 API 幾乎一致，可無縫替換。
try:
    import pydirectinput as _di
    _ENGINE = "pydirectinput"
    # 關閉 pydirectinput 預設的 PAUSE，由本模組自行控制節奏
    _di.PAUSE = 0
except ImportError:
    import pyautogui as _di
    _ENGINE = "pyautogui"
    _di.PAUSE = 0


# ── 節奏：jsleep ─────────────────────────────────────────
def jsleep(min_s: float, max_s: float | None = None) -> None:
    """Jittered sleep. 取代所有固定的 time.sleep 呼叫。

    jsleep(2)       → sleep(2)          # 精確暫停（用於純等待）
    jsleep(1.5, 2.8)→ sleep(uniform)    # 隨機暫停（用於事件間隔）
    """
    if max_s is None:
        time.sleep(min_s)
    else:
        if max_s < min_s:
            min_s, max_s = max_s, min_s
        time.sleep(random.uniform(min_s, max_s))


# ── 貝茲曲線工具 ─────────────────────────────────────────
def _cubic_bezier(p0, p1, p2, p3, num_steps: int) -> list[tuple[float, float]]:
    """計算三次貝茲曲線上的點。"""
    points = []
    for i in range(num_steps + 1):
        t = i / num_steps
        mt = 1 - t
        x = (mt**3) * p0[0] + 3 * (mt**2) * t * p1[0] + 3 * mt * (t**2) * p2[0] + (t**3) * p3[0]
        y = (mt**3) * p0[1] + 3 * (mt**2) * t * p1[1] + 3 * mt * (t**2) * p2[1] + (t**3) * p3[1]
        points.append((x, y))
    return points


def _ease_out_quint(t: float) -> float:
    """鐘形速度剖面：開始快加速、接近終點緩減速（minimum-jerk 近似）。"""
    return 1 - (1 - t) ** 5


# ── 滑鼠移動：human_move_to ──────────────────────────────
def _current_pos() -> tuple[int, int]:
    pos = _di.position()
    return (pos.x, pos.y) if hasattr(pos, "x") else (pos[0], pos[1])


def human_move_to(
    dest_x: int,
    dest_y: int,
    *,
    duration: float | None = None,
    overshoot: bool = True,
) -> None:
    """擬人化滑鼠移動。

    特徵：
    - 三次貝茲曲線軌跡（非直線）
    - 鐘形速度剖面（非等速）
    - 每步疊加高斯 tremor（人類生理顫動）
    - 5-20% 機率過衝後修正（更像人類）
    - 自適應時長：距離越遠越久，並加入隨機性
    """
    start_x, start_y = _current_pos()
    dx = dest_x - start_x
    dy = dest_y - start_y
    dist = math.hypot(dx, dy)

    if dist < 2:
        # 極短距離直接到位，但仍加一點微小抖動
        _di.moveTo(dest_x + random.randint(-1, 1), dest_y + random.randint(-1, 1))
        return

    # 自適應時長：近距離快、遠距離慢，加隨機
    if duration is None:
        duration = min(0.9, max(0.18, dist / 1800)) * random.uniform(0.85, 1.25)

    # 貝茲控制點：在直線兩側隨機偏移，產生弧線
    mid_x = start_x + dx * 0.5
    mid_y = start_y + dy * 0.5
    perp_x = -dy / dist
    perp_y = dx / dist
    curve_offset = dist * random.uniform(-0.15, 0.25)
    # 兩個控制點各偏移一點，製造不對稱弧線
    off1 = curve_offset * random.uniform(0.6, 1.1)
    off2 = curve_offset * random.uniform(0.6, 1.1)
    p0 = (start_x, start_y)
    p1 = (start_x + dx * 0.3 + perp_x * off1, start_y + dy * 0.3 + perp_y * off1)
    p2 = (start_x + dx * 0.7 + perp_x * off2, start_y + dy * 0.7 + perp_y * off2)

    # 偶爾過衝（5-20% 機率，距離夠長時才有意義）
    do_overshoot = overshoot and dist > 80 and random.random() < 0.15
    if do_overshoot:
        over_dist = random.uniform(3, 8)
        p3 = (dest_x + perp_x * over_dist + dx * 0.02,
              dest_y + perp_y * over_dist + dy * 0.02)
    else:
        p3 = (dest_x, dest_y)

    steps = max(12, int(duration / 0.008))  # ~8ms 每步，產生密集 mousemove
    points = _cubic_bezier(p0, p1, p2, p3, steps)

    step_interval = duration / steps
    for i, (x, y) in enumerate(points):
        # 高斯 tremor：1-3px 生理顫動
        tx = x + random.gauss(0, 0.6)
        ty = y + random.gauss(0, 0.6)
        _di.moveTo(int(tx), int(ty))
        time.sleep(step_interval)

    if do_overshoot:
        # 過衝後拉回正確位置（人類修正動作）
        jsleep(0.04, 0.12)
        steps2 = max(4, int(random.uniform(8, 16)))
        back_points = _cubic_bezier(p3, p3, (dest_x, dest_y), (dest_x, dest_y), steps2)
        for x, y in back_points:
            _di.moveTo(int(x + random.gauss(0, 0.4)),
                       int(y + random.gauss(0, 0.4)))
            time.sleep(0.008)


# ── 滑鼠點擊：human_click ────────────────────────────────
def human_click(
    x: int | None = None,
    y: int | None = None,
    *,
    button: str = "left",
    clicks: int = 1,
    move_first: bool = True,
    dwell: tuple[float, float] = (0.05, 0.15),
) -> None:
    """擬人化點擊。

    特徵：
    - 點擊位置高斯散射（不命中精確中心）
    - 先擬人移動到位（可關閉）
    - 點擊前人類慣性微停頓
    - mousedown→mouseup dwell 50-150ms（reCAPTCHA 最敏感訊號）
    - 雙擊時兩擊間也有隨機間隔
    """
    if x is not None and y is not None:
        # 高斯散射：σ≈3px，幾乎不命中正中心
        actual_x = int(x + random.gauss(0, 3))
        actual_y = int(y + random.gauss(0, 3))
        if move_first:
            human_move_to(actual_x, actual_y)
        else:
            _di.moveTo(actual_x, actual_y)
        # 點擊前人類慣性停頓（眼神/手指就位）
        jsleep(0.05, 0.22)

    for c in range(clicks):
        _di.mouseDown(actual_x if x is not None else None,
                      actual_y if y is not None else None,
                      button=button)
        jsleep(*dwell)  # ★ 核心修復：真實 dwell
        _di.mouseUp(actual_x if x is not None else None,
                    actual_y if y is not None else None,
                    button=button)
        if c < clicks - 1:
            jsleep(0.06, 0.14)  # 雙擊間隔


def human_click_image(
    img_path: str,
    confidence: float = 0.8,
    timeout: float = 10,
    *,
    button: str = "left",
    dwell: tuple[float, float] = (0.05, 0.15),
) -> bool:
    """影像辨識定位後執行 human_click（不使用 pyautogui.click）。

    回傳 True 表示成功找到並點擊。
    """
    import pyautogui  # 影像辨識仍用 pyautogui（pydirectinput 無此能力）
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            location = pyautogui.locateCenterOnScreen(img_path, confidence=confidence)
            if location:
                human_click(location.x, location.y, button=button, dwell=dwell)
                return True
        except pyautogui.ImageNotFoundException:
            pass
        except Exception:
            pass
        jsleep(0.6, 1.2)
    return False


# ── 按鍵：human_press / human_hotkey ─────────────────────
def human_press(key: str, *, presses: int = 1) -> None:
    """擬人化單鍵按擊。dwell 60-120ms。"""
    for _ in range(presses):
        _di.keyDown(key)
        jsleep(0.06, 0.12)
        _di.keyUp(key)
        jsleep(0.04, 0.10)


def human_hotkey(*keys: str) -> None:
    """擬人化組合鍵（如 human_hotkey('ctrl', 'v')）。

    依序 keyDown 每個鍵（間隔 jitter）→ 反向依序 keyUp。
    """
    for k in keys:
        _di.keyDown(k)
        jsleep(0.04, 0.09)
    jsleep(0.02, 0.06)  # 組合鍵穩定時間
    for k in reversed(keys):
        _di.keyUp(k)
        jsleep(0.03, 0.07)


def human_write(text: str, *, interval: tuple[float, float] = (0.02, 0.06)) -> None:
    """擬人化逐字打字（罕用，因為貼上更擬真）。保留供特殊情境。"""
    for ch in text:
        _di.press(ch)
        jsleep(*interval)


# ── 滾輪：human_scroll ───────────────────────────────────
def human_scroll(clicks: int, *, smooth: bool = True) -> None:
    """擬人化滾輪。因為 pydirectinput 不支援 scroll，故強制使用 pyautogui"""
    import pyautogui
    if not smooth or abs(clicks) <= 120:
        pyautogui.scroll(clicks)
        return
    direction = 1 if clicks > 0 else -1
    remaining = abs(clicks)
    while remaining > 0:
        # 將 chunk 放大以符合 Windows 刻度 (100~250 相當於 1~2 格滾輪)
        chunk = min(remaining, random.randint(100, 250))
        pyautogui.scroll(direction * chunk)
        remaining -= chunk
        jsleep(0.05, 0.18)


ENGINE = _ENGINE  # 供外部檢視目前使用的引擎
