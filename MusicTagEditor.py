import os
import re
import shutil
import mutagen
from mutagen.easyid3 import EasyID3
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk, simpledialog
import musicbrainzngs 
import threading
import regex as regex
from datetime import datetime


# 검색 결과 선택을 위한 별도 팝업 클래스
class SelectionDialog(tk.Toplevel):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.title("검색 결과 선택")
        self.geometry("900x400")
        self.result_data = None
        
        lbl = tk.Label(self, text="가장 일치하는 항목을 선택해 주세요:", font=('Malgun Gothic', 10, 'bold'))
        lbl.pack(pady=10)

        # 트리뷰를 사용하여 검색 결과 표시
        cols = ("노래 제목", "앨범명", "아티스트", "트랙번호", "연도")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=100, anchor="center")
        
        # 컬럼별 너비 세부 조정
        self.tree.column("노래 제목", width=250, anchor="w")
        self.tree.column("앨범명", width=250, anchor="w")
        self.tree.column("아티스트", width=150, anchor="w")
        
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 데이터 삽입
        for res in results:
            tit = res.get('title', '-') # 검색된 곡의 제목
            rel = res.get('release-list', [{}])[0]
            alb = rel.get('title', '-')
            art = res.get('artist-credit-phrase', '-')
            dat = rel.get('date', '-')[:4]
            
            # [수정] 전체 트랙수가 아닌, 이 곡의 해당 앨범 내 트랙 번호를 추출
            trk_num = "-"
            try:
                # medium-list 안의 track-list에서 현재 검색된 곡과 일치하는 트랙 번호 찾기
                medium = rel.get('medium-list', [{}])[0]
                track_list = medium.get('track-list', [])
                # recording 검색 결과이므로 보통 첫 번째 트랙 리스트의 number가 해당 곡의 번호입니다.
                trk_num = track_list[0].get('number', '-')
            except:
                pass
           
            self.tree.insert("", "end", values=(tit, alb, art, trk_num, dat), tags=(res['id'],))

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="선택 적용", command=self.on_select).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="취소", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.tree.bind("<Double-1>", lambda e: self.on_select())
        self.grab_set() # 팝업이 닫히기 전까지 메인 창 조작 방지

    # SelectionDialog 클래스 내부의 on_select 메서드 수정
    def on_select(self):
        sel = self.tree.selection()
        if sel:
            # [주의] 데이터 구조가 변경되었으므로 인덱스 확인
            # values는 (노래 제목, 앨범명, 아티스트, 트랙번호, 연도) 순서입니다.
            full_values = self.tree.item(sel[0], 'values')
            # 기존 GUI에서 기대하는 데이터 형식(앨범, 아티스트, 트랙, 연도)으로 슬라이싱하여 전달
            # 노래 제목은 이미 입력창에 있으므로 앨범 정보부터 추출합니다.
            self.result_data = (full_values[1], full_values[2], full_values[3], full_values[4])
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
        
        # [추가] 현재 소팅 상태 저장 (컬럼명, 반전 여부)
        self.current_sort = {"col": None, "reverse": False}

        self.setup_ui()
        self.load_drives()
        self.log("시스템 시작: 다중 검색 결과 선택 기능이 로드되었습니다.")

    def log(self, msg):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        self.log_area.insert(tk.END, f"{timestamp} {msg}\n")
        self.log_area.see(tk.END)

    # --- 개선된 온라인 검색 기능 (팝업 연동) ---
    # MusicTagEditorGUI 클래스 내부의 fetch_online_data 메서드 수정
    def fetch_online_data(self):
        art, tit = self.ent_artist.get().strip(), self.ent_title.get().strip()
        if not art or not tit: 
            messagebox.showwarning("알림", "가수와 제목이 입력되어야 검색이 가능합니다.")
            return

        self.log(f"검색 요청: {art} - {tit}")
        try:
            res = musicbrainzngs.search_recordings(artist=art, recording=tit, limit=10)
            recordings = res.get('recording-list', [])

            if not recordings:
                self.log("검색 결과가 없습니다.")
                messagebox.showinfo("알림", "일치하는 정보를 찾을 수 없습니다.")
                return

            if len(recordings) == 1:
                self.apply_search_result(recordings[0])
            else:
                dialog = SelectionDialog(self.root, recordings)
                self.root.wait_window(dialog)
                
                if dialog.result_data:
                    # dialog.result_data 구조: (앨범명, 아티스트, 트랙번호, 연도)
                    alb, artist_name, trk, dat = dialog.result_data
                    
                    # 입력 필드 업데이트 (기존 앨범, 연도 외에 '트랙' 추가)
                    self.update_field_with_compare(self.ent_album, alb)
                    self.update_field_with_compare(self.ent_date, dat)
                    
                    # --- [수정 구간: 트랙 번호 입력 추가] ---
                    if trk and trk != '-':
                        self.update_field_with_compare(self.ent_track, trk)
                    # ---------------------------------------
                    
                    # 아티스트 정보도 필요시 업데이트 가능
                    self.update_field_with_compare(self.ent_artist, artist_name)
                    
                    self.log(f"사용자 선택 적용: {alb} | 트랙: {trk} | 연도: {dat}")

        except Exception as e:
            self.log(f"검색 중 오류 발생: {e}")

    def apply_search_result(self, d):
        rel = d.get('release-list', [{}])[0]
        # 앨범명, 연도 추출
        alb_title = rel.get('title', '-')
        rel_date = rel.get('date', '-')[:4]
        
        # [수정] 해당 녹음(Recording)의 정확한 트랙 번호 추출
        trk_num = "-"
        try:
            # MusicBrainz의 recording 검색 결과는 해당 곡이 포함된 앨범 정보를 함께 줍니다.
            # 그 앨범(release) 내의 트랙 리스트에서 '이 곡'의 순번을 가져옵니다.
            medium_list = rel.get('medium-list', [])
            if medium_list:
                track_list = medium_list[0].get('track-list', [])
                if track_list:
                    trk_num = track_list[0].get('number', '-')
        except Exception as e:
            self.log(f"트랙 번호 추출 실패: {e}")

        self.update_field_with_compare(self.ent_album, alb_title)
        self.update_field_with_compare(self.ent_date, rel_date)
        
        # 트랙 번호가 존재할 경우 입력 (01 등으로 변환은 이후 run_process에서 처리됨)
        if trk_num != "-":
            self.update_field_with_compare(self.ent_track, trk_num)
        
        self.log(f"정보 수신: {alb_title} | 트랙: {trk_num}")

    def sort_column(self, col, reverse):
        """그리드의 모든 헤더를 클릭했을 때 호출되는 정렬 메서드"""
        # 정렬 상태 업데이트
        self.current_sort["col"] = col
        self.current_sort["reverse"] = reverse
        
        # 모든 헤더에서 기호 제거 및 선택된 헤더에 삼각형 표시
        for c in self.cols:
            header_text = c
            if c == col:
                header_text += " ▲" if not reverse else " ▼"
            self.file_grid.heading(c, text=header_text)

        # 현재 그리드의 모든 항목 가져오기 (값, 아이디)
        l = [(self.file_grid.set(k, col), k) for k in self.file_grid.get_children('')]
        
        # 정렬 기준 설정 함수
        def sort_key(item):
            val = item[0]
            # 1. 비트전송률 (예: '320k') 처리
            if col == "비트전송률":
                try: return int(re.sub(r'[^0-9]', '', val))
                except: return 0
            
            # 2. 트랙 번호나 연도 등 숫자 데이터 처리
            if val.isdigit():
                return int(val)
            
            # 3. 일반 문자열 (가수명, 제목 등) - 대소문자 구분 없이 처리
            return val.lower()

        # 데이터 정렬 실행
        l.sort(key=sort_key, reverse=reverse)

        # 정렬된 순서대로 트리뷰 항목 이동
        for index, (val, k) in enumerate(l):
            self.file_grid.move(k, '', index)

        # 다음 클릭 시 반대 방향으로 정렬되도록 헤더 명령 업데이트
        self.file_grid.heading(col, command=lambda: self.sort_column(col, not reverse))
        
        self.log(f"정렬 완료: [{col}] 기준 {'내림차순' if reverse else '오름차순'}")

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
        self.dir_tree.tag_configure('file', foreground='#0078D4') # 파일은 파란색
        self.dir_tree.tag_configure('folder', foreground='#333333') # 폴더는 검정색 
        self.v_paned = tk.PanedWindow(self.right_frame, orient=tk.VERTICAL, sashrelief=tk.FLAT, sashwidth=4, bg="#F3F3F3")
        self.v_paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        self.create_grid_area()
        self.create_log_area()
        self.create_context_menus()

    def create_input_fields(self):
        f_grid = tk.Frame(self.input_area, bg="#FFFFFF")
        f_grid.pack(fill=tk.X)

        # 현재 선택된 폴더 경로 표시 레이블
        self.lbl_path = tk.Label(f_grid, text="📁 폴더를 선택해 주세요", fg="#555555", 
                                 bg="#FFFFFF", font=('Malgun Gothic', 9, 'bold'))
        self.lbl_path.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        # 필드 구성 정의: (레이블 텍스트, 변수명, CLR 버튼 여부)
        fields = [
            ("제목", "ent_title", False), 
            ("가수", "ent_artist", False), 
            ("트랙", "ent_track", False), 
            ("앨범", "ent_album", True), 
            ("장르", "ent_genre", True), 
            ("연도", "ent_date", True), 
            ("키워드", "ent_keywords", False)
        ]

        for i, (lt, vn, cl) in enumerate(fields, 1):
            # 레이블 영역 (텍스트 + CLR 버튼)
            lbl_c = tk.Frame(f_grid, bg="#FFFFFF")
            lbl_c.grid(row=i, column=0, sticky="e", pady=3, padx=(0, 10))
            
            tk.Label(lbl_c, text=lt, font=('Malgun Gothic', 9), bg="#FFFFFF").pack(side=tk.LEFT)
            
            # Entry(입력창) 생성
            ent = tk.Entry(f_grid, font=('Malgun Gothic', 10), relief=tk.SOLID, borderwidth=1)
            setattr(self, vn, ent)
            
            # [기능 추가] 더블 클릭 시 최근 입력 기록 7개 팝업 노출
            ent.bind("<Double-1>", lambda e, v=vn: self.show_history_popup(e, v))
            
            # CLR(초기화) 버튼이 필요한 필드인 경우
            if cl: 
                ttk.Button(lbl_c, text="CLR", command=lambda e=ent: self.set_null_value(e), 
                           width=4).pack(side=tk.LEFT, padx=2)
            
            # 레이아웃 배치 로직
            if vn == "ent_title":
                # 제목 필드 옆에는 '파일명 추출' 버튼 배치
                ttk.Button(f_grid, text="파일명 추출", command=self.load_filename_to_title).grid(row=i, column=1, padx=2)
                ent.grid(row=i, column=2, columnspan=2, sticky="ew", padx=2)
            else:
                # 나머지 필드는 길게 배치
                ent.grid(row=i, column=1, columnspan=3, sticky="ew", padx=2, pady=3)
        
        # 그리드 너비 가변 설정
        f_grid.columnconfigure(2, weight=1)

    def show_history_popup(self, event, var_name):
        """더블 클릭 시 최근 기록 7개를 보여주는 팝업 생성"""
        history = self.history_dict.get(var_name, [])
        if not history:
            return

        # 팝업 창 설정
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True) # 타이틀바 제거
        
        # 위치 설정 (마우스 클릭 위치 근처)
        popup.geometry(f"250x{min(len(history) * 25, 175)}+{event.x_root}+{event.y_root}")

        listbox = tk.Listbox(popup, font=('Malgun Gothic', 9), bd=1, relief=tk.SOLID)
        listbox.pack(fill=tk.BOTH, expand=True)

        # 최근 10개까지만 역순(최신순)으로 표시
        display_items = history[-10:][::-1]
        for item in display_items:
            listbox.insert(tk.END, item)

        # --- 수정된 내부 선택 로직 ---
        def on_select_item(evt):
            if listbox.curselection():
                index = listbox.curselection()[0]
                selected_val = listbox.get(index)
                
                # 해당하는 Entry 위젯 가져오기
                entry_widget = getattr(self, var_name)
                
                # 값 입력 및 시각적 피드백
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, selected_val)
                entry_widget.config(fg="#0078D4") # 선택된 값은 강조색 적용
                
                popup.destroy()

        # 클릭 또는 엔터 키 입력 시 선택 완료
        listbox.bind("<<ListboxSelect>>", on_select_item)
        listbox.bind("<Return>", on_select_item)
        
        # 포커스를 잃으면 자동으로 닫힘
        listbox.bind("<FocusOut>", lambda e: popup.destroy())
        
        listbox.focus_set()

    def update_history(self, var_name, value):
        """새로운 입력값을 히스토리에 저장 (최대 7개 유지, 중복 제거)"""
        if not value or value.upper() == "NULL": return
        
        if var_name not in self.history_dict:
            self.history_dict[var_name] = []
        
        # 중복 제거 후 추가
        if value in self.history_dict[var_name]:
            self.history_dict[var_name].remove(value)
        
        self.history_dict[var_name].append(value)
        
        # 7개 초과 시 오래된 순으로 삭제
        if len(self.history_dict[var_name]) > 10:
            self.history_dict[var_name].pop(0)

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
        #clean = re.sub(r'[^a-zA-Z0-9가-힣\s\(\)\[\]\&\.\']', ' ', clean).strip()
        clean = regex.sub(r'[^\p{Latin}\p{Hangul}\p{Han}\p{Hiragana}\p{Katakana}\d\s\(\)\[\]\.\&]', ' ', clean).strip()
        
        if src != clean:
            self.ent_title.delete(0, tk.END)
            self.ent_title.insert(0, clean)
            self.ent_title.config(fg="#0078D4")
            self.log(f"최종 정제 결과: '{clean}'")

    def create_control_buttons(self):
        # 상단 일괄 실행 버튼
        ttk.Button(self.button_area, text="🚀 태그 수정 및 파일명 일괄 변경 실행 (선택 항목)", 
                   command=self.run_process).pack(fill=tk.X, ipady=8)
        
        sub = tk.Frame(self.button_area, bg="#FFFFFF")
        sub.pack(fill=tk.X, pady=5)
        
        # 버튼 리스트 구성
        btns = [
            ("🧹 초기화", self.clear_fields_with_color),
            ("🏷️ 모든 파일명 생성", self.generate_all_filenames),
            ("📝 제목 파싱", self.advanced_title_parse),
            ("🌐 검색", self.fetch_online_data),
            ("🔍 자동 매칭", self.start_batch_search)
        ]
        
        for i, (t, c) in enumerate(btns):
            sub.columnconfigure(i, weight=1)
            ttk.Button(sub, text=t, command=c).grid(row=0, column=i, sticky="ew", padx=2)

    def create_grid_area(self):
        g_f = tk.Frame(self.v_paned, bg="white"); self.v_paned.add(g_f, height=550)
        self.cols = ("파일명", "트랙", "제목", "가수", "앨범", "연도", "장르", "비트전송률")
        self.file_grid = ttk.Treeview(g_f, columns=self.cols, show="headings", selectmode="extended")
        self.file_grid.tag_configure('diff', foreground='#0078D4')
        for c in self.cols: 
            self.file_grid.heading(c, text=c, command=lambda _c=c: self.sort_column(_c, False))
            # 열별 너비 및 정렬 설정
            if c == "파일명":
                self.file_grid.column(c, width=300, anchor="w")
            else:
                self.file_grid.column(c, width=80, anchor="center")
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
                fp = os.path.join(path, n)
                # 폴더인 경우
                if os.path.isdir(fp):
                    node = self.dir_tree.insert(p, "end", text=n, values=[fp], tags=('folder',))
                    # 하위 항목이 있는지 확인 (더하기 기호 표시용)
                    try:
                        if os.listdir(fp): self.dir_tree.insert(node, "end")
                    except: pass
                # 음악 파일인 경우 (추가된 로직)
                elif n.lower().endswith(self.supported_ext):
                    self.dir_tree.insert(p, "end", text=n, values=[fp], tags=('file',))
        except Exception as e:
            self.log(f"탐색기 로드 오류: {e}")
        
    def on_dir_open(self, event):
        n = self.dir_tree.focus(); p = self.dir_tree.item(n, "values")[0]
        self.dir_tree.delete(*self.dir_tree.get_children(n)); self.insert_nodes(n, p)
      
    def on_dir_double_click(self, event):
        n = self.dir_tree.identify_row(event.y)
        if not n: return
        
        path = self.dir_tree.item(n, "values")[0]
        
        if os.path.isdir(path):
            # 폴더인 경우: 기존 방식대로 폴더 내 모든 파일 리스트업
            self.selected_path = path
            self.lbl_path.config(text=f"📂 {self.selected_path}")
            self.refresh_grid_list(self.selected_path)
        else:
            # 파일인 경우: 그리드를 비우고 해당 파일 하나만 추가
            self.selected_path = os.path.dirname(path)
            self.lbl_path.config(text=f"📄 {path}")
            self.add_single_file_to_grid(path)

    def add_single_file_to_grid(self, fp):
        """단일 파일 정보를 그리드에 한 줄 추가하는 메서드"""
        self.file_grid.delete(*self.file_grid.get_children())
        self.full_file_paths.clear()
        
        try:
            f = os.path.basename(fp)
            audio = mutagen.File(fp, easy=True)
            info = mutagen.File(fp).info
            
            # --- 트랙 번호 처리 로직 수정 ---
            raw_track = audio.get('tracknumber', ['-'])[0]
            clean_track = raw_track.split('/')[0] if '/' in raw_track else raw_track
            # ------------------------------
            
            v = (
                f, 
                clean_track,
                audio.get('title', ['-'])[0], 
                audio.get('artist', ['-'])[0], 
                audio.get('album', ['-'])[0], 
                audio.get('date', ['-'])[0], 
                audio.get('genre', ['-'])[0], 
                f"{int(info.bitrate/1000)}k"
            )
            item_id = self.file_grid.insert("", "end", values=v)
            self.full_file_paths[item_id] = fp
            # 추가 후 즉시 선택 상태로 만들어 입력창에 반영
            self.file_grid.selection_set(item_id)
            
            # [수정] 소팅 조건 적용
            if self.current_sort["col"]:
                self.sort_column(self.current_sort["col"], self.current_sort["reverse"])
        except Exception as e:
            self.log(f"파일 정보 로드 실패: {e}")
    
    def refresh_grid_list(self, path):
        self.file_grid.delete(*self.file_grid.get_children()); 
        self.full_file_paths.clear()
        
        for r, _, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith(self.supported_ext):
                    fp = os.path.join(r, f)
                    try:
                        a = mutagen.File(fp, easy=True); 
                        info = mutagen.File(fp).info
                        # --- 트랙 번호 처리 로직 수정 ---
                        raw_track = a.get('tracknumber', ['-'])[0]
                        clean_track = raw_track.split('/')[0] if '/' in raw_track else raw_track
                        # ------------------------------
                        v = (f, clean_track, a.get('title', ['-'])[0], a.get('artist', ['-'])[0], a.get('album', ['-'])[0], a.get('date', ['-'])[0], a.get('genre', ['-'])[0], f"{int(info.bitrate/1000)}k")
                        self.full_file_paths[self.file_grid.insert("", "end", values=v)] = fp
                    except: pass
                    
        # [수정] 데이터 로드 후 기존 소팅 조건이 있다면 재적용
        if self.current_sort["col"]:
            self.sort_column(self.current_sort["col"], self.current_sort["reverse"]) 
                    
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
        
        # 그리드에서 선택된 행의 값들 가져오기
        # v[0]: 파일명, v[1]: 트랙, v[2]: 제목, v[3]: 가수, v[4]: 앨범, v[5]: 연도, v[6]: 장르
        v = self.file_grid.item(sel[0], "values")
        
        # --- [로직 추가] 제목이 없는 경우 파일명으로 대체 ---
        display_title = v[2]
        if not display_title or display_title.strip() == "-":
            # 파일명(v[0])에서 확장자를 제외한 순수 이름만 추출
            file_name_only = os.path.splitext(v[0])[0]
            display_title = file_name_only
            self.log(f"정보: 태그 제목이 없어 파일명('{display_title}')을 제목창에 표시합니다.")
        # -----------------------------------------------

        mapping = {
            self.ent_title: display_title, # 수정된 제목 적용
            self.ent_artist: v[3], 
            self.ent_track: v[1], 
            self.ent_album: v[4], 
            self.ent_date: v[5], 
            self.ent_genre: v[6]
        }
        
        for w, val in mapping.items():
            w.delete(0, tk.END)
            cv = "" if val == "-" else val
            
            # 트랙 번호 정수화 처리 (01 -> 1)
            if w == self.ent_track and cv.isdigit():
                cv = str(int(cv))
                
            w.insert(0, cv)
            w.config(fg="black")
            
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
        if not targets:
            return
            
        if messagebox.askyesno("삭제", f"선택한 {len(targets)}개의 파일을 실제 저장소에서 삭제하시겠습니까?"):
            deleted_count = 0
            for i in targets:
                fp = self.full_file_paths.get(i)
                if fp and os.path.exists(fp):
                    try:
                        filename = os.path.basename(fp)
                        os.remove(fp)
                        # 삭제 성공 로그 기록
                        self.log(f"파일 삭제 완료: {filename}")
                        self.file_grid.delete(i)
                        deleted_count += 1
                    except Exception as e:
                        self.log(f"파일 삭제 실패 ({filename}): {e}")
            
            if deleted_count > 0:
                self.log(f"--- 총 {deleted_count}개의 파일이 삭제되었습니다 ---")
    def delete_selected_folder(self):
        item = self.dir_tree.selection()
        if not item: 
            return
            
        tp = self.dir_tree.item(item[0], "values")[0]
        # 루트 디렉토리 삭제 방지 (길이가 3 이하인 경우 예: C:\)
        if len(tp) > 3:
            if messagebox.askyesno("삭제", f"폴더와 그 내부 파일이 모두 삭제됩니다.\n경로: {tp}\n삭제하시겠습니까?"):
                try:
                    shutil.rmtree(tp)
                    # 폴더 삭제 로그 기록
                    self.log(f"폴더 삭제 완료: {tp}")
                    self.dir_tree.delete(item[0])
                    # 그리드 초기화 (삭제된 폴더 내 파일을 보고 있었을 경우 대비)
                    self.file_grid.delete(*self.file_grid.get_children())
                except Exception as e:
                    self.log(f"폴더 삭제 오류: {e}")
    def rename_selected_folder(self):
        item = self.dir_tree.selection()
        if not item: return
        old = self.dir_tree.item(item[0], "values")[0]
        new = simpledialog.askstring("이름 바꾸기", "새 이름:", initialvalue=os.path.basename(old))
        if new:
            new_fp = os.path.join(os.path.dirname(old), new)
            os.rename(old, new_fp); self.on_drive_select(None)
            
            
        
    def get_unique_filename(self, folder, filename):
        """파일명이 중복될 경우 (1), (2) 등을 붙여 고유한 이름을 생성"""
        base, ext = os.path.splitext(filename)
        counter = 1
        unique_name = filename
        
        while os.path.exists(os.path.join(folder, unique_name)):
            unique_name = f"{base} ({counter}){ext}"
            counter += 1
        return unique_name

    def generate_all_filenames(self):
        items = self.file_grid.get_children()
        if not items:
            messagebox.showwarning("알림", "목록에 변경할 파일이 없습니다.")
            return

        if not messagebox.askyesno("확인", "그리드의 정보를 바탕으로 모든 파일명을 일괄 변경하시겠습니까?\n(규칙: 가수명 - 트랙 번호 - 제목)"):
            return

        success_count = 0
        skip_count = 0
        self.log("--- 일괄 파일명 생성 프로세스 시작 ---")

        for item_id in items:
            fp = self.full_file_paths.get(item_id)
            if not fp or not os.path.exists(fp): continue

            # 그리드 값 추출 (v[1]:트랙, v[2]:제목, v[3]:가수)
            v = self.file_grid.item(item_id, "values")
            
            raw_track = v[1].strip()
            raw_title = v[2].strip()
            raw_artist = v[3].strip()

            # --- [핵심 수정: 정보 검증 로직] ---
            # 가수명이나 제목이 비어있거나, 초기값('-')이거나, "NULL"인 경우 건너뜀
            invalid_values = ['', '-', 'NULL', 'Null', 'null']
            if raw_title in invalid_values or raw_artist in invalid_values:
                self.log(f"건너뜀: 필수 정보 부족 (가수: '{raw_artist}', 제목: '{raw_title}')")
                skip_count += 1
                continue
            # ----------------------------------

            # 트랙 번호 처리 (숫자일 경우 두 자리 01, 02... 아니면 00)
            track_str = raw_track.zfill(2) if raw_track.isdigit() else "00"
            
            ext = os.path.splitext(fp)[1]
            # 새 파일명 조립
            new_name_base = f"{raw_artist} - {track_str} - {raw_title}{ext}"
            # 윈도우 파일명 금지 문자 제거
            new_name_base = re.sub(r'[\\/:*?"<>|]', '', new_name_base)
            
            dir_name = os.path.dirname(fp)
            current_name = os.path.basename(fp)

            # 현재 파일명과 바꿀 파일명이 동일하면 스킵
            if current_name == new_name_base:
                success_count += 1 # 이미 변경된 상태로 간주
                continue

            # 중복 체크 후 최종 파일명 확정
            final_name = self.get_unique_filename(dir_name, new_name_base)
            final_path = os.path.join(dir_name, final_name)

            try:
                os.rename(fp, final_path)
                # 데이터 딕셔너리 및 그리드 정보 갱신
                self.full_file_paths[item_id] = final_path
                success_count += 1
                self.log(f"변경 완료: {current_name} -> {final_name}")
            except Exception as e:
                self.log(f"오류 발생 ({current_name}): {e}")

        # 결과 보고
        self.refresh_grid_list(self.selected_path)
        self.log(f"--- 작업 종료: 성공 {success_count}, 건너뜀 {skip_count} ---")
        messagebox.showinfo("완료", f"파일명 변경이 완료되었습니다.\n(성공: {success_count}, 건너뜀: {skip_count})")
            
            
    def run_process(self):
        targets = self.file_grid.selection()
        if not targets: 
            messagebox.showwarning("알림", "수정할 파일을 목록에서 선택해 주세요.")
            return
            
        # [검증] 제목과 가수 정보 가져오기
        current_title = self.ent_title.get().strip()
        current_artist = self.ent_artist.get().strip()
        
        # [추가] 복수 파일 선택 시 제목 입력값 체크 로직
        if len(targets) > 1 and current_title:
            messagebox.showerror("수정 거부", 
                "복수의 파일이 선택된 상태에서는 '제목'을 일괄 수정할 수 없습니다.\n"
                "제목 칸을 비우거나 파일을 하나만 선택해 주세요.")
            return
        
        # 입력창에서 현재 입력된 정보 가져오기
        raw = {k: getattr(self, k).get().strip() for k in ["ent_title", "ent_artist", "ent_track", "ent_album", "ent_genre", "ent_date"]}
        
        success_count = 0
        for item_id in targets:
            fp = self.full_file_paths.get(item_id)
            if not fp or not os.path.exists(fp): continue
            
            try:
                # 1. 태그 수정 및 저장
                audio = mutagen.File(fp, easy=True)
                mapping = {'title': 'ent_title', 'artist': 'ent_artist', 'album': 'ent_album', 
                           'tracknumber': 'ent_track', 'date': 'ent_date', 'genre': 'ent_genre'}
                
                # [데이터 분리 처리]
                raw_track = raw['ent_track']
                tag_track = ""    # 파일 내부 태그용 (정수형 문자열: 1)
                file_track = "00" # 파일 이름용 (두 자리 문자열: 01)
                
                # 복수 선택 시 트랙 번호는 태그에 쓰지 않음
                if len(targets) > 1:
                    tag_track = "" # 빈 값으로 설정하여 기존 태그 유지 또는 무시
                elif raw_track.isdigit():
                    track_int = int(raw_track)
                    tag_track = str(track_int)          # "01" -> "1"
                    file_track = str(track_int).zfill(2) # "1" -> "01"
                    
                for tag, key in mapping.items():
                    if tag == 'tracknumber':
                        val = tag_track
                    else:
                        val = raw[key]
                        
                    if val.upper() == "NULL": 
                        audio.pop(tag, None)
                    elif val: 
                        # 트랙번호는 정수형태로 정제하여 저장
                        audio[tag] = val
                
                audio.save()
                
                # 2. 파일명 일치 여부 확인 및 변경 로직
                # 가수명이나 제목 중 하나라도 비어있거나 "NULL"인 경우 파일명 변경을 수행하지 않음
                if not current_artist or not current_title or \
                   current_artist.upper() == "NULL" or current_title.upper() == "NULL":
                    self.log(f"파일명 유지: 정보 부족 (가수: '{current_artist}', 제목: '{current_title}')")
                    success_count += 1
                    continue # 다음 파일로 넘어감

                # 정보가 모두 있을 경우에만 실행되는 파일명 변경 로직
                dir_name = os.path.dirname(fp)
                ext = os.path.splitext(fp)[1]
                
                # 규칙: 가수명 - 트랙번호 - 제목
                # 값이 비어있을 경우를 대비해 기본값 설정
                new_artist = raw['ent_artist'] if raw['ent_artist'] else "Unknown"
                new_title = raw['ent_title'] if raw['ent_title'] else "Untitled"
                
                # 파일명에는 두 자리(file_track) 사용
                new_filename = f"{new_artist} - {file_track} - {new_title}{ext}"
                new_filename = re.sub(r'[\\/:*?"<>|]', '', new_filename)
                new_fp = os.path.join(dir_name, new_filename)                
                
                # 현재 파일명과 다를 경우에만 이름 변경 실행
                if os.path.normpath(fp) != os.path.normpath(new_fp):
                    # 만약 동일한 이름의 파일이 이미 존재한다면 충돌 방지
                    if os.path.exists(new_fp):
                        self.log(f"중단: 동일 이름의 파일이 이미 존재함 -> {new_filename}")
                    else:
                        os.rename(fp, new_fp)
                        self.log(f"파일명 변경: {os.path.basename(fp)} -> {new_filename}")
                        # 내부 경로 데이터 갱신
                        self.full_file_paths[item_id] = new_fp
                else:
                    self.log(f"태그 수정 완료 (파일명 일치): {new_filename}")
                
                success_count += 1
            except Exception as e:
                self.log(f"오류 발생 ({os.path.basename(fp)}): {e}")

        # 작업 완료 후 입력된 값들을 히스토리에 저장 ---
        for vn in ["ent_title", "ent_artist", "ent_track", "ent_album", "ent_genre", "ent_date"]:
            val = getattr(self, vn).get().strip()
            if val and val.upper() != "NULL":
                self.update_history(vn, val)

        # 작업 완료 후 목록 새로고침
        self.refresh_grid_list(self.selected_path)
        # messagebox.showinfo("완료", f"{success_count}개의 파일 처리가 완료되었습니다.")
        self.log(f"--- 작업 완료: 총 {success_count}개의 파일 처리됨 ---")
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
