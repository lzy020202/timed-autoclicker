import ctypes
import ctypes.wintypes
import json
import queue
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from tkinter import messagebox, ttk


APP_NAME = "定时连点器"
WM_HOTKEY = 0x0312
VK_F8 = 0x77
MOD_NOREPEAT = 0x4000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class TimeSource:
    def __init__(self):
        self.offset = 0.0
        self.name = "系统时间"

    def now(self):
        return datetime.now().astimezone() + timedelta(seconds=self.offset)

    def sync(self, source):
        if source == "系统时间":
            self.offset = 0.0
            self.name = source
            return 0.0

        start_wall = time.time()
        start_mono = time.perf_counter()
        if source == "淘宝时间":
            req = urllib.request.Request(
                "https://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                server = int(data["data"]["t"]) / 1000.0
        else:
            req = urllib.request.Request("https://www.ele.me/", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                value = response.headers.get("Date")
                if not value:
                    raise RuntimeError("响应中没有 Date 时间头")
                server = parsedate_to_datetime(value).timestamp()

        elapsed = time.perf_counter() - start_mono
        midpoint = start_wall + elapsed / 2
        self.offset = server - midpoint
        self.name = source
        return self.offset


class ClickEngine:
    def __init__(self, status_callback):
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.thread = None

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, target_timestamp, offset, interval_ms, count):
        if self.running:
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run,
            args=(target_timestamp, offset, interval_ms / 1000.0, count),
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self, target_timestamp, offset, interval, count):
        self.status_callback("等待开始")
        while not self.stop_event.is_set():
            remaining = target_timestamp - (time.time() + offset)
            if remaining <= 0:
                break
            self.stop_event.wait(min(remaining, 0.05 if remaining < 1 else 0.5))

        if self.stop_event.is_set():
            self.status_callback("已停止")
            return

        self.status_callback("正在连点")
        done = 0
        next_click = time.perf_counter()
        while not self.stop_event.is_set() and (count == 0 or done < count):
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            done += 1
            next_click += interval
            delay = next_click - time.perf_counter()
            if delay > 0:
                self.stop_event.wait(delay)
        self.status_callback("已停止" if self.stop_event.is_set() else f"已完成（{done} 次）")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("530x430")
        self.resizable(False, False)
        self.time_source = TimeSource()
        self.events = queue.Queue()
        self.engine = ClickEngine(lambda text: self.events.put(("status", text)))
        self._build()
        self._set_default_time()
        self.after(50, self._poll)
        self.after(100, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

    def _build(self):
        box = ttk.Frame(self, padding=18)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="定时鼠标连点", font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 16)
        )

        ttk.Label(box, text="时间源").grid(row=1, column=0, sticky="w", pady=6)
        self.source = ttk.Combobox(
            box, state="readonly", width=18, values=("系统时间", "淘宝时间", "饿了么时间")
        )
        self.source.set("系统时间")
        self.source.grid(row=1, column=1, sticky="w")
        ttk.Button(box, text="立即校时", command=self.sync_time).grid(row=1, column=2, padx=8)

        ttk.Label(box, text="当前时间").grid(row=2, column=0, sticky="w", pady=6)
        self.clock = ttk.Label(box, text="--", font=("Consolas", 12))
        self.clock.grid(row=2, column=1, columnspan=2, sticky="w")

        ttk.Label(box, text="开始时间").grid(row=3, column=0, sticky="w", pady=6)
        self.start_value = tk.StringVar()
        ttk.Entry(box, textvariable=self.start_value, width=26).grid(row=3, column=1, sticky="w")
        ttk.Label(box, text="YYYY-MM-DD HH:MM:SS.mmm").grid(row=3, column=2, sticky="w")

        ttk.Label(box, text="点击间隔").grid(row=4, column=0, sticky="w", pady=6)
        self.interval = tk.StringVar(value="100")
        ttk.Entry(box, textvariable=self.interval, width=12).grid(row=4, column=1, sticky="w")
        ttk.Label(box, text="毫秒（建议 ≥ 10）").grid(row=4, column=2, sticky="w")

        ttk.Label(box, text="点击次数").grid(row=5, column=0, sticky="w", pady=6)
        self.count = tk.StringVar(value="0")
        ttk.Entry(box, textvariable=self.count, width=12).grid(row=5, column=1, sticky="w")
        ttk.Label(box, text="0 表示一直点击").grid(row=5, column=2, sticky="w")

        ttk.Separator(box).grid(row=6, column=0, columnspan=3, sticky="ew", pady=15)
        self.status = tk.StringVar(value="就绪")
        ttk.Label(box, textvariable=self.status, font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w"
        )
        button_row = ttk.Frame(box)
        button_row.grid(row=8, column=0, columnspan=3, sticky="w", pady=14)
        ttk.Button(button_row, text="开始 / 等待", command=self.start, width=16).pack(side="left")
        ttk.Button(button_row, text="停止", command=self.stop, width=12).pack(side="left", padx=10)
        ttk.Label(box, text="F8：开始或紧急停止 · 点击位置为鼠标当前所在位置").grid(
            row=9, column=0, columnspan=3, sticky="w"
        )

    def _set_default_time(self):
        future = self.time_source.now() + timedelta(seconds=10)
        self.start_value.set(future.strftime("%Y-%m-%d %H:%M:%S.") + f"{future.microsecond // 1000:03d}")

    def _tick(self):
        now = self.time_source.now()
        self.clock.config(text=now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}")
        self.after(50, self._tick)

    def sync_time(self):
        source = self.source.get()
        self.status.set(f"正在同步{source}…")
        threading.Thread(target=self._sync_worker, args=(source,), daemon=True).start()

    def _sync_worker(self, source):
        try:
            offset = self.time_source.sync(source)
            self.events.put(("sync", source, offset))
        except Exception as exc:
            self.events.put(("error", f"校时失败：{exc}"))

    def start(self):
        if self.engine.running:
            self.stop()
            return
        try:
            target = datetime.strptime(self.start_value.get().strip(), "%Y-%m-%d %H:%M:%S.%f")
            target = target.replace(tzinfo=datetime.now().astimezone().tzinfo).timestamp()
            interval = int(self.interval.get())
            count = int(self.count.get())
            if interval < 1 or count < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "请检查开始时间、点击间隔和点击次数。")
            return
        self.engine.start(target, self.time_source.offset, interval, count)

    def stop(self):
        self.engine.stop()
        self.status.set("正在停止…")

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    self.status.set(event[1])
                elif event[0] == "sync":
                    self.status.set(f"已同步{event[1]}，偏差 {event[2] * 1000:+.0f} ms")
                elif event[0] == "hotkey":
                    self.stop() if self.engine.running else self.start()
                else:
                    self.status.set("校时失败")
                    messagebox.showerror(APP_NAME, event[1])
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _hotkey_loop(self):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, MOD_NOREPEAT, VK_F8):
            self.events.put(("error", "F8 全局热键注册失败，可能已被其他程序占用。"))
            return
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                self.events.put(("hotkey",))
        user32.UnregisterHotKey(None, 1)

    def _close(self):
        self.engine.stop()
        self.destroy()


if __name__ == "__main__":
    if not hasattr(ctypes, "windll"):
        raise SystemExit("此程序仅支持 Windows。")
    App().mainloop()
