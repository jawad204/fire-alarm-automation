"""
The window your brother actually sees - a tkinter GUI wrapping the same
extract -> confirm -> write -> generate pipeline as run.py.

Build with:
    pyinstaller --onefile --windowed --add-data "logo.png;." gui_run.py

--windowed hides the console entirely, so only this window appears.

Nothing about the underlying pipeline changes: this file only replaces
input()/print() with widgets. extract_quotation.py, quotation_to_sheet.py
and make_requisition.py are untouched and still work standalone.
"""

import datetime
import pathlib
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from extract_quotation import all_pages, extract, save_json
from quotation_to_sheet import TAB, check, supply_lines, clean_qty, write_row
from make_requisition import build


def base_dir():
    """The folder this program lives in - the exe's own folder when frozen,
    or this script's folder otherwise. Never the current working directory,
    which can differ depending on how the program was launched."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


CONFIG_PATH = base_dir() / "config.txt"


def read_sheet_path():
    if not CONFIG_PATH.exists():
        return None
    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.lower().startswith("sheet_path"):
            _, _, value = line.partition("=")
            path = value.strip().strip('"')
            if path:
                return path
    return None


def write_sheet_path(path):
    CONFIG_PATH.write_text(f"sheet_path = {path}\n", encoding="utf-8")


# ---------------------------------------------------------------- styling

BG = "#f4f1ec"
PANEL = "#ffffff"
ACCENT = "#c55a11"
TEXT = "#2b2b2b"
MONO = ("Consolas", 10)
SANS = ("Segoe UI", 10)
SANS_BOLD = ("Segoe UI", 10, "bold")
SANS_TITLE = ("Segoe UI", 14, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fire Alarm Requisition Tool")
        self.geometry("640x560")
        self.configure(bg=BG)
        self.resizable(False, False)

        self.sheet_path = read_sheet_path()
        self.current_data = None
        self.current_pdf = None

        if not self.sheet_path or not pathlib.Path(self.sheet_path).exists():
            self.build_setup_screen()
        else:
            self.build_main_screen()

    # ------------------------------------------------------------- setup

    def build_setup_screen(self):
        for w in self.winfo_children():
            w.destroy()

        tk.Label(self, text="First-time setup", font=SANS_TITLE, bg=BG, fg=TEXT).pack(pady=(30, 6))
        tk.Label(
            self,
            text="Choose your Excel job sheet. This only needs to be done once.",
            font=SANS, bg=BG, fg=TEXT, wraplength=520, justify="center",
        ).pack(pady=(0, 20))

        self.path_var = tk.StringVar(value=self.sheet_path or "")
        entry = tk.Entry(self, textvariable=self.path_var, font=SANS, width=60)
        entry.pack(pady=6)

        def browse():
            path = filedialog.askopenfilename(
                title="Choose the job sheet",
                filetypes=[("Excel files", "*.xlsx")],
            )
            if path:
                self.path_var.set(path)

        tk.Button(self, text="Browse...", command=browse, font=SANS).pack(pady=6)

        def save():
            path = self.path_var.get().strip()
            if not path or not pathlib.Path(path).exists():
                messagebox.showerror("Not found", "That file doesn't exist. Pick your Excel sheet.")
                return
            write_sheet_path(path)
            self.sheet_path = path
            self.build_main_screen()

        tk.Button(
            self, text="Save and continue", command=save,
            font=SANS_BOLD, bg=ACCENT, fg="white", padx=16, pady=6,
        ).pack(pady=24)

    # -------------------------------------------------------------- main

    def build_main_screen(self):
        for w in self.winfo_children():
            w.destroy()

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 10))
        tk.Label(header, text="Fire Alarm Requisition Tool", font=SANS_TITLE, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            header, text=f"Sheet: {self.sheet_path}", font=("Segoe UI", 8), bg=BG, fg="#888",
        ).pack(anchor="w")

        self.choose_btn = tk.Button(
            self, text="Choose Quotation PDF...", command=self.choose_pdf,
            font=SANS_BOLD, bg=ACCENT, fg="white", padx=16, pady=8,
        )
        self.choose_btn.pack(pady=10)

        self.status_var = tk.StringVar(value="Pick a quotation PDF to begin.")
        tk.Label(self, textvariable=self.status_var, font=SANS, bg=BG, fg=TEXT).pack(pady=(0, 8))

        panel = tk.Frame(self, bg=PANEL, highlightbackground="#ccc", highlightthickness=1)
        panel.pack(padx=24, pady=8, fill="both", expand=True)
        self.result_text = tk.Text(panel, font=MONO, bg=PANEL, fg=TEXT, wrap="word", height=18, borderwidth=0)
        self.result_text.pack(padx=10, pady=10, fill="both", expand=True)
        self.result_text.configure(state="disabled")

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=14)
        self.confirm_btn = tk.Button(
            btn_row, text="Confirm and File", command=self.on_confirm,
            font=SANS_BOLD, bg="#2e8b57", fg="white", padx=16, pady=6, state="disabled",
        )
        self.confirm_btn.grid(row=0, column=0, padx=8)
        self.cancel_btn = tk.Button(
            btn_row, text="Cancel", command=self.on_cancel,
            font=SANS, padx=16, pady=6, state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, padx=8)

    def set_result_text(self, text):
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    # --------------------------------------------------------- pdf -> read

    def choose_pdf(self):
        path = filedialog.askopenfilename(title="Choose the quotation PDF", filetypes=[("PDF files", "*.pdf")])
        if not path:
            return

        self.current_pdf = path
        self.current_data = None
        self.choose_btn.configure(state="disabled")
        self.confirm_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.status_var.set(f"Reading {pathlib.Path(path).name} ...")
        self.set_result_text("")

        threading.Thread(target=self._read_pdf_thread, args=(path,), daemon=True).start()

    def _read_pdf_thread(self, path):
        try:
            pages = all_pages(path)
            data, usage = extract(path, pages)
            save_json(path, data)
        except Exception as err:                       # noqa: BLE001
            self.after(0, self._read_failed, str(err))
            return
        self.after(0, self._read_done, data)

    def _read_failed(self, message):
        self.status_var.set("Could not read this quotation.")
        self.set_result_text(f"Error:\n{message}\n\nTry a different file, or send this one to Jawad.")
        self.choose_btn.configure(state="normal")

    def _read_done(self, data):
        problems = check(data)
        if problems:
            self.status_var.set("This quotation could not be read reliably.")
            self.set_result_text("Problems found:\n  - " + "\n  - ".join(problems)
                                  + "\n\nNothing will be written. Please send this one to Jawad.")
            self.choose_btn.configure(state="normal")
            return

        self.current_data = data
        items = supply_lines(data.get("line_items"))

        lines = [
            f"Customer   {data.get('customer_name')}",
            f"Project    {data.get('project_name')}",
            f"Quotation  {data.get('quotation_ref')}",
            f"Value      {data.get('value')}",
            f"Payment    {data.get('payment_term')}",
            "",
            "Material requisition:",
        ]
        for n, item in enumerate(items, start=1):
            desc = str(item.get("description"))
            lines.append(f"  {n}.  {desc:<44} qty {clean_qty(item.get('qty'))}")

        self.set_result_text("\n".join(lines))
        self.status_var.set("Check this against the quotation, then confirm.")
        self.choose_btn.configure(state="normal")
        self.confirm_btn.configure(state="normal")
        self.cancel_btn.configure(state="normal")

    # ------------------------------------------------------------ confirm

    def on_cancel(self):
        self.current_data = None
        self.current_pdf = None
        self.set_result_text("")
        self.status_var.set("Cancelled. Pick a quotation PDF to begin.")
        self.confirm_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")

    def on_confirm(self):
        if not self.current_data:
            return
        self.confirm_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.choose_btn.configure(state="disabled")
        self.status_var.set("Writing...")

        threading.Thread(target=self._write_thread, daemon=True).start()

    def _write_thread(self):
        data = self.current_data
        today = datetime.date.today()
        try:
            row, job_no = write_row(data, self.sheet_path, self.sheet_path, TAB, date=today)

            req_path = base_dir() / "requisitions" / f"requisition_{job_no}.pdf"
            req_path.parent.mkdir(parents=True, exist_ok=True)
            build(data, job_no, req_path, date=today.strftime("%d/%m/%y"))
        except Exception as err:                       # noqa: BLE001
            self.after(0, self._write_failed, str(err))
            return
        self.after(0, self._write_done, row, job_no, req_path)

    def _write_failed(self, message):
        self.status_var.set("Something went wrong while writing.")
        self.set_result_text(f"Error:\n{message}")
        self.choose_btn.configure(state="normal")

    def _write_done(self, row, job_no, req_path):
        if row is None:
            self.status_var.set(f"Already filed as job {job_no}. Sheet not touched.")
        else:
            self.status_var.set(f"Written to row {row}, job {job_no}.")
        self.set_result_text(
            self.result_text.get("1.0", "end").strip()
            + f"\n\nRequisition saved:\n  {req_path}"
        )
        self.choose_btn.configure(state="normal")
        self.current_data = None


if __name__ == "__main__":
    App().mainloop()
