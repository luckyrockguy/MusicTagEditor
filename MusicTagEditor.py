import os
import re
import shutil
import mutagen
from mutagen.easyid3 import EasyID3
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk, simpledialog
import musicbrainzngs 
import threading
from datetime import datetime

# 검색 결과 선택을 위한 별도 팝업 클래스
class SelectionDialog(tk.Toplevel):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.title("검색 결과 선택")
        self.geometry("600x400")
        self.result_data = None
        
        lbl = tk.Label(self, text="가장 일치하는 항목을 선택해 주세요:", font=('Malgun Gothic', 10, 'bold'))
        lbl.pack(pady=10)

        # 트리뷰를 사용하여 검색 결과 표시
        cols = ("앨범명", "아티스트", "트랙수", "연도")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=100, anchor="center")
        self.tree.column("앨범명", width=250, anchor="w")
        
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 데이터 삽입
        for res in results:
            rel = res.get('release-list', [{}])[0]
            alb = rel.get('title', '-')
            art = res.get('artist-credit-phrase', '-')
            cnt = rel.get('medium-track-count', '-')
            dat = rel.get('date', '-')[:4]
            self.tree.insert("", "end", values=(alb, art, cnt, dat), tags=(res['id'],))

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="선택 적용", command=self.on_select).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="취소", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.tree.bind("<Double-1>", lambda e: self.on_select())
        self.grab_set() # 팝업이 닫히기 전까지 메인 창 조작 방지

    def on_select(self):
        sel = self.tree.selection()
        if sel:
            self.result_data = self.tree.item(sel[0], 'values')
            self.destroy()

class MusicTagEditorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("음악 태그 정제기 v2.1 (Search Selection)")
        self.root.geometry("1300x950")
        self.root.configure(bg="#F3F3F3")
        
        self.history_dict = {k: [] for k in ["ent_title", "ent_artist", "ent_track", "ent_album", "ent_genre", "ent_date", "ent_keywords"]}
        musicbrainzngs.set_useragent("MyMusicTagTool", "2.1", "contact@example.com")
        self.supported_ext = ('.mp3', '.flac', '.m4a', '.ogg', '.wma', '.wav')
        self.full_file_paths = {}
        self.selected_path = ""

        self.setup_ui()
        self.load_drives()
        self.log("시스템 시작: 다중 검색 결과 선택 기능이 로드되었습니다.")

    def log(self, msg):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        self.log_area.insert(tk.END, f"{timestamp} {msg}\n")
        self.log_area.see(tk.END)

    # --- 개선된 온라인 검색 기능 (팝업 연동) ---
    def fetch_online_data(self):
        art, tit = self.ent_artist.get().strip(), self.ent_title.get().strip()
        if not art or not tit: 
            messagebox.showwarning("알림", "가수와 제목이 입력되어야 검색이 가능합니다.")
            return

        self.log(f"검색 요청: {art} - {tit}")
        try:
            # 검색 범위를 조금 넓혀서 최대 10개까지 가져옴
            res = musicbrainzngs.search_recordings(artist=art, recording=tit, limit=10)
            recordings = res.get('recording-list', [])

            if not recordings:
                self.log("검색 결과가 없습니다.")
                messagebox.showinfo("알림", "일치하는 정보를 찾을 수 없습니다.")
                return

            if len(recordings) == 1:
                # 결과가 하나면 즉시 적용
                self.apply_search_result(recordings[0])
            else:
                # 결과가 여러 개면 선택 팝업 실행
                dialog = SelectionDialog(self.root, recordings)
                self.root.wait_window(dialog)
                if dialog.result_data:
                    alb, _, _, dat = dialog.result_data
                    self.update_field_with_compare(self.ent_album, alb)
                    self.update_field_with_compare(self.ent_date, dat)
                    self.log(f"사용자 선택 적용: {alb} ({dat})")

        except Exception as e:
            self.log(f"검색 중 오류 발생: {e}")

    def apply_search_result(self, d):
        rel = d.get('release-list', [{}])[0]
        self.update_field_with_compare(self.ent_album, rel.get('title', '-'))
        self.update_field_with_compare(self.ent_date, rel.get('date', '-')[:4])
        self.log(f"자동 적용 완료: {rel.get('title', '-')}")

    # --- 기존 정렬 및 유틸리티 로직 ---
    def sort_column(self, col, reverse):
        l = [(self.file_grid.set(k, col), k) for k in self.file_grid.get_children('')]
        try:
            l.sort(key=lambda t: int(re.sub(r'[^0-9]', '', t[0])) if re.sub(r'[^0-9]', '', t[0]) else 0, reverse=reverse)
        except:
            l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l):
            self.file_grid.move(k, '', index)
        self.file_grid.heading(col, command=lambda: self.sort_column(col, not reverse))

    # (이하 UI 및 탐색기 관련 코드는 v2.0과 동일하게 유지)
    def setup_ui(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.FLAT, sashwidth=4, bg="#F3F3F3")
        self.main_paned.pack(fill=tk.BOTH, expand=True)
        self.left_frame = tk.Frame(self.main_paned, bg="#F3F3F3")
        self.main_paned.add(self.left_frame, width=280)
        self.create_left_widgets()
        self.right_frame = tk.Frame(self.main_paned, bg="#FFFFFF")
        self.main_paned.add(self.right_frame)
        self.input_area = tk.Frame(self.right_frame, bg="#FFFFFF")
        self.input_area.pack(fill=tk.X, padx=15, pady=(15, 0))
        self.create_input_fields()
        self.button_area = tk.Frame(self.right_frame, bg="#FFFFFF")
        self.button_area.pack(fill=tk.X, padx=15, pady=10)
        self.create_control_buttons()
        self.v_paned = tk.PanedWindow(self.right_frame, orient=tk.VERTICAL, sashrelief=tk.FLAT, sashwidth=4, bg="#F3F3F3")
        self.v_paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        self.create_grid_area()
        self.create_log_area()
        self.create_context_menus()

    def create_input_fields(self):
        f_grid = tk.Frame(self.input_area, bg="#FFFFFF")
        f_grid.pack(fill=tk.X)
        self.lbl_path = tk.Label(f_grid, text="📁 폴더를 선택해 주세요", fg="#555555", bg="#FFFFFF", font=('Malgun Gothic', 9, 'bold'))
        self.lbl_path.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        fields = [("제목", "ent_title", False), ("가수", "ent_artist", False), ("트랙", "ent_track", False), ("앨범", "ent_album", True), ("장르", "ent_genre", True), ("연도", "ent_date", True), ("키워드", "ent_keywords", False)]
        for i, (lt, vn, cl) in enumerate(fields, 1):
            lbl_c = tk.Frame(f_grid, bg="#FFFFFF")
            lbl_c.grid(row=i, column=0, sticky="e", pady=3, padx=(0, 10))
            tk.Label(lbl_c, text=lt, font=('Malgun Gothic', 9), bg="#FFFFFF").pack(side=tk.LEFT)
            ent = tk.Entry(f_grid, font=('Malgun Gothic', 10), relief=tk.SOLID, borderwidth=1)
            setattr(self, vn, ent)
            if cl: ttk.Button(lbl_c, text="CLR", command=lambda e=ent: self.set_null_value(e), width=4).pack(side=tk.LEFT, padx=2)
            if vn == "ent_title":
                ttk.Button(f_grid, text="파일명 추출", command=self.load_filename_to_title).grid(row=i, column=1, padx=2)
                ent.grid(row=i, column=2, columnspan=2, sticky="ew", padx=2)
            else: ent.grid(row=i, column=1, columnspan=3, sticky="ew", padx=2, pady=3)
        f_grid.columnconfigure(2, weight=1)

    def advanced_title_parse(self):
        """텍스트 파싱 및 트랙 번호 추출 기능"""
        src = self.ent_title.get().strip()
        if not src: 
            self.log("알림: 파싱할 제목이 없습니다.")
            return
            
        self.log(f"텍스트 파싱 시작: '{src}'")
        clean = src
        art = self.ent_artist.get().strip()
        kw = self.ent_keywords.get().strip()

        # 가수명 제거
        if art: 
            clean = re.compile(re.escape(art), re.IGNORECASE).sub(' ', clean)
            self.log(f"가수명('{art}') 제거 수행")
            
        # 키워드 제거
        if kw:
            for k in kw.split(';'):
                if k.strip(): 
                    clean = re.compile(re.escape(k.strip()), re.IGNORECASE).sub(' ', clean)
                    self.log(f"키워드('{k.strip()}') 제거 수행")
        
        # 숫자(트랙번호) 추출 및 제목에서 분리
        m = re.match(r'^(\d+)([.\s\-_]+)', clean.strip())
        if m:
            tr = str(int(m.group(1)))
            self.update_field_with_compare(self.ent_track, tr)
            clean = clean.strip()[len(m.group(0)):].strip()
            self.log(f"트랙번호 '{tr}' 추출 완료")

        # 특수문자 정제
        clean = re.sub(r'[^a-zA-Z0-9가-힣\s\(\)\[\]]', ' ', clean).strip()
        
        if src != clean:
            self.ent_title.delete(0, tk.END)
            self.ent_title.insert(0, clean)
            self.ent_title.config(fg="#0078D4")
            self.log(f"최종 정제 결과: '{clean}'")

    def create_control_buttons(self):
        ttk.Button(self.button_area, text="🚀 태그 수정 및 파일명 일괄 변경 실행", command=self.run_process).pack(fill=tk.X, ipady=8)
        sub = tk.Frame(self.button_area, bg="#FFFFFF")
        sub.pack(fill=tk.X, pady=5)
        for i, (t, c) in enumerate([("🧹 초기화", self.clear_fields_with_color), ("📝 텍스트 파싱", self.advanced_title_parse), ("🌐 검색", self.fetch_online_data), ("🔍 자동 매칭", self.start_batch_search)]):
            sub.columnconfigure(i, weight=1)
            ttk.Button(sub, text=t, command=c).grid(row=0, column=i, sticky="ew", padx=2)

    def create_grid_area(self):
        g_f = tk.Frame(self.v_paned, bg="white"); self.v_paned.add(g_f, height=550)
        self.cols = ("파일명", "트랙", "제목", "가수", "앨범", "연도", "장르", "비트전송률")
        self.file_grid = ttk.Treeview(g_f, columns=self.cols, show="headings", selectmode="extended")
        self.file_grid.tag_configure('diff', foreground='#0078D4')
        for c in self.cols: 
            self.file_grid.heading(c, text=c, command=lambda _c=c: self.sort_column(_c, False))
            self.file_grid.column(c, width=70, anchor="center")
        self.file_grid.column("파일명", width=300, anchor="w")
        vsb = ttk.Scrollbar(g_f, orient="vertical", command=self.file_grid.yview)
        self.file_grid.configure(yscrollcommand=vsb.set)
        self.file_grid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_grid.bind("<<TreeviewSelect>>", self.on_grid_click_or_select)
        self.file_grid.bind("<Button-3>", self.on_grid_right_click)

    def create_log_area(self):
        l_f = tk.Frame(self.v_paned); self.v_paned.add(l_f, height=200)
        self.log_area = scrolledtext.ScrolledText(l_f, bg="#2D2D2D", fg="#DCDCDC", font=('Consolas', 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)

    def create_left_widgets(self):
        tk.Label(self.left_frame, text="EXPLORER", font=('Malgun Gothic', 10, 'bold'), bg="#F3F3F3").pack(pady=10)
        self.drive_combo = ttk.Combobox(self.left_frame, state="readonly"); self.drive_combo.pack(fill=tk.X, padx=10)
        self.drive_combo.bind("<<ComboboxSelected>>", self.on_drive_select)
        self.dir_tree = ttk.Treeview(self.left_frame, selectmode="browse"); self.dir_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.dir_tree.bind("<<TreeviewOpen>>", self.on_dir_open); self.dir_tree.bind("<Double-1>", self.on_dir_double_click); self.dir_tree.bind("<Button-3>", self.on_tree_right_click)

    def create_context_menus(self):
        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="🗑 선택한 파일 삭제", command=self.delete_selected_files)
        self.dir_context_menu = tk.Menu(self.root, tearoff=0)
        self.dir_context_menu.add_command(label="✏️ 이름 바꾸기", command=self.rename_selected_folder)
        self.dir_context_menu.add_command(label="📂 폴더 삭제", command=self.delete_selected_folder)

    def load_drives(self):
        import string; from ctypes import windll
        d = [f"{l}:\\" for l, b in zip(string.ascii_uppercase, bin(windll.kernel32.GetLogicalDrives())[::-1]) if b == '1']
        self.drive_combo['values'] = d
        if d: self.drive_combo.current(0); self.on_drive_select(None)
    def on_drive_select(self, event):
        d = self.drive_combo.get(); self.dir_tree.delete(*self.dir_tree.get_children())
        self.insert_nodes(self.dir_tree.insert("", "end", text=d, values=[d]), d)
    def insert_nodes(self, p, path):
        try:
            for n in sorted(os.listdir(path)):
                fp = os.path.join(path, n); node = self.dir_tree.insert(p, "end", text=n, values=[fp])
                if os.path.isdir(fp):
                    try: 
                        if any(os.path.isdir(os.path.join(fp, x)) for x in os.listdir(fp)): self.dir_tree.insert(node, "end")
                    except: pass
        except: pass
    def on_dir_open(self, event):
        n = self.dir_tree.focus(); p = self.dir_tree.item(n, "values")[0]
        self.dir_tree.delete(*self.dir_tree.get_children(n)); self.insert_nodes(n, p)
    def on_dir_double_click(self, event):
        n = self.dir_tree.identify_row(event.y)
        if n: self.selected_path = self.dir_tree.item(n, "values")[0]; self.lbl_path.config(text=f"📂 {self.selected_path}"); self.refresh_grid_list(self.selected_path)
    def refresh_grid_list(self, path):
        self.file_grid.delete(*self.file_grid.get_children()); self.full_file_paths.clear()
        for r, _, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith(self.supported_ext):
                    fp = os.path.join(r, f)
                    try:
                        a = mutagen.File(fp, easy=True); info = mutagen.File(fp).info
                        v = (f, a.get('tracknumber', ['-'])[0], a.get('title', ['-'])[0], a.get('artist', ['-'])[0], a.get('album', ['-'])[0], a.get('date', ['-'])[0], a.get('genre', ['-'])[0], f"{int(info.bitrate/1000)}k")
                        self.full_file_paths[self.file_grid.insert("", "end", values=v)] = fp
                    except: pass
    def set_null_value(self, target_entry): target_entry.delete(0, tk.END); target_entry.insert(0, "Null"); target_entry.config(fg="#D13438")
    def update_field_with_compare(self, ew, nv):
        c = ew.get().strip(); n = str(nv).strip()
        if ew == self.ent_track and n.isdigit(): n = str(int(n))
        if n and n != "-" and c != n: ew.delete(0, tk.END); ew.insert(0, n); ew.config(fg="#0078D4")
    def clear_fields_with_color(self):
        for v in self.history_dict.keys(): getattr(self, v).delete(0, tk.END); getattr(self, v).config(fg="black")
    def on_grid_click_or_select(self, event=None):
        sel = self.file_grid.selection()
        if not sel: return
        v = self.file_grid.item(sel[0], "values")
        mapping = {self.ent_title: v[2], self.ent_artist: v[3], self.ent_track: v[1], self.ent_album: v[4], self.ent_date: v[5], self.ent_genre: v[6]}
        for w, val in mapping.items():
            w.delete(0, tk.END); cv = "" if val == "-" else val
            if w == self.ent_track and cv.isdigit(): cv = str(int(cv))
            w.insert(0, cv); w.config(fg="black")
    def on_grid_right_click(self, event):
        item = self.file_grid.identify_row(event.y)
        if item:
            if item not in self.file_grid.selection(): self.file_grid.selection_set(item)
            self.file_context_menu.post(event.x_root, event.y_root)
    def on_tree_right_click(self, event):
        item = self.dir_tree.identify_row(event.y)
        if item: self.dir_tree.selection_set(item); self.dir_context_menu.post(event.x_root, event.y_root)
    def delete_selected_files(self):
        targets = self.file_grid.selection()
        if targets and messagebox.askyesno("삭제", "파일을 삭제하시겠습니까?"):
            for i in targets:
                fp = self.full_file_paths.get(i)
                if fp and os.path.exists(fp): os.remove(fp); self.file_grid.delete(i)
    def delete_selected_folder(self):
        item = self.dir_tree.selection()
        if not item: return
        tp = self.dir_tree.item(item[0], "values")[0]
        if len(tp) > 3 and messagebox.askyesno("삭제", "폴더를 삭제하시겠습니까?"):
            shutil.rmtree(tp); self.dir_tree.delete(item[0])
    def rename_selected_folder(self):
        item = self.dir_tree.selection()
        if not item: return
        old = self.dir_tree.item(item[0], "values")[0]
        new = simpledialog.askstring("이름 바꾸기", "새 이름:", initialvalue=os.path.basename(old))
        if new:
            new_fp = os.path.join(os.path.dirname(old), new)
            os.rename(old, new_fp); self.on_drive_select(None)
    def run_process(self):
        targets = self.file_grid.selection()
        if not targets: return
        raw = {k: getattr(self, k).get().strip() for k in ["ent_title", "ent_artist", "ent_track", "ent_album", "ent_genre", "ent_date"]}
        for item_id in targets:
            fp = self.full_file_paths.get(item_id)
            if not fp: continue
            try:
                audio = mutagen.File(fp, easy=True)
                mapping = {'title': 'ent_title', 'artist': 'ent_artist', 'album': 'ent_album', 'tracknumber': 'ent_track', 'date': 'ent_date', 'genre': 'ent_genre'}
                for tag, key in mapping.items():
                    val = raw[key]
                    if val.upper() == "NULL": audio.pop(tag, None)
                    elif val: audio[tag] = str(int(val)) if tag == 'tracknumber' and val.isdigit() else val
                audio.save()
            except: pass
        self.refresh_grid_list(self.selected_path)
    def start_batch_search(self):
        items = self.file_grid.get_children()
        if items: threading.Thread(target=self.batch_search_logic, args=(items,), daemon=True).start()
    def batch_search_logic(self, items):
        for i in items:
            v = self.file_grid.item(i, "values")
            try:
                res = musicbrainzngs.search_recordings(artist=v[3], recording=v[2], limit=1)
                if res['recording-list']:
                    d = res['recording-list'][0]; r = d.get('release-list', [{}])[0]
                    alb, dat = r.get('title', '-'), r.get('date', '-')[:4]
                    tr = "-"
                    try: tr = str(int(r['medium-list'][0]['track-list'][0]['number']))
                    except: pass
                    diff = (alb != v[4] or dat != v[5] or (tr != v[1] and tr != "-"))
                    self.root.after(0, lambda _i=i, _v=v, _a=alb, _d=dat, _t=tr, _df=diff: self.update_grid_item(_i, _v, _a, _d, _t, _df))
            except: pass
    def update_grid_item(self, i, vv, a, d, t, diff):
        new_v = list(vv); new_v[1], new_v[4], new_v[5] = t, a, d
        self.file_grid.item(i, values=new_v, tags=('diff',) if diff else ())
    def load_filename_to_title(self):
        sel = self.file_grid.selection()
        if sel: 
            f = os.path.splitext(self.file_grid.item(sel[0], "values")[0])[0]
            self.ent_title.delete(0, tk.END); self.ent_title.insert(0, f)

if __name__ == "__main__":
    root = tk.Tk(); MusicTagEditorGUI(root); root.mainloop()