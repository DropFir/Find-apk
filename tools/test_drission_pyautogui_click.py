#!/usr/bin/env python3
"""Verify DrissionPage element coordinates with a real PyAutoGUI mouse click.

This diagnostic intentionally opens only its embedded local test page. It does
not accept an external URL or locator and must not be used for CAPTCHA widgets.
"""

from __future__ import annotations

import argparse
import json
import time

from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
from DrissionPage import Chromium
import pyautogui


TEST_PAGE = """<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>Find-APK 鼠标联动测试</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: #07110d;
    color: #f4fff8;
    font: 18px/1.5 -apple-system, BlinkMacSystemFont, sans-serif;
  }
  main { text-align: center; }
  button {
    min-width: 320px;
    min-height: 96px;
    border: 2px solid #9bff43;
    border-radius: 18px;
    background: #5a8f2d;
    color: white;
    font-size: 24px;
    font-weight: 750;
    cursor: pointer;
  }
  #result { margin-top: 24px; color: #9bff43; font-weight: 700; }
</style>
<main>
  <h1>DrissionPage + PyAutoGUI</h1>
  <p>下面按钮只用于本机真实鼠标点击测试。</p>
  <button id="find-apk-pointer-test" type="button">执行测试点击</button>
  <div id="result">WAITING</div>
</main>
<script>
  document.querySelector('#find-apk-pointer-test').addEventListener('click', event => {
    document.body.dataset.pointerTest = event.isTrusted ? 'trusted' : 'synthetic';
    document.querySelector('#result').textContent = event.isTrusted
      ? 'CLICK_OK_TRUSTED'
      : 'CLICK_OK_SYNTHETIC';
  });
</script>
</html>"""


def run_test(port: int, *, keep_open: bool = False) -> dict[str, object]:
    browser = Chromium(port)
    tab = browser.new_tab("about:blank", background=False)
    try:
        tab.run_js(
            f"document.open();document.write({json.dumps(TEST_PAGE)});document.close();"
        )
        tab._run_cdp("Page.bringToFront")
        application = NSRunningApplication.runningApplicationWithProcessIdentifier_(
            browser.process_id
        )
        if application is None:
            raise RuntimeError("无法定位专用 Chrome 进程")
        application.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.4)
        button = tab.ele("#find-apk-pointer-test", timeout=5)
        if not button:
            raise RuntimeError("本机测试按钮未加载")

        viewport_x, viewport_y = button.rect.viewport_midpoint
        metrics = tab.run_js(
            "return {screenX,screenY,outerWidth,outerHeight,innerWidth,innerHeight}"
        )
        frame_x = max(0, (metrics["outerWidth"] - metrics["innerWidth"]) / 2)
        frame_y = max(0, metrics["outerHeight"] - metrics["innerHeight"])
        x = round(metrics["screenX"] + frame_x + viewport_x)
        y = round(metrics["screenY"] + frame_y + viewport_y)
        window = tab._run_cdp("Browser.getWindowForTarget")["bounds"]
        pyautogui.PAUSE = 0.15
        pyautogui.FAILSAFE = True
        pyautogui.moveTo(x, y, duration=0.35)
        pyautogui.click()

        result = tab.ele("#result", timeout=3)
        text = str(result.text if result else "")
        if text != "CLICK_OK_TRUSTED":
            cursor = pyautogui.position()
            raise RuntimeError(
                "真实鼠标点击未命中测试按钮："
                f"{text or 'no_result'}；目标=({x},{y})；"
                f"鼠标=({cursor.x},{cursor.y})；窗口={window}"
            )
        return {
            "classification": "trusted_pointer_click_ok",
            "point": {"x": x, "y": y},
            "window": window,
            "viewport": metrics,
            "event": "trusted",
        }
    finally:
        if not keep_open:
            browser.close_tabs(tab)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test DrissionPage coordinates using one real PyAutoGUI click."
    )
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--keep-open", action="store_true")
    arguments = parser.parse_args()
    print(
        json.dumps(
            run_test(arguments.port, keep_open=arguments.keep_open),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
