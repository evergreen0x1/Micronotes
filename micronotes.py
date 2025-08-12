import tkinter as tk
from tkinter import ttk, Menu, messagebox
from datetime import datetime
from pathlib import Path
import json, uuid, platform
from typing import Optional, Dict, Any

APP_NAME = "micronotes"
TITLE = "Micronotes"
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_NOTES = 10000

LIGHT = {
    "bg": "#F2F2F2",
    "surface": "#FFFFFF",
    "text": "#0A0A0A",
    "text_muted": "#666666",
    "border": "#D1D1D1",
    "accent": "#0A84FF",
    "header": "#F5F5F7",
}

DARK = {
    "bg": "#1C1C1E",
    "surface": "#2C2C2E",
    "text": "#F2F2F7",
    "text_muted": "#98989E",
    "border": "#3A3A3C",
    "accent": "#0A84FF",
    "header": "#2C2C2E",
}

def app_data_path() -> Path:
    home = Path.home()
    base = home / ("Library/Application Support/" + APP_NAME if platform.system()=="Darwin"
                   else f".{APP_NAME.lower()}")
    base.mkdir(parents=True, exist_ok=True)
    return base / "notes.json"

class MicroNotes:
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title(TITLE)
        self.file_path = app_data_path()
        self.editing_id: Optional[str] = None
        self.notes = self.load_notes()

        # ——— базовый стиль ttk
        self.style = ttk.Style()
        # используем 'clam', чтобы кастомы работали одинаково на mac
        try: self.style.theme_use("clam")
        except tk.TclError: pass

        self.theme = "light"   # стартуем со светлой
        self.palette = LIGHT

        # ——— корневой контейнер
        self.root_frame = ttk.Frame(master, padding=12)
        self.root_frame.grid(row=0, column=0, sticky="nsew")
        master.grid_rowconfigure(0, weight=1)
        master.grid_columnconfigure(0, weight=1)

        # ——— поля
        self.lbl_subject = ttk.Label(self.root_frame, text="Subject")
        self.entry_subject = ttk.Entry(self.root_frame, style="Mic.TEntry")

        self.lbl_info = ttk.Label(self.root_frame, text="Additional info")
        self.entry_info = ttk.Entry(self.root_frame, style="Mic.TEntry")

        self.lbl_desc = ttk.Label(self.root_frame, text="Description")
        # Text не ttk — красим вручную при смене темы
        self.entry_desc = tk.Text(self.root_frame, height=4, wrap="word", borderwidth=0, padx=6, pady=6)

        # ——— таблица
        cols = ("Time", "Subject", "Info", "Description")
        headers = ("Date & Time", "Subject", "Additional Info", "Description")
        self.tree = ttk.Treeview(self.root_frame, columns=cols, show="headings", height=12, style="Mic.Treeview")
        for c, h in zip(cols, headers):
            self.tree.heading(c, text=h, command=lambda k=c: self.sort_by(k))
            self.tree.column(c, width=160 if c!="Description" else 420, anchor="w")
        self.tree.bind("<Button-3>", self._tree_menu)
        self.tree.bind("<Double-1>", self.load_into_form)

        # ——— кнопки
        self.btn_save = ttk.Button(self.root_frame, text="Save (⌘S)", command=self.save_note, style="Mic.TButton")
        self.btn_del  = ttk.Button(self.root_frame, text="Delete (Del)", command=self.delete_selected, style="Mic.TButton")
        self.btn_theme = ttk.Button(self.root_frame, text="Toggle Theme", command=self.toggle_theme, style="Mic.TButton")

        # ——— сетка
        g = self.root_frame
        self.lbl_subject.grid(row=0, column=0, sticky="w")
        self.lbl_info.grid(   row=0, column=1, sticky="w", padx=(12,0))

        self.entry_subject.grid(row=1, column=0, sticky="ew", pady=(4,12))
        self.entry_info.grid(   row=1, column=1, sticky="ew", padx=(12,0), pady=(4,12))

        self.lbl_desc.grid(row=2, column=0, columnspan=2, sticky="w")
        self.entry_desc.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4,12))

        self.tree.grid(row=4, column=0, columnspan=2, sticky="nsew")

        self.btn_save.grid(row=5, column=0, sticky="ew", pady=(12,0))
        self.btn_del.grid( row=5, column=1, sticky="ew", padx=(12,0), pady=(12,0))
        self.btn_theme.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8,0))

        g.grid_columnconfigure(0, weight=1)
        g.grid_columnconfigure(1, weight=1)
        g.grid_rowconfigure(4, weight=1)

        # хоткеи
        master.bind_all("<Command-s>", lambda e: self.save_note())
        master.bind_all("<Command-S>", lambda e: self.save_note())
        master.bind_all("<Delete>", lambda e: self.delete_selected())
        master.bind_all("<BackSpace>", lambda e: self.delete_selected())

        self.apply_theme()
        self.refresh()

    # ——— темы
    def apply_theme(self):
        p = self.palette

        # фон окна и фрейма
        self.master.configure(bg=p["bg"])
        self.root_frame.configure(style="Mic.TFrame")
        self.style.configure("Mic.TFrame", background=p["bg"])

        # Label
        self.style.configure("Mic.TLabel", background=p["bg"], foreground=p["text"])
        for lbl in (self.lbl_subject, self.lbl_info, self.lbl_desc):
            lbl.configure(style="Mic.TLabel")

        # Entry
        self.style.configure("Mic.TEntry",
                             fieldbackground=p["surface"],
                             foreground=p["text"],
                             bordercolor=p["border"],
                             lightcolor=p["border"],
                             darkcolor=p["border"])
        self.style.map("Mic.TEntry",
                       fieldbackground=[("focus", p["surface"])],
                       foreground=[("disabled", p["text_muted"])],
                       bordercolor=[("focus", p["accent"])])

        # Button
        self.style.configure("Mic.TButton",
                             background=p["surface"],
                             foreground=p["text"],
                             bordercolor=p["border"])
        self.style.map("Mic.TButton",
                       background=[("active", p["border"])],
                       foreground=[("disabled", p["text_muted"])])

        # Text (ручная покраска)
        self.entry_desc.configure(bg=p["surface"], fg=p["text"],
                                  insertbackground=p["text"], highlightthickness=1,
                                  highlightbackground=p["border"], highlightcolor=p["accent"])

        # Treeview
        self.style.configure("Mic.Treeview",
                             background=p["surface"],
                             fieldbackground=p["surface"],
                             foreground=p["text"],
                             bordercolor=p["border"],
                             rowheight=22)
        self.style.map("Mic.Treeview",
                       background=[("selected", p["accent"])],
                       foreground=[("selected", "#FFFFFF")])
        self.style.configure("Mic.Treeview.Heading",
                             background=p["header"],
                             foreground=p["text"],
                             bordercolor=p["border"])

        # контекстные меню будут системные — не красим

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.palette = DARK if self.theme == "dark" else LIGHT
        self.apply_theme()

    # ——— данные
    @staticmethod
    def now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def load_notes(self) -> list:
        p = self.file_path
        if not p.exists():
            return []
        try:
            if p.stat().st_size > MAX_FILE_SIZE:
                return []
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            out = []
            for n in data[:MAX_NOTES]:
                if not isinstance(n, dict):
                    continue
                n.setdefault("id", uuid.uuid4().hex)
                n.setdefault("Time", self.now())
                n.setdefault("Subject", ""); n["Subject"] = str(n["Subject"])[:200]
                n.setdefault("Info", "");    n["Info"] = str(n["Info"])[:200]
                n.setdefault("Description", ""); n["Description"] = str(n["Description"])[:2000]
                out.append(n)
            return out
        except Exception:
            return []

    def save_all(self) -> bool:
        try:
            tmp = self.file_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.notes, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.file_path)
            return True
        except Exception:
            return False

    # ——— таблица / CRUD
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for n in sorted(self.notes, key=lambda x: x.get("Time",""), reverse=True):
            self.tree.insert("", "end", iid=n["id"],
                             values=(n["Time"], n["Subject"], n["Info"], n["Description"]))

    def selected_id(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def find_by_id(self, nid: str) -> tuple[Optional[int], Optional[Dict[str, Any]]]:
        for i, n in enumerate(self.notes):
            if n.get("id") == nid:
                return i, n
        return None, None

    def _ctx_menu(self, widget):
        m = Menu(widget, tearoff=0)
        m.add_command(label="Copy", command=lambda: self._copy(widget))
        m.add_command(label="Paste", command=lambda: self._paste(widget))
        widget.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))

    def _tree_menu(self, e):
        m = Menu(self.master, tearoff=0)
        m.add_command(label="Copy row", command=self.copy_row)
        m.add_command(label="Delete", command=self.delete_selected)
        m.tk_popup(e.x_root, e.y_root)

    def _copy(self, w):
        try:
            s = w.selection_get()
            self.master.clipboard_clear()
            self.master.clipboard_append(s)
        except tk.TclError:
            pass

    def _paste(self, w):
        try:
            t = self.master.clipboard_get()
            if isinstance(t, str) and len(t) < 10000:
                w.insert(tk.INSERT, t)
        except tk.TclError:
            pass

    def save_note(self):
        subject = self.entry_subject.get().strip()
        info = self.entry_info.get().strip()
        desc = self.entry_desc.get("1.0", "end").strip()
        if not any([subject, info, desc]):
            return
        if len(subject)>200 or len(info)>200 or len(desc)>2000:
            messagebox.showwarning("Warning", "Too long. Subject/Info ≤ 200, Description ≤ 2000.")
            return
        now = self.now()
        if self.editing_id:
            idx, n = self.find_by_id(self.editing_id)
            if n:
                n.update({"Time": now, "Subject": subject, "Info": info, "Description": desc})
            self.editing_id = None
        else:
            if len(self.notes) >= MAX_NOTES:
                self.notes.pop(0)
            self.notes.append({
                "id": uuid.uuid4().hex,
                "Time": now,
                "Subject": subject,
                "Info": info,
                "Description": desc
            })
        if self.save_all():
            self.entry_subject.delete(0, tk.END)
            self.entry_info.delete(0, tk.END)
            self.entry_desc.delete("1.0", "end")
            self.refresh()

    def delete_selected(self):
        nid = self.selected_id()
        if not nid: return
        idx, _ = self.find_by_id(nid)
        if idx is not None:
            del self.notes[idx]
            if self.save_all():
                self.refresh()

    def copy_row(self):
        nid = self.selected_id()
        if not nid: return
        _, n = self.find_by_id(nid)
        if n:
            s = f"{n['Time']}+{n['Subject']}+{n['Info']}+{n['Description']}"
            self.master.clipboard_clear()
            self.master.clipboard_append(s)

    def load_into_form(self, _=None):
        nid = self.selected_id()
        if not nid: return
        _, n = self.find_by_id(nid)
        if not n: return
        self.editing_id = nid
        self.entry_subject.delete(0, tk.END); self.entry_subject.insert(0, n["Subject"])
        self.entry_info.delete(0, tk.END);    self.entry_info.insert(0, n["Info"])
        self.entry_desc.delete("1.0", "end"); self.entry_desc.insert("1.0", n["Description"])

if __name__ == "__main__":
    root = tk.Tk()
    root.minsize(900, 540)
    app = MicroNotes(root)
    root.mainloop()