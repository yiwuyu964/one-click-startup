from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from launcher_config import Config
from launcher_scanner import AppEntry, scan_apps


APP_TITLE = "一键启动"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x660")
        self.root.minsize(600, 480)

        self.config = Config(CONFIG_PATH)
        self.config.load()

        self.entries: list[AppEntry] = []
        self.vars: dict[str, tk.BooleanVar] = {}
        self.current_shown: list[AppEntry] = []
        self.filter_var = tk.StringVar()
        self.profile_var = tk.StringVar()
        self.status_var = tk.StringVar(value="正在扫描本地应用…")
        self.scan_generation = 0
        self.scan_queue: queue.Queue[tuple[str, object]] | None = None

        self._build_ui()
        self._bind_events()
        self.start_scan()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text=APP_TITLE, font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(header, text="重新扫描", command=self.start_scan).grid(row=0, column=2, padx=(8, 0))

        search_frame = ttk.Frame(header)
        search_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        search_frame.columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="搜索：").grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(search_frame, textvariable=self.filter_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")

        profile_frame = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        profile_frame.grid(row=1, column=0, sticky="ew")
        ttk.Label(profile_frame, text="存档：").pack(side="left")
        self.profile_combo = ttk.Combobox(
            profile_frame,
            textvariable=self.profile_var,
            state="readonly",
            width=18,
        )
        self.profile_combo.pack(side="left")
        self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_selected)
        ttk.Button(profile_frame, text="新建", command=self.create_profile).pack(side="left", padx=(8, 0))
        ttk.Button(profile_frame, text="保存当前", command=self.save_current_to_profile).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(profile_frame, text="重命名", command=self.rename_profile).pack(side="left", padx=(6, 0))
        ttk.Button(profile_frame, text="删除", command=self.delete_profile).pack(side="left", padx=(6, 0))

        toolbar = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        toolbar.grid(row=3, column=0, sticky="ew")
        ttk.Button(toolbar, text="全选当前", command=self.select_shown).pack(side="left")
        ttk.Button(toolbar, text="清空全部", command=self.clear_all).pack(side="left", padx=(8, 0))
        self.count_var = tk.StringVar(value="已选 0 个")
        ttk.Label(toolbar, textvariable=self.count_var).pack(side="right")

        list_frame = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(list_frame, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.list_inner = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_inner, anchor="nw")
        self.list_inner.bind("<Configure>", self._on_list_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        footer = ttk.Frame(self.root, padding=(12, 8, 12, 12))
        footer.grid(row=4, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, foreground="#666666").grid(
            row=0, column=0, sticky="w"
        )
        self.launch_button = ttk.Button(footer, text="一键启动所选应用", command=self.launch_selected)
        self.launch_button.grid(row=0, column=1, sticky="e")
        self.launch_profile_button = ttk.Button(
            footer, text="一键启动此存档", command=self.launch_profile
        )
        self.launch_profile_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _bind_events(self) -> None:
        self.filter_var.trace_add("write", lambda *_: self.rebuild_list())
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _on_list_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def refresh_profile_values(self) -> None:
        names = self.config.profile_names()
        self.profile_combo.configure(values=names)
        active = self.config.active_profile
        if active not in names and names:
            active = names[0]
            self.config.active_profile = active
        self.profile_var.set(active)

    def on_profile_selected(self, _event: tk.Event | None = None) -> None:
        name = self.profile_var.get()
        if name:
            self.apply_profile(name)

    def apply_profile(self, name: str, save: bool = True) -> int:
        if name not in self.config.profiles:
            return 0

        self.config.active_profile = name
        targets = set(self.config.get_profile(name))
        for entry in self.entries:
            var = self.vars.get(entry.target)
            if var is not None:
                var.set(entry.target in targets)

        self.profile_var.set(name)
        self.update_count()
        missing = len(targets - {entry.target for entry in self.entries})
        if save:
            try:
                self.config.save()
            except OSError:
                pass
        return missing

    def create_profile(self) -> None:
        name = simpledialog.askstring("新建存档", "请输入存档名称：", parent=self.root)
        if name is None:
            return
        name = name.strip()
        if not name:
            return
        if name in self.config.profiles:
            if not messagebox.askyesno(
                APP_TITLE,
                f"存档“{name}”已存在，覆盖后该存档将清空，确定要覆盖吗？",
            ):
                return

        self.config.set_profile(name, [])
        try:
            self.config.save()
        except OSError:
            pass
        self.refresh_profile_values()
        self.apply_profile(name, save=False)
        self.filter_var.set("")
        self.status_var.set(f"已新建空存档“{name}”，请勾选需要的应用")

    def save_current_to_profile(self) -> None:
        name = self.profile_var.get() or self.config.active_profile
        if not name:
            return
        self.config.set_profile(name, self.current_selected_targets())
        try:
            self.config.save()
        except OSError:
            pass
        self.status_var.set(f"已保存到存档“{name}”")

    def rename_profile(self) -> None:
        old_name = self.profile_var.get()
        if not old_name:
            return
        new_name = simpledialog.askstring(
            "重命名存档",
            "请输入新的存档名称：",
            initialvalue=old_name,
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if new_name in self.config.profiles:
            messagebox.showwarning(APP_TITLE, f"存档“{new_name}”已存在。")
            return

        if self.config.rename_profile(old_name, new_name):
            try:
                self.config.save()
            except OSError:
                pass
            self.refresh_profile_values()
            self.profile_var.set(new_name)
            self.status_var.set(f"已重命名为“{new_name}”")

    def delete_profile(self) -> None:
        name = self.profile_var.get()
        if not name:
            return
        if len(self.config.profiles) <= 1:
            messagebox.showinfo(APP_TITLE, "至少保留一个存档。")
            return
        if not messagebox.askyesno(APP_TITLE, f"确定删除存档“{name}”吗？"):
            return

        if self.config.delete_profile(name):
            try:
                self.config.save()
            except OSError:
                pass
            self.refresh_profile_values()
            self.apply_profile(self.config.active_profile, save=False)
            self.status_var.set(f"已删除存档“{name}”")

    def launch_profile(self) -> None:
        name = self.profile_var.get() or self.config.active_profile
        if not name:
            return
        self.apply_profile(name)
        self._launch_entries(self._selected_entries(), profile_name=name)

    def start_scan(self) -> None:
        self.status_var.set("正在扫描本地应用…")
        for child in self.list_inner.winfo_children():
            child.destroy()
        self.launch_button.configure(state="disabled")
        self.launch_profile_button.configure(state="disabled")
        self.scan_generation += 1
        generation = self.scan_generation
        self.scan_queue = queue.Queue()
        threading.Thread(target=self._scan_worker, args=(self.scan_queue,), daemon=True).start()
        self.root.after(100, lambda: self._poll_scan(self.scan_queue, generation))

    def _scan_worker(self, result_queue: queue.Queue[tuple[str, object]]) -> None:
        try:
            entries = scan_apps()
        except Exception as exc:  # noqa: BLE001
            result_queue.put(("error", exc))
        else:
            result_queue.put(("ok", entries))

    def _poll_scan(self, result_queue: queue.Queue[tuple[str, object]] | None, generation: int) -> None:
        if result_queue is None or generation != self.scan_generation:
            return
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, lambda: self._poll_scan(result_queue, generation))
            return

        if kind == "ok":
            self._scan_done(payload)  # type: ignore[arg-type]
        else:
            self._scan_failed(payload)  # type: ignore[arg-type]

    def _scan_failed(self, exc: Exception) -> None:
        self.launch_button.configure(state="normal")
        self.launch_profile_button.configure(state="normal")
        self.status_var.set("扫描失败")
        messagebox.showerror("扫描失败", f"扫描本地应用时出错：\n{exc}")

    def _scan_done(self, entries: list[AppEntry]) -> None:
        self.entries = entries
        self.vars = {}
        for entry in entries:
            self.vars[entry.target] = tk.BooleanVar(value=False)

        self.refresh_profile_values()
        missing = self.apply_profile(self.config.active_profile, save=False)
        self.rebuild_list()
        self.launch_button.configure(state="normal")
        self.launch_profile_button.configure(state="normal")
        self.update_count()
        name = self.config.active_profile
        if missing:
            self.status_var.set(f"已找到 {len(entries)} 个应用，存档“{name}”有 {missing} 个未找到")
        else:
            self.status_var.set(f"已找到 {len(entries)} 个应用，当前存档：{name}")

    def rebuild_list(self) -> None:
        for child in self.list_inner.winfo_children():
            child.destroy()

        query = self.filter_var.get().strip().lower()
        self.current_shown = [
            entry
            for entry in self.entries
            if not query
            or query in entry.name.lower()
            or query in entry.target.lower()
            or query in entry.category.lower()
        ]

        for entry in self.current_shown:
            self._add_app_row(entry)

        if not self.current_shown:
            ttk.Label(
                self.list_inner,
                text="没有匹配的应用，可点击右上角“重新扫描”。",
                foreground="#888888",
            ).pack(anchor="w", pady=12)

        self.update_count()

    def _add_app_row(self, entry: AppEntry) -> None:
        var = self.vars.get(entry.target)
        if var is None:
            var = tk.BooleanVar(value=False)
            self.vars[entry.target] = var

        row = ttk.Frame(self.list_inner, padding=(0, 4))
        row.pack(fill="x", anchor="w")

        cb = ttk.Checkbutton(row, text=entry.name, variable=var, command=self.on_toggle)
        cb.pack(anchor="w")

        detail = ttk.Label(
            row,
            text=f"{entry.category} · {entry.target}",
            foreground="#777777",
            font=("Microsoft YaHei UI", 8),
        )
        detail.pack(anchor="w", padx=(22, 0))

    def on_toggle(self) -> None:
        self.update_count()
        self.save_selection()

    def select_shown(self) -> None:
        for entry in self.current_shown:
            self.vars[entry.target].set(True)
        self.update_count()
        self.save_selection()

    def clear_all(self) -> None:
        for var in self.vars.values():
            var.set(False)
        self.update_count()
        self.save_selection()

    def update_count(self) -> None:
        count = sum(1 for var in self.vars.values() if var.get())
        self.count_var.set(f"已选 {count} 个")

    def current_selected_targets(self) -> list[str]:
        return [target for target, var in self.vars.items() if var.get()]

    def save_selection(self) -> None:
        name = self.profile_var.get() or self.config.active_profile
        if not name:
            return
        self.config.set_profile(name, self.current_selected_targets())
        try:
            self.config.save()
        except OSError:
            pass

    def _selected_entries(self) -> list[AppEntry]:
        selected: list[AppEntry] = []
        for entry in self.entries:
            var = self.vars.get(entry.target)
            if var is not None and var.get():
                selected.append(entry)
        return selected

    def launch_selected(self) -> None:
        self._launch_entries(self._selected_entries())

    def _launch_entries(self, selected: list[AppEntry], profile_name: str = "") -> None:
        if not selected:
            if profile_name:
                messagebox.showinfo(APP_TITLE, f"存档“{profile_name}”里没有可启动的应用。")
            else:
                messagebox.showinfo(APP_TITLE, "请先勾选要启动的应用。")
            return

        success = 0
        failures: list[str] = []
        for entry in selected:
            try:
                self._launch_entry(entry)
                success += 1
            except OSError as exc:
                failures.append(f"{entry.name}：{exc}")

        suffix = f"（存档：{profile_name}）" if profile_name else ""
        self.status_var.set(f"已启动 {success} 个应用{suffix}")
        if failures:
            messagebox.showwarning(
                "部分应用启动失败",
                "以下应用未能启动：\n" + "\n".join(failures[:10]),
            )

    @staticmethod
    def _launch_entry(entry: AppEntry) -> None:
        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        result = shell32.ShellExecuteW(
            None,
            "open",
            entry.target,
            entry.arguments or None,
            entry.working_dir or None,
            1,
        )
        if result is None or int(result) <= 32:
            raise OSError(f"ShellExecuteW 返回错误码 {result}")

    def on_close(self) -> None:
        self.save_selection()
        self.root.destroy()


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    enable_dpi_awareness()
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
