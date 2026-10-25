#!/usr/bin/env python3
"""ShopifyCsvFix desktop shell (tkinter). Pick a product CSV -> audit, fix & re-check."""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shopify_fix import run_shopifyfix


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ShopifyCsvFix — Product CSV Audit, Fix & Re-Check")
        self.geometry("680x520")
        self.src = tk.StringVar()
        tk.Label(self, text="Shopify product CSV file:").pack(anchor="w", padx=12, pady=(12, 2))
        row = tk.Frame(self)
        row.pack(fill="x", padx=12)
        tk.Entry(row, textvariable=self.src).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse…", command=self.pick).pack(side="left", padx=6)
        self.btn = tk.Button(self, text="Audit, Fix & Re-Check", command=self.run, height=2)
        self.btn.pack(pady=12)
        self.log = scrolledtext.ScrolledText(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.write("ShopifyCsvFix checks your product CSV the way Shopify's importer\n"
                   "sees it, repairs the mechanical errors, then re-checks the file.\n"
                   "Everything runs locally — your catalogue never leaves this computer.\n")

    def write(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    def pick(self):
        p = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if p:
            self.src.set(p)

    def run(self):
        src = self.src.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("ShopifyCsvFix", "Choose a CSV file first.")
            return
        self.btn.config(state="disabled")
        threading.Thread(target=self._work, args=(src,), daemon=True).start()

    def _work(self, src):
        try:
            outdir = os.path.join(os.path.dirname(src), "shopifycsvfix_output")
            s = run_shopifyfix(src, outdir)
            self.write(f"\nDone. Rows: {s['rows']} · problems found: {s['found'] + s['fixed']} · "
                       f"auto-fixed: {s['fixed']} · remaining: {s['remaining']} "
                       f"({s['errors_remaining']} blocking errors)\n"
                       f"Repaired CSV: {s['fixed_path']}\nReport: {s['report_path']}\n")
            self.write("Verdict: NOT READY — see the report.\n" if s["errors_remaining"]
                       else "Verdict: PASS — no blocking errors remain.\n")
        except Exception as e:
            self.write(f"\nError: {e}\n")
        finally:
            self.btn.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
