import os
import shutil
import subprocess
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
ORIG_BASE = r"\\pixartnas\home\INTERNAL_PROCESSING\ALL_PHOTOS\ORIGNAL"


def list_image_pairs(input_folder):
    full_dir = os.path.join(input_folder, "FULL")
    partial_dir = os.path.join(input_folder, "PARTIAL")

    if not os.path.isdir(full_dir) or not os.path.isdir(partial_dir):
        messagebox.showerror("Error", "Input folder must contain FULL and PARTIAL subfolders.")
        return []

    full_files = {
        os.path.splitext(f)[0]: os.path.join(full_dir, f)
        for f in os.listdir(full_dir)
        if f.lower().endswith(IMAGE_EXTS)
    }
    partial_files = {
        os.path.splitext(f)[0]: os.path.join(partial_dir, f)
        for f in os.listdir(partial_dir)
        if f.lower().endswith(IMAGE_EXTS)
    }
    common = sorted(set(full_files.keys()) & set(partial_files.keys()))
    return [(full_files[name], partial_files[name]) for name in common]


def _draw_guides(canvas, w, h, is_partial=False):
    canvas.delete("guides")
    x_mid = w // 2
    if not is_partial:
        y1 = int(h * 56 / 300)
        y2 = int(h * 272 / 300)
        canvas.create_line(0, y1, w, y1, fill="lime", dash=(3, 2), tags="guides")
        canvas.create_line(0, y2, w, y2, fill="lime", dash=(3, 2), tags="guides")
    else:
        canvas.create_line(0, 76, w, 76, fill="lime", dash=(3, 2), tags="guides")
        canvas.create_line(0, 210, w, 210, fill="lime", dash=(3, 2), tags="guides")
    canvas.create_line(x_mid, 0, x_mid, h, fill="lime", dash=(3, 2), tags="guides")


