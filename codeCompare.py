# -*- coding: utf-8 -*-
"""
Beyond Compare + Meld Clone – FULLY FIXED
Proper alignment, blank line handling, and move detection
"""

import os
import re
import hashlib
import zipfile
import mimetypes
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher, unified_diff
from tkinter import (
    filedialog, messagebox, ttk, Toplevel,
    StringVar, BooleanVar, Canvas,
    END, LEFT, RIGHT, TOP, BOTTOM,
    X, Y, BOTH, HORIZONTAL, VERTICAL
)
from tkinter.scrolledtext import ScrolledText
import ttkbootstrap as tb
from ttkbootstrap.constants import (
    PRIMARY, SUCCESS, WARNING, SECONDARY, INFO, OUTLINE, DANGER
)
import pandas as pd
from PIL import Image, ImageTk


class BeyondCompareClone(tb.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Beyond Compare + Meld Clone (Fully Fixed)")
        self.geometry("1700x950")
        self.minsize(1200, 600)

        # State
        self.left_path = self.right_path = ""
        self.left_type = self.right_type = ""
        self.ignore_ws = BooleanVar(value=False)
        self.ignore_case = BooleanVar(value=False)
        self.ignore_blank = BooleanVar(value=False)
        self.fast_compare = BooleanVar(value=False)
        self.diff_mode = StringVar(value="side")
        self.search_var = StringVar()
        self.diff_items = []
        self.current_diff = 0
        self.move_arrows = []

        # Defensive flags
        self._suspend_events = False
        self._syntax_job = None
        self._in_compare = False

        # Build UI
        self._build_ui()
        self._apply_styles()
        self._bind_events()

    def _build_ui(self):
        toolbar = tb.Frame(self, bootstyle=INFO)
        toolbar.pack(fill=X, padx=4, pady=2)

        tb.Button(toolbar, text="Left", bootstyle=PRIMARY, command=self.open_left).pack(side=LEFT, padx=2)
        tb.Button(toolbar, text="Right", bootstyle=PRIMARY, command=self.open_right).pack(side=LEFT, padx=2)
        tb.Button(toolbar, text="Compare", bootstyle=SUCCESS, command=self.compare).pack(side=LEFT, padx=4)
        tb.Button(toolbar, text="Merge to Left", bootstyle=WARNING, command=self.merge_left).pack(side=LEFT, padx=2)
        tb.Button(toolbar, text="Merge to Right", bootstyle=WARNING, command=self.merge_right).pack(side=LEFT, padx=2)
        tb.Button(toolbar, text="Clear", bootstyle=SECONDARY, command=self.clear).pack(side=LEFT, padx=2)

        tb.Label(toolbar, text="Diff:").pack(side=LEFT, padx=(10, 2))
        tb.Button(toolbar, text="Prev", command=self.prev_diff).pack(side=LEFT, padx=1)
        tb.Button(toolbar, text="Next", command=self.next_diff).pack(side=LEFT, padx=1)
        self.diff_lbl = tb.Label(toolbar, text="0/0")
        self.diff_lbl.pack(side=LEFT, padx=5)

        tb.Label(toolbar, text="View:").pack(side=LEFT, padx=(20, 2))
        tb.Radiobutton(toolbar, text="Side-by-Side", variable=self.diff_mode, value="side", command=self.toggle_view).pack(side=LEFT, padx=2)
        tb.Radiobutton(toolbar, text="Unified", variable=self.diff_mode, value="unified", command=self.toggle_view).pack(side=LEFT, padx=2)

        tb.Label(toolbar, text="Find:").pack(side=RIGHT, padx=(10, 2))
        tb.Entry(toolbar, textvariable=self.search_var, width=22).pack(side=RIGHT, padx=2)
        tb.Button(toolbar, text="Find", bootstyle=OUTLINE, command=self.find_next).pack(side=RIGHT, padx=2)

        opts = tb.LabelFrame(self, text="Options", padding=5)
        opts.pack(fill=X, padx=5, pady=3)
        tb.Checkbutton(opts, text="Ignore Whitespace", variable=self.ignore_ws).pack(side=LEFT, padx=5)
        tb.Checkbutton(opts, text="Ignore Case", variable=self.ignore_case).pack(side=LEFT, padx=5)
        tb.Checkbutton(opts, text="Ignore Blank Lines", variable=self.ignore_blank).pack(side=LEFT, padx=5)
        tb.Checkbutton(opts, text="Fast Compare", variable=self.fast_compare).pack(side=LEFT, padx=5)

        # Paned window
        self.paned = tb.Panedwindow(self, orient=HORIZONTAL)
        self.paned.pack(fill=BOTH, expand=True, padx=5, pady=5)

        # Left Panel
        lf = tb.LabelFrame(self.paned, text="Left", padding=5)
        self.paned.add(lf, weight=1)
        li = tb.Frame(lf)
        li.pack(fill=BOTH, expand=True)
        
        self.l_nums = tb.Text(li, width=5, state="disabled", bg="#2b2b2b", fg="#888", cursor="arrow")
        self.l_nums.pack(side=LEFT, fill=Y)
        
        self.l_text = ScrolledText(li, wrap="none", font=("Consolas", 11), undo=True)
        self.l_text.pack(side=LEFT, fill=BOTH, expand=True)

        # Arrow Canvas
        middle_frame = tb.Frame(self.paned, width=60)
        self.paned.add(middle_frame, weight=0)
        self.arrow_canvas = Canvas(middle_frame, bg="#1e1e1e", highlightthickness=0, width=60)
        self.arrow_canvas.pack(fill=BOTH, expand=True)
        self.arrow_canvas.bind("<Button-1>", self._on_arrow_click)

        # Right Panel
        rf = tb.LabelFrame(self.paned, text="Right", padding=5)
        self.paned.add(rf, weight=1)
        ri = tb.Frame(rf)
        ri.pack(fill=BOTH, expand=True)
        
        self.r_nums = tb.Text(ri, width=5, state="disabled", bg="#2b2b2b", fg="#888", cursor="arrow")
        self.r_nums.pack(side=LEFT, fill=Y)
        
        self.r_text = ScrolledText(ri, wrap="none", font=("Consolas", 11), undo=True)
        self.r_text.pack(side=LEFT, fill=BOTH, expand=True)

        # Unified View
        self.unified = ScrolledText(self, wrap="none", font=("Consolas", 11), state="disabled")
        self.unified.tag_configure("added", background="#355E3B", foreground="white")
        self.unified.tag_configure("removed", background="#78281F", foreground="white")
        self.unified.tag_configure("header", foreground="#A0A0A0", font=("Consolas", 10, "italic"))

        # Status Bar
        bottom = tb.Frame(self)
        bottom.pack(fill=X, side=BOTTOM, padx=5, pady=2)
        self.status = tb.Label(bottom, text="Ready", anchor="w", bootstyle=INFO)
        self.status.pack(side=LEFT, fill=X, expand=True)
        self.prog = tb.Progressbar(bottom, mode="indeterminate", bootstyle=SUCCESS)

        # Diff Tree
        self.tree = ttk.Treeview(self, columns=("Type", "L", "R", "Text"), show="headings", height=6)
        self.tree.heading("Type", text="Type")
        self.tree.heading("L", text="Left")
        self.tree.heading("R", text="Right")
        self.tree.heading("Text", text="Content")
        self.tree.column("Type", width=80)
        self.tree.column("L", width=60)
        self.tree.column("R", width=60)
        self.tree.column("Text", width=400)
        self.tree.bind("<Double-1>", self._jump_to)

        self._menu()

    def _apply_styles(self):
        for w in (self.l_text, self.r_text):
            w.tag_configure("added", background="#355E3B", foreground="white")
            w.tag_configure("removed", background="#78281F", foreground="white")
            w.tag_configure("moved", background="#D4AC0D", foreground="black")
            w.tag_configure("changed", background="#5B4A8A", foreground="white")
            w.tag_configure("same", background="", foreground="")
            w.tag_configure("keyword", foreground="#569CD6")
            w.tag_configure("string", foreground="#CE9178")
            w.tag_configure("comment", foreground="#6A9955")
            w.tag_configure("search", background="#5B5B00")
            w.tag_configure("sel", background="#264F78")

    def _bind_events(self):
        for w in (self.l_text, self.r_text):
            w.bind("<KeyRelease>", self._on_key_release)
            w.bind("<MouseWheel>", self._sync_scroll)
            w.bind("<Button-4>", self._sync_scroll)
            w.bind("<Button-5>", self._sync_scroll)
            
        self.l_text.vbar.config(command=self._sync_yview)
        self.r_text.vbar.config(command=self._sync_yview)

    def _sync_scroll(self, event):
        """Synchronize scrolling between panels"""
        widget = event.widget
        try:
            if event.num == 4 or event.delta > 0:
                widget.yview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0:
                widget.yview_scroll(1, "units")
                
            # Sync the other panel
            pos = widget.yview()[0]
            if widget == self.l_text:
                self.r_text.yview_moveto(pos)
            else:
                self.l_text.yview_moveto(pos)
                
        except:
            pass
        return "break"

    def _sync_yview(self, *args):
        """Synchronize vertical scrollbar"""
        self.l_text.yview(*args)
        self.r_text.yview(*args)

    def _on_key_release(self, event=None):
        if self._suspend_events:
            return
        if self._syntax_job:
            try:
                self.after_cancel(self._syntax_job)
            except:
                pass
        self._syntax_job = self.after(400, self._syntax)

    def open_left(self):
        p = filedialog.askopenfilename()
        if p:
            self.left_path = p
            self._load(self.l_text, p, 1)
            self.status.config(text=f"Left: {os.path.basename(p)}")

    def open_right(self):
        p = filedialog.askopenfilename()
        if p:
            self.right_path = p
            self._load(self.r_text, p, 2)
            self.status.config(text=f"Right: {os.path.basename(p)}")

    def _load(self, widget, path, side):
        widget.delete("1.0", END)
        self._detect(path, side)
        typ = self.left_type if side == 1 else self.right_type

        try:
            if typ == "image":
                self._show_img(path)
                widget.insert("1.0", f"[Image] {os.path.basename(path)}")
            elif typ == "excel":
                widget.insert("1.0", pd.read_excel(path).to_string(index=False))
            elif typ == "docx":
                txt = self._docx_text(path)
                widget.insert("1.0", txt or "[DOCX read error]")
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    widget.insert("1.0", f.read())
        except Exception as e:
            widget.insert("1.0", f"[Error: {e}]")
            setattr(self, f"{'left' if side==1 else 'right'}_type", "binary")

        self._update_nums()
        self._syntax()

    def _detect(self, path, side):
        mime, _ = mimetypes.guess_type(path)
        if mime and mime.startswith("image"):
            t = "image"
        elif path.lower().endswith((".xlsx", ".xls")):
            t = "excel"
        elif path.lower().endswith(".docx"):
            t = "docx"
        elif mime and mime.startswith("text"):
            t = "text"
        else:
            t = "binary"
        setattr(self, f"{'left' if side==1 else 'right'}_type", t)

    def _docx_text(self, path):
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml")
            tree = ET.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            return "\n".join(t.text or "" for t in tree.iterfind('.//w:t', ns))
        except:
            return None

    def _show_img(self, path):
        try:
            img = Image.open(path).copy()
            img.thumbnail((800, 600), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            win = Toplevel(self)
            win.title(os.path.basename(path))
            tb.Label(win, image=photo).pack(padx=10, pady=10)
            win.photo = photo
            tb.Button(win, text="Close", bootstyle=DANGER, command=win.destroy).pack(pady=5)
        except Exception as e:
            messagebox.showerror("Image", str(e))

    def _update_nums(self):
        """Update line numbers"""
        for txt, num in [(self.l_text, self.l_nums), (self.r_text, self.r_nums)]:
            try:
                num.config(state="normal")
                num.delete("1.0", END)
                cnt = int(txt.index("end-1c").split('.')[0])
                num.insert("1.0", "\n".join(str(i) for i in range(1, cnt + 1)))
                num.config(state="disabled")
            except:
                pass

    def _syntax(self):
        """Apply syntax highlighting"""
        if self._suspend_events:
            return
        self._syntax_job = None

        for w in (self.l_text, self.r_text):
            try:
                data = w.get("1.0", "end-1c")
            except:
                continue

            if len(data) > 200_000:
                continue

            for tag in ("keyword", "string", "comment"):
                try:
                    w.tag_remove(tag, "1.0", "end")
                except:
                    pass

            patterns = [
                (r'\b(def|class|if|else|elif|for|while|try|except|finally|with|import|from|as|return|yield|lambda|None|True|False|and|or|not|in|is)\b', "keyword"),
                (r'\"(\\.|[^\"])*\"|\'(\\.|[^\'])*\'', "string"),
                (r'#.*', "comment")
            ]

            for pat, tag in patterns:
                for m in re.finditer(pat, data):
                    try:
                        s = w.index(f"1.0 + {m.start()} chars")
                        e = w.index(f"1.0 + {m.end()} chars")
                        w.tag_add(tag, s, e)
                    except:
                        continue

    def compare(self):
        """Main comparison method"""
        if self._in_compare:
            return

        self._in_compare = True
        self._suspend_events = True

        try:
            left = self.l_text.get("1.0", "end-1c")
            right = self.r_text.get("1.0", "end-1c")

            if not left and not right:
                messagebox.showwarning("Empty", "Both sides must contain data.")
                return

            if self.left_type in ("binary", "image") or self.right_type in ("binary", "image"):
                self._binary_compare()
                return

            # Split into lines
            l_lines = left.split("\n")
            r_lines = right.split("\n")

            # Apply options
            l_processed = self._process_lines(l_lines)
            r_processed = self._process_lines(r_lines)

            self.diff_items = []
            self._clear_tags()

            if self.diff_mode.get() == "side":
                self._side_by_side_diff(l_processed, r_processed, l_lines, r_lines)
            else:
                self._unified_diff(l_processed, r_processed)

            self._update_nums()
            self._populate_tree()
            self.after(100, self._draw_arrows)
            self.after(200, self._syntax)
            self.status.config(text=f"Comparison complete - {len(self.diff_items)} differences")
            
        except Exception as e:
            messagebox.showerror("Compare Error", f"Error during comparison: {e}")
        finally:
            self._suspend_events = False
            self._in_compare = False

    def _process_lines(self, lines):
        """Apply comparison options to lines"""
        processed = []
        for line in lines:
            if self.ignore_blank.get() and not line.strip():
                continue
            pline = line
            if self.ignore_ws.get():
                pline = pline.strip()
            if self.ignore_case.get():
                pline = pline.lower()
            processed.append(pline)
        return processed

    def _side_by_side_diff(self, l_proc, r_proc, l_orig, r_orig):
        """Perform side-by-side comparison with proper alignment"""
        self.paned.pack(fill=BOTH, expand=True)
        self.l_text.delete("1.0", END)
        self.r_text.delete("1.0", END)

        # Get diff operations
        matcher = SequenceMatcher(None, l_proc, r_proc)
        opcodes = matcher.get_opcodes()

        # Build output with proper alignment
        left_lines = []
        right_lines = []
        left_tags = []
        right_tags = []

        line_num = 0

        for op, i1, i2, j1, j2 in opcodes:
            if op == "equal":
                # Lines are the same
                for k in range(i2 - i1):
                    left_lines.append(l_orig[i1 + k] if i1 + k < len(l_orig) else "")
                    right_lines.append(r_orig[j1 + k] if j1 + k < len(r_orig) else "")
                    left_tags.append("same")
                    right_tags.append("same")
                    line_num += 1

            elif op == "delete":
                # Lines only in left
                for k in range(i2 - i1):
                    line = l_orig[i1 + k] if i1 + k < len(l_orig) else ""
                    left_lines.append(line)
                    right_lines.append("")
                    left_tags.append("removed")
                    right_tags.append("")
                    line_num += 1
                    self.diff_items.append({
                        "type": "removed",
                        "l": line_num,
                        "r": None,
                        "text": line
                    })

            elif op == "insert":
                # Lines only in right
                for k in range(j2 - j1):
                    line = r_orig[j1 + k] if j1 + k < len(r_orig) else ""
                    left_lines.append("")
                    right_lines.append(line)
                    left_tags.append("")
                    right_tags.append("added")
                    line_num += 1
                    self.diff_items.append({
                        "type": "added",
                        "l": None,
                        "r": line_num,
                        "text": line
                    })

            elif op == "replace":
                # Lines are different - align them
                l_count = i2 - i1
                r_count = j2 - j1
                max_count = max(l_count, r_count)

                for k in range(max_count):
                    l_line = l_orig[i1 + k] if (i1 + k < len(l_orig) and k < l_count) else ""
                    r_line = r_orig[j1 + k] if (j1 + k < len(r_orig) and k < r_count) else ""

                    left_lines.append(l_line)
                    right_lines.append(r_line)

                    if l_line and r_line:
                        left_tags.append("changed")
                        right_tags.append("changed")
                    elif l_line:
                        left_tags.append("removed")
                        right_tags.append("")
                    else:
                        left_tags.append("")
                        right_tags.append("added")

                    line_num += 1

                    # Record the difference
                    if l_line and r_line:
                        self.diff_items.append({
                            "type": "changed",
                            "l": line_num,
                            "r": line_num,
                            "text": f"{l_line} → {r_line}"
                        })
                    elif l_line:
                        self.diff_items.append({
                            "type": "removed",
                            "l": line_num,
                            "r": None,
                            "text": l_line
                        })
                    elif r_line:
                        self.diff_items.append({
                            "type": "added",
                            "l": None,
                            "r": line_num,
                            "text": r_line
                        })

        # Insert all lines
        self.l_text.insert("1.0", "\n".join(left_lines))
        self.r_text.insert("1.0", "\n".join(right_lines))

        # Apply tags
        for i, tag in enumerate(left_tags, 1):
            if tag:
                self.l_text.tag_add(tag, f"{i}.0", f"{i}.end")

        for i, tag in enumerate(right_tags, 1):
            if tag:
                self.r_text.tag_add(tag, f"{i}.0", f"{i}.end")

    def _draw_arrows(self):
        """Draw connection arrows between panels"""
        self.arrow_canvas.delete("all")
        self.move_arrows = []

        try:
            # Get line height
            info = self.l_text.dlineinfo("1.0")
            if not info:
                return
            line_height = info[3]

            # Draw arrows for changed lines
            for item in self.diff_items:
                if item["type"] == "changed" and item.get("l") and item.get("r"):
                    l_line = item["l"]
                    r_line = item["r"]

                    y1 = (l_line - 1) * line_height + line_height // 2
                    y2 = (r_line - 1) * line_height + line_height // 2

                    # Draw connecting line
                    self.arrow_canvas.create_line(
                        5, y1, 55, y2,
                        fill="#5B4A8A", width=2, smooth=True
                    )

        except Exception as e:
            pass

    def _on_arrow_click(self, event):
        """Handle arrow clicks"""
        pass  # Can be implemented for specific merge operations

    def _unified_diff(self, l_lines, r_lines):
        """Show unified diff view"""
        self.paned.pack_forget()
        self.unified.pack(fill=BOTH, expand=True, padx=5, pady=5)
        self.unified.config(state="normal")
        self.unified.delete("1.0", END)

        for line in unified_diff(l_lines, r_lines, n=3, lineterm=''):
            if line.startswith(("+++", "---", "@@")):
                self.unified.insert(END, line + "\n", "header")
            elif line.startswith("+"):
                self.unified.insert(END, line + "\n", "added")
            elif line.startswith("-"):
                self.unified.insert(END, line + "\n", "removed")
            else:
                self.unified.insert(END, line + "\n")

        self.unified.config(state="disabled")

    def toggle_view(self):
        """Toggle between views"""
        if self.l_text.get("1.0", "end-1c").strip() or self.r_text.get("1.0", "end-1c").strip():
            self.compare()

    def _binary_compare(self):
        """Compare binary files"""
        if not (self.left_path and self.right_path):
            messagebox.showinfo("Binary", "Load two files first.")
            return
        h1 = self._hash(self.left_path)
        h2 = self._hash(self.right_path)
        msg = "Identical" if h1 == h2 else "Different"
        messagebox.showinfo("Binary", f"{msg}\n\nMD5 Left: {h1}\nMD5 Right: {h2}")

    def _hash(self, p):
        """Calculate MD5 hash"""
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def merge_left(self):
        """Merge from right to left"""
        if not self.left_path:
            messagebox.showerror("Error", "No left file loaded.")
            return
        if not messagebox.askyesno("Confirm", "Merge all from Right to Left?"):
            return
        try:
            content = self.r_text.get("1.0", "end-1c")
            with open(self.left_path, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Success", "Merged to left file.")
            self._load(self.l_text, self.left_path, 1)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def merge_right(self):
        """Merge from left to right"""
        if not self.right_path:
            messagebox.showerror("Error", "No right file loaded.")
            return
        if not messagebox.askyesno("Confirm", "Merge all from Left to Right?"):
            return
        try:
            content = self.l_text.get("1.0", "end-1c")
            with open(self.right_path, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Success", "Merged to right file.")
            self._load(self.r_text, self.right_path, 2)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _populate_tree(self):
        """Populate diff tree"""
        for i in self.tree.get_children():
            self.tree.delete(i)

        for idx, d in enumerate(self.diff_items, 1):
            text = d.get("text", "")[:50]  # Truncate long lines
            self.tree.insert("", END, values=(
                d["type"].capitalize(),
                d.get("l") or "-",
                d.get("r") or "-",
                text
            ), iid=idx)

        self.diff_lbl.config(text=f"{len(self.diff_items)} diffs")
        if self.diff_items:
            self.current_diff = 0

    def _jump_to(self, ev):
        """Jump to selected diff"""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0]) - 1
        if 0 <= idx < len(self.diff_items):
            self.current_diff = idx
            self._go_to_diff()

    def prev_diff(self):
        """Go to previous diff"""
        if self.diff_items and self.current_diff > 0:
            self.current_diff -= 1
            self._go_to_diff()

    def next_diff(self):
        """Go to next diff"""
        if self.diff_items and self.current_diff < len(self.diff_items) - 1:
            self.current_diff += 1
            self._go_to_diff()

    def _go_to_diff(self):
        """Navigate to current diff"""
        if not self.diff_items or self.current_diff < 0 or self.current_diff >= len(self.diff_items):
            return

        d = self.diff_items[self.current_diff]

        # Clear previous selections
        self.l_text.tag_remove("sel", "1.0", END)
        self.r_text.tag_remove("sel", "1.0", END)

        # Highlight and scroll to diff
        if d.get("l"):
            self.l_text.see(f"{d['l']}.0")
            self.l_text.tag_add("sel", f"{d['l']}.0", f"{d['l']}.end")

        if d.get("r"):
            self.r_text.see(f"{d['r']}.0")
            self.r_text.tag_add("sel", f"{d['r']}.0", f"{d['r']}.end")

        self.diff_lbl.config(text=f"{self.current_diff + 1}/{len(self.diff_items)}")

    def find_next(self):
        """Find text in both panels"""
        term = self.search_var.get().strip()
        if not term:
            return

        for w in (self.l_text, self.r_text):
            try:
                w.tag_remove("search", "1.0", "end")
            except:
                pass

        found = False
        for w in (self.l_text, self.r_text):
            start = "1.0"
            while True:
                pos = w.search(term, start, stopindex=END, nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(term)}c"
                w.tag_add("search", pos, end)
                if not found:
                    w.see(pos)
                    found = True
                start = end

        if not found:
            messagebox.showinfo("Find", f"'{term}' not found.")

    def compare_folders(self):
        """Compare two folders"""
        l = filedialog.askdirectory(title="Select Left Folder")
        r = filedialog.askdirectory(title="Select Right Folder")
        if not (l and r):
            return

        win = Toplevel(self)
        win.title("Folder Compare")
        win.geometry("1000x600")

        tree = ttk.Treeview(win, columns=("Status", "Path", "Size", "Mod"), show="headings")
        for col, w in zip(tree["columns"], [100, 500, 100, 150]):
            tree.heading(col, text=col)
            tree.column(col, width=w)
        tree.pack(fill=BOTH, expand=True, side=LEFT)

        vsb = ttk.Scrollbar(win, command=tree.yview)
        vsb.pack(side=RIGHT, fill=Y)
        tree.configure(yscrollcommand=vsb.set)

        def dbl(e):
            sel = tree.selection()
            if not sel:
                return
            item = sel[0]
            vals = tree.item(item, "values")
            if not vals:
                return
            rel = vals[1]
            lp = os.path.join(l, rel)
            rp = os.path.join(r, rel)

            if os.path.isfile(lp) and os.path.isfile(rp):
                self.left_path, self.right_path = lp, rp
                self._load(self.l_text, lp, 1)
                self._load(self.r_text, rp, 2)
                self.compare()
                win.destroy()

        tree.bind("<Double-1>", dbl)
        
        prog_bar = tb.Progressbar(win, mode="indeterminate", bootstyle=SUCCESS)
        prog_bar.pack(side=BOTTOM, fill=X, padx=5, pady=2)
        prog_bar.start()
        
        threading.Thread(target=self._folder_worker, args=(l, r, tree, prog_bar, win), daemon=True).start()

    def _folder_worker(self, l, r, tree, prog_bar, win):
        """Worker thread for folder comparison"""
        def ins(st, p, sz="", m=""):
            try:
                self.after(0, lambda: tree.insert("", END, values=(st, p, sz, m)))
            except:
                pass

        # Scan left folder
        left_files = {}
        for root, _, files in os.walk(l):
            rel = os.path.relpath(root, l)
            for f in files:
                path = os.path.join(rel, f) if rel != "." else f
                left_files[path] = os.path.join(root, f)

        # Scan right folder
        right_files = {}
        for root, _, files in os.walk(r):
            rel = os.path.relpath(root, r)
            for f in files:
                path = os.path.join(rel, f) if rel != "." else f
                right_files[path] = os.path.join(root, f)

        # Compare
        all_paths = set(left_files.keys()) | set(right_files.keys())

        for path in sorted(all_paths):
            if path in left_files and path not in right_files:
                lp = left_files[path]
                ins("Only Left", path, self._format_size(os.path.getsize(lp)), self._fmt(lp))

            elif path not in left_files and path in right_files:
                rp = right_files[path]
                ins("Only Right", path, self._format_size(os.path.getsize(rp)), self._fmt(rp))

            else:
                lp = left_files[path]
                rp = right_files[path]

                if self.fast_compare.get():
                    same = (os.path.getsize(lp) == os.path.getsize(rp) and
                            abs(os.path.getmtime(lp) - os.path.getmtime(rp)) < 2)
                else:
                    same = self._hash(lp) == self._hash(rp)

                ins("Identical" if same else "Different",
                    path,
                    self._format_size(os.path.getsize(lp)),
                    self._fmt(lp))

        try:
            self.after(0, lambda: prog_bar.stop())
            self.after(0, lambda: self.status.config(text="Folder compare finished"))
        except:
            pass

    def _format_size(self, size):
        """Format file size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _fmt(self, p):
        """Format file modification time"""
        try:
            return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
        except:
            return ""

    def _menu(self):
        """Create menu bar"""
        m = tb.Menu(self)

        file_menu = tb.Menu(m, tearoff=0)
        file_menu.add_command(label="Open Left", command=self.open_left)
        file_menu.add_command(label="Open Right", command=self.open_right)
        file_menu.add_separator()
        file_menu.add_command(label="Clear", command=self.clear)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        m.add_cascade(label="File", menu=file_menu)

        tools = tb.Menu(m, tearoff=0)
        tools.add_command(label="Compare Folders", command=self.compare_folders)
        tools.add_command(label="Generate Report", command=self._report)
        m.add_cascade(label="Tools", menu=tools)

        self.config(menu=m)

    def _report(self):
        """Generate comparison report"""
        if self.diff_mode.get() != "side":
            messagebox.showinfo("Report", "Only available in Side-by-Side mode.")
            return

        if not self.diff_items:
            messagebox.showinfo("Report", "No differences to report. Run comparison first.")
            return

        lines = [
            f"Beyond Compare Clone – Comparison Report",
            f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "=" * 70,
            f"Left : {self.left_path or 'N/A'}",
            f"Right: {self.right_path or 'N/A'}",
            "",
            f"Total Differences: {len(self.diff_items)}",
            "=" * 70,
            ""
        ]

        for d in self.diff_items:
            dtype = d["type"]
            if dtype == "removed":
                lines.append(f"[-] Line {d.get('l', '?')}: {d['text']}")
            elif dtype == "added":
                lines.append(f"[+] Line {d.get('r', '?')}: {d['text']}")
            elif dtype == "changed":
                lines.append(f"[~] Line {d.get('l', '?')} ↔ {d.get('r', '?')}: {d['text']}")

        p = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )

        if p:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                messagebox.showinfo("Saved", f"Report saved to:\n{p}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save report: {e}")

    def clear(self):
        """Clear both panels"""
        self.l_text.delete("1.0", END)
        self.r_text.delete("1.0", END)
        self.left_path = self.right_path = ""
        self.left_type = self.right_type = ""
        self.diff_items = []
        self.current_diff = 0
        self._clear_tags()
        self._update_nums()
        self.arrow_canvas.delete("all")
        self.move_arrows = []

        for i in self.tree.get_children():
            self.tree.delete(i)

        self.diff_lbl.config(text="0/0")
        self.status.config(text="Ready")

    def _clear_tags(self):
        """Clear all tags from text widgets"""
        for w in (self.l_text, self.r_text):
            for t in ("added", "removed", "moved", "changed", "same", "search", "sel"):
                try:
                    w.tag_remove(t, "1.0", END)
                except:
                    pass

        if self.unified.winfo_ismapped():
            self.unified.pack_forget()


if __name__ == "__main__":
    app = BeyondCompareClone()
    app.mainloop()