class ImageEditorWidget(tk.Frame):
    def __init__(self, master, img_path, canvas_w, canvas_h):
        super().__init__(master, bg="#2b2b2b", highlightthickness=4, highlightbackground="#2b2b2b")
        self.master = master
        self.img_path = img_path
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h

        self.orig_pil = Image.open(img_path).convert("RGBA")
        self.edit_pil = self.orig_pil.copy()

        self.history = []
        self.history_index = -1

        self.last_mod_time = None

        self.zoom = 1.0
        self.img_pos_x = 0
        self.img_pos_y = 0
        self.rotation = 0.0

        self._last_scale = None
        self._last_img_x = 0
        self._last_img_y = 0

        self.brush_radius = 20
        self.drawing = False
        self._stroke_changed = False

        self.canvas = tk.Canvas(self, width=self.canvas_w, height=self.canvas_h, bg="#ddd", highlightthickness=0)
        self.canvas.pack(padx=10, pady=10)
        self._tk_img = None
        self._cursor_id = None

        self.canvas.bind("<Button-1>", lambda e: self.master.focus_editor(self))
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<ButtonPress-1>", self._on_down, add="+")
        self.canvas.bind("<B1-Motion>", self._on_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        self._render()
        self.refresh_mod_time()
        self._reset_history()

    def _capture_state(self):
        return {
            "image": self.edit_pil.copy(),
            "rotation": self.rotation,
            "zoom": self.zoom,
            "img_pos_x": self.img_pos_x,
            "img_pos_y": self.img_pos_y,
        }

    def _push_history(self):
        state = self._capture_state()
        if self.history_index < len(self.history) - 1:
            self.history = self.history[: self.history_index + 1]
        self.history.append(state)
        self.history_index = len(self.history) - 1

    def _restore_state(self, state):
        self.edit_pil = state["image"].copy()
        self.rotation = state["rotation"]
        self.zoom = state["zoom"]
        self.img_pos_x = state["img_pos_x"]
        self.img_pos_y = state["img_pos_y"]
        self._render()

    def _reset_history(self):
        self.history = []
        self.history_index = -1
        self._push_history()

    def _render(self):
        preview_rotated = self.edit_pil.rotate(self.rotation, expand=True, resample=Image.BICUBIC)
        base_scale = min(self.canvas_w / preview_rotated.width, self.canvas_h / preview_rotated.height)
        scale = base_scale * self.zoom
        disp_w = max(1, int(preview_rotated.width * scale))
        disp_h = max(1, int(preview_rotated.height * scale))
        disp = preview_rotated.resize((disp_w, disp_h), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(disp)
        x = (self.canvas_w - disp_w) // 2 + int(self.img_pos_x)
        y = (self.canvas_h - disp_h) // 2 + int(self.img_pos_y)
        self._last_scale = scale
        self._last_img_x = x
        self._last_img_y = y
        self.canvas.delete("img")
        self.canvas.create_image(x, y, anchor="nw", image=self._tk_img, tags="img")
        _draw_guides(self.canvas, self.canvas_w, self.canvas_h, is_partial=(self.canvas_w == 613))
        if self._cursor_id:
            self.canvas.tag_raise(self._cursor_id)

    def _to_img(self, cx, cy):
        if not self._last_scale:
            return 0, 0
        w, h = self.edit_pil.size
        ix = int((cx - self._last_img_x) / self._last_scale)
        iy = int((cy - self._last_img_y) / self._last_scale)
        return max(0, min(ix, w - 1)), max(0, min(iy, h - 1))

    def _on_motion(self, e):
        if self._cursor_id:
            self.canvas.delete(self._cursor_id)
        r = self.brush_radius
        self._cursor_id = self.canvas.create_oval(e.x - r, e.y - r, e.x + r, e.y + r, outline="white")

    def _on_down(self, e):
        self.master.focus_editor(self)
        self.drawing = True
        self.last = (e.x, e.y)
        self._stroke_changed = False

    def _on_move(self, e):
        if not self.drawing:
            return
        ix0, iy0 = self._to_img(*self.last)
        ix1, iy1 = self._to_img(e.x, e.y)
        scale = self._last_scale or 1.0
        lw = max(1, int(2 * self.brush_radius / scale))
        r = max(1, int(self.brush_radius / scale))
        alpha = self.edit_pil.split()[3]
        draw = ImageDraw.Draw(alpha)
        draw.line([(ix0, iy0), (ix1, iy1)], fill=0, width=lw)
        draw.ellipse([ix1 - r, iy1 - r, ix1 + r, iy1 + r], fill=0)
        self.edit_pil.putalpha(alpha)
        self.last = (e.x, e.y)
        self._stroke_changed = True
        self._render()

    def _on_up(self, e):
        if self.drawing and self._stroke_changed:
            self._push_history()
        self.drawing = False
        self.last = None
        self._stroke_changed = False

    def set_brush(self, r):
        self.brush_radius = max(1, r)
        self.master.update_brush_label(r)

    def move_by(self, dx, dy):
        if dx == 0 and dy == 0:
            return
        self.img_pos_x += dx
        self.img_pos_y += dy
        self._render()
        self._push_history()

    def zoom_by(self, factor):
        if factor == 1:
            return
        self.zoom *= factor
        self._render()
        self._push_history()

    def rotate_by(self, deg):
        if deg == 0:
            return
        self.rotation = (self.rotation + deg) % 360
        self._render()
        self._push_history()

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_state(self.history[self.history_index])

    def redo(self):
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self._restore_state(self.history[self.history_index])

    def refresh_mod_time(self):
        try:
            self.last_mod_time = os.path.getmtime(self.img_path)
        except OSError:
            self.last_mod_time = None

    def check_external_update(self):
        try:
            current_mod = os.path.getmtime(self.img_path)
        except OSError:
            return
        if self.last_mod_time is None or current_mod != self.last_mod_time:
            self.reload_image(current_mod)

    def reload_image(self, mod_time=None):
        """Reload image if edited externally (e.g., Photoshop)."""
        try:
            self.orig_pil = Image.open(self.img_path).convert("RGBA")
            self.edit_pil = self.orig_pil.copy()
            self._render()
            self._reset_history()
            if mod_time is None:
                self.refresh_mod_time()
            else:
                self.last_mod_time = mod_time
        except Exception as e:
            print(f"Failed to reload image: {e}")


class DualEditor(tk.Tk):
    def __init__(self, input_folder, pairs):
        super().__init__()
        self.title("Dual Photo Editor")
        self.geometry("1600x980")
        self.input_folder = input_folder
        self.full_dir = os.path.join(input_folder, "FULL")
        self.partial_dir = os.path.join(input_folder, "PARTIAL")
        self.pairs = pairs
        self.index = 0
        self.left = None
        self.right = None
        self.focused = None

        self.photoshop_path_file = "photoshop_path.txt"
        self.photoshop_path = self._load_photoshop_path() or r"C:\Program Files\Adobe\Adobe Photoshop 2025\Photoshop.exe"

        bar = tk.Frame(self, bg="#333")
        bar.pack(side="bottom", fill="x")
        tk.Button(bar, text="← Prev", command=self.prev).pack(side="left", padx=6, pady=6)
        tk.Button(bar, text="Undo (Ctrl+Z)", command=lambda: self._do("undo")).pack(side="left")
        tk.Button(bar, text="Redo (Ctrl+Shift+Z)", command=lambda: self._do("redo")).pack(side="left")
        tk.Button(bar, text="Open in Photoshop", bg="#ffcc66", command=self.open_in_photoshop).pack(side="left", padx=10)
        tk.Button(bar, text="Locate Photoshop", bg="#ff9966", command=self.locate_photoshop).pack(side="left", padx=10)

        self.brush_label = tk.Label(bar, text="20", bg="#333", fg="white")
        self.brush_label.pack(side="left", padx=20)
        tk.Button(bar, text="Save", bg="#9f9", command=self._save).pack(side="left")
        tk.Button(bar, text="Replace Original", bg="#ff6666", command=self._replace_original).pack(side="left", padx=10)
        tk.Button(bar, text="Next →", bg="#9ff", command=self.next).pack(side="right", padx=6)

        # Shortcuts
        self.bind_all("<Control-z>", lambda e: self._do("undo"))
        self.bind_all("<Control-Z>", lambda e: self._do("undo"))
        self.bind_all("<Control-Shift-Z>", lambda e: self._do("redo"))
        self.bind_all("<Control-Shift-z>", lambda e: self._do("redo"))
        self.bind_all("<Control-y>", lambda e: self._do("redo"))
        self.bind_all("[", lambda e: self._change_brush(-2))
        self.bind_all("]", lambda e: self._change_brush(2))
        self.bind_all("+", lambda e: self._do("zoom", 1.02))
        self.bind_all("-", lambda e: self._do("zoom", 0.98))
        self.bind_all("/", lambda e: self._do("rotate", -5))
        self.bind_all("*", lambda e: self._do("rotate", 5))
        for k, dx, dy in [("<Left>", -2, 0), ("<Right>", 2, 0), ("<Up>", 0, -2), ("<Down>", 0, 2)]:
            self.bind_all(k, lambda e, dx=dx, dy=dy: self._do("move", dx, dy))

        self.bind_all("<Return>", lambda e: self.next())
        self.bind_all("<KP_Enter>", lambda e: self.next())
        self.bind_all("<BackSpace>", lambda e: self.prev())

        self.bind("<FocusIn>", self._check_external_updates)

        self._load(0)

    def _load(self, i):
        if self.left: self.left.destroy()
        if self.right: self.right.destroy()
        lf, rt = self.pairs[i]
        self.left = ImageEditorWidget(self, lf, 300, 300)
        self.right = ImageEditorWidget(self, rt, 613, 713)
        self.left.pack(side="left", expand=True, padx=20, pady=20)
        self.right.pack(side="right", expand=True, padx=20, pady=20)
        self.focus_editor(self.left)

    def focus_editor(self, e):
        self.focused = e
        if self.left == e:
            self.left.config(highlightbackground="#1e90ff")
            self.right.config(highlightbackground="#2b2b2b")
        else:
            self.right.config(highlightbackground="#1e90ff")
            self.left.config(highlightbackground="#2b2b2b")
        self.update_brush_label(self.focused.brush_radius)

    def update_brush_label(self, r):
        self.brush_label.config(text=str(r))

    def _do(self, action, *args):
        e = self.focused
        if not e: return
        if action == "undo": e.undo()
        elif action == "redo": e.redo()
        elif action == "move": e.move_by(*args)
        elif action == "zoom": e.zoom_by(args[0])
        elif action == "rotate": e.rotate_by(args[0])

    def _change_brush(self, d):
        if self.focused:
            self.focused.set_brush(self.focused.brush_radius + d)

    def _save(self):
        self.left.edit_pil.save(self.left.img_path)
        self.right.edit_pil.save(self.right.img_path)
        self.left.refresh_mod_time()
        self.right.refresh_mod_time()
        messagebox.showinfo("Saved", "Images saved successfully!")

    def _replace_original(self):
        if not self.focused:
            messagebox.showerror("Error", "Select an editor first.")
            return

        editor = self.focused
        src_path = editor.img_path
        try:
            editor.edit_pil.save(src_path)
            editor.refresh_mod_time()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save image before replacing original:\n{e}")
            return

        rel_path = None
        normalized_src = os.path.normpath(src_path)
        normalized_src_case = os.path.normcase(normalized_src)
        for base in (self.full_dir, self.partial_dir):
            if not base:
                continue
            try:
                normalized_base = os.path.normpath(base)
                common = os.path.commonpath([os.path.normcase(normalized_base), normalized_src_case])
            except ValueError:
                continue
            if common == os.path.normcase(normalized_base):
                try:
                    rel_path = os.path.relpath(normalized_src, normalized_base)
                except ValueError:
                    rel_path = os.path.basename(normalized_src)
                break

        if not rel_path:
            rel_path = os.path.basename(normalized_src)

        dest_path = os.path.join(ORIG_BASE, rel_path)
        dest_dir = os.path.dirname(dest_path)
        try:
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
        except OSError as e:
            if not dest_dir or not os.path.isdir(dest_dir):
                messagebox.showerror("Error", f"Could not access original folder:\n{e}")
                return

        try:
            shutil.copy2(src_path, dest_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to replace original:\n{e}")
            return

        messagebox.showinfo("Replace Original", f"Copied to:\n{dest_path}")

    def next(self):
        self._save()
        self.index += 1
        if self.index >= len(self.pairs): self.destroy(); return
        self._load(self.index)

    def prev(self):
        if self.index <= 0:
            messagebox.showinfo("Start", "You are already at the first image pair.")
            return
        self._save()
        self.index -= 1
        self._load(self.index)

    # --- Photoshop Integration ---
    def _load_photoshop_path(self):
        if os.path.exists(self.photoshop_path_file):
            with open(self.photoshop_path_file, "r") as f:
                return f.read().strip()
        return None

    def locate_photoshop(self):
        path = filedialog.askopenfilename(title="Locate Photoshop Executable", filetypes=[("EXE files", "*.exe")])
        if path:
            self.photoshop_path = path
            with open(self.photoshop_path_file, "w") as f:
                f.write(path)
            messagebox.showinfo("Photoshop Path Saved", f"Photoshop path saved:\n{path}")

    def open_in_photoshop(self):
        if not self.focused:
            messagebox.showerror("Error", "Select an editor first.")
            return
        if not os.path.exists(self.photoshop_path):
            messagebox.showerror("Error", "Photoshop not found. Locate it first.")
            return

        img_path = self.focused.img_path
        subprocess.Popen([self.photoshop_path, img_path])

        # Watch file for changes in a separate thread
        threading.Thread(target=self._watch_file, args=(self.focused, img_path), daemon=True).start()

    def _watch_file(self, editor, path):
        try:
            last_mod = os.path.getmtime(path)
            while True:
                time.sleep(1)
                if os.path.getmtime(path) != last_mod:
                    editor.reload_image()
                    break
        except Exception as e:
            print(f"File watch error: {e}")

    def _check_external_updates(self, event=None):
        for editor in (self.left, self.right):
            if editor:
                editor.check_external_update()


def main():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select input folder with FULL and PARTIAL")
    root.destroy()
    if not folder:
        return
    pairs = list_image_pairs(folder)
    if not pairs:
        return
    DualEditor(folder, pairs).mainloop()


if __name__ == "__main__":
    main()
