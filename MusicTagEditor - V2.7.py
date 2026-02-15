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
import requests  # 추가: 이미지 다운로드용
from PIL import Image, ImageTk  # 추가: 이미지 처리용
from io import BytesIO
import xml.etree.ElementTree as ET


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
            rel_list = res.get('release-list', [{}])
            rel = rel_list[0] if rel_list else {}
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
            
            # release_id를 태그에 저장 (앨범 아트 다운로드용)
            rel_id = rel.get('id', '')
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
            # tags[0]에 저장된 정보를 rel_id로 명시적으로 추출
            rel_id = self.tree.item(sel[0], 'tags')[0]
            # 기존 GUI에서 기대하는 데이터 형식(앨범, 아티스트, 트랙, 연도)으로 슬라이싱하여 전달
            # 노래 제목은 이미 입력창에 있으므로 앨범 정보부터 추출합니다.
            self.result_data = (full_values[1], full_values[2], full_values[3], full_values[4], rel_id)
            self.destroy()

class MusicTagEditorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Music Tag Editor v2.7 (New Features)")
        self.root.geometry("1400x950")
        self.root.configure(bg="#F3F3F3")

        # config.xml 저장 경로: 쓰기 가능한 위치를 실제 테스트로 결정
        self.config_file = self._get_config_path()

        # 시작 시 창 크기/위치만 먼저 설정
        self.load_config_start()

        self.history_dict = {k: [] for k in ["ent_title", "ent_artist", "ent_albumartist", "ent_track", "ent_album", "ent_genre", "ent_date", "ent_keywords"]}
        musicbrainzngs.set_useragent("MyMusicTagTool", "2.7", "rockguy.im@gmail.com")
        self.supported_ext = ('.mp3', '.flac', '.m4a', '.ogg', '.wma', '.wav')
        self.full_file_paths = {}
        self.selected_path = ""

        # 스타일 설정 (버튼 색상 변경을 위함)
        self.style = ttk.Style()
        self.style.theme_use('clam')  # 배경색 변경이 잘 적용되는 clam 테마 권장
        self.style.configure("Action.TButton", 
                             background="#ffcccc", 
                             foreground="black",
                             font=('Malgun Gothic', 9, 'bold'))
        
        # 마우스를 올렸을 때 색상(Hover)도 지정 가능
        self.style.map("Action.TButton",
                       background=[('active', '#ffb3b3')])        
        
        # [추가] 현재 소팅 상태 저장 (컬럼명, 반전 여부)
        self.current_sort = {"col": None, "reverse": False}

        self.current_album_art = None # 메모리 누수 방지용 참조 유지
        
        self.setup_ui()
        self.load_drives()

        # [X] 종료 프로토콜 연결
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # UI가 완전히 그려진 후 세부 설정(폭, 높이 등) 복구
        self.root.after(500, self.load_config_ui_details)

        self.log("시스템 시작: 프로그램이 로드되었습니다.")

    def log(self, msg):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        self.log_area.insert(tk.END, f"{timestamp} {msg}\n")
        self.log_area.see(tk.END)

    def _get_config_path(self):
        """config.xml 저장 경로를 결정한다.

        우선순위:
          1. 스크립트(sys.argv[0]) 위치 폴더  ← 일반 실행 시 가장 자연스러운 위치
          2. __file__ 위치 폴더               ← import 실행 시
          3. 현재 작업 디렉토리
          4. 사용자 홈 디렉토리               ← 최후 보루 (항상 쓰기 가능)

        각 후보에 임시 파일을 실제로 써보아 쓰기 가능 여부를 검증한다.
        """
        import sys

        candidates = []

        try:                                            # 1순위: sys.argv[0]
            p = os.path.dirname(os.path.abspath(sys.argv[0]))
            if os.path.isdir(p):
                candidates.append(p)
        except Exception:
            pass

        try:                                            # 2순위: __file__
            p = os.path.dirname(os.path.abspath(__file__))
            if os.path.isdir(p) and p not in candidates:
                candidates.append(p)
        except NameError:
            pass

        try:                                            # 3순위: cwd
            p = os.path.abspath(os.getcwd())
            if p not in candidates:
                candidates.append(p)
        except Exception:
            pass

        candidates.append(os.path.expanduser("~"))      # 4순위: 홈

        for d in candidates:
            try:
                test = os.path.join(d, ".mte_tmp")
                with open(test, "w") as f:
                    f.write("ok")
                os.remove(test)
                return os.path.join(d, "config.xml")   # 쓰기 가능한 첫 경로
            except Exception:
                continue

        return os.path.join(os.path.expanduser("~"), "config.xml")  # 최후 수단

    def load_config_start(self):
        """프로그램 시작 시 창 크기와 위치를 설정"""
        if os.path.exists(self.config_file):
            try:
                tree = ET.parse(self.config_file)
                root_xml = tree.getroot()
                geo = root_xml.find("geometry").text
                self.root.geometry(geo)
            except:
                self.root.geometry("1400x900") # 에러 발생 시 기본값
        else:
            self.root.geometry("1400x900")

    def load_config_ui_details(self):
        """UI 렌더링 완료 후 Sash·드라이브·폴더 트리·그리드를 복구한다."""
        if not os.path.exists(self.config_file):
            return
        try:
            self.root.update_idletasks()
            xml_root = ET.parse(self.config_file).getroot()

            # ── Sash: 좌우 (main_paned) ───────────────────────
            sm = xml_root.find("sash_main")
            if sm is not None and sm.text:
                try:
                    if hasattr(self, "main_paned"):
                        self.main_paned.sash_place(0, int(sm.text), 0)
                except Exception:
                    pass

            # ── Sash: 상하 (v_paned) ──────────────────────────
            sr = xml_root.find("sash_right")
            if sr is not None and sr.text:
                try:
                    if hasattr(self, "v_paned"):
                        self.v_paned.sash_place(0, 0, int(sr.text))
                except Exception:
                    pass

            # ── 폴더 트리에서 last_folder 복구 ───────────────
            lf_elem = xml_root.find("last_folder")
            last_folder = (lf_elem.text or "").strip() if lf_elem is not None else ""
            if last_folder and os.path.isdir(last_folder):
                self.focus_and_expand_path(last_folder)
                self.log(f"마지막 폴더 복구: {last_folder}")

            # ── 그리드: last_path 폴더의 파일 목록 복구 ─────
            lp = xml_root.find("last_path")
            if lp is not None and lp.text and os.path.isdir(lp.text):
                self.selected_path = lp.text
                self.refresh_grid_list(lp.text)

        except Exception as e:
            print(f"Load Config Error: {e}")

    def save_config(self):
        """현재 화면 구성(창 크기·위치, 드라이브, 폴더, Sash)을 config.xml에 저장.

        각 항목을 독립적인 try/except 로 보호하여,
        일부 수집 실패가 전체 저장 실패로 이어지지 않도록 한다.
        성공·실패 모두 debug.log 파일에 기록한다.
        """
        import traceback
        from datetime import datetime as _dt

        log_path = os.path.join(os.path.dirname(self.config_file), "debug.log")

        def _log(msg):
            try:
                print(msg)
            except Exception:
                pass
            try:
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(f"[{_dt.now():%H:%M:%S}] {msg}\n")
            except Exception:
                pass

        _log("save_config 시작")
        _log(f"저장 경로: {self.config_file}")

        root_xml = ET.Element("config")

        # ── [1] 창 크기/위치 ─────────────────────────────────
        try:
            geo = self.root.geometry()
            if geo:
                ET.SubElement(root_xml, "geometry").text = geo
                _log(f"[1] geometry: {geo}")
        except Exception:
            _log(f"[1] geometry 수집 실패:\n{traceback.format_exc()}")

        # ── [2] 마지막 폴더 경로 ─────────────────────────────
        try:
            lp = getattr(self, "selected_path", "") or ""
            ET.SubElement(root_xml, "last_path").text = str(lp)
            _log(f"[2] last_path: {lp}")
        except Exception:
            _log(f"[2] last_path 수집 실패:\n{traceback.format_exc()}")

        # ── [3] 마지막 선택 드라이브 ─────────────────────────
        try:
            drv = self.drive_combo.get() if hasattr(self, "drive_combo") else ""
            ET.SubElement(root_xml, "last_drive").text = str(drv)
            _log(f"[3] last_drive: {drv}")
        except Exception:
            _log(f"[3] last_drive 수집 실패:\n{traceback.format_exc()}")

        # ── [4] 마지막 선택 폴더 경로 (dir_tree 선택 항목) ──
        try:
            sel = self.dir_tree.selection() if hasattr(self, "dir_tree") else ()
            folder_path = ""
            if sel:
                vals = self.dir_tree.item(sel[0], "values")
                if vals:
                    folder_path = vals[0]
            ET.SubElement(root_xml, "last_folder").text = str(folder_path)
            _log(f"[4] last_folder: {folder_path}")
        except Exception:
            _log(f"[4] last_folder 수집 실패:\n{traceback.format_exc()}")

        # ── [5] 좌우 Sash (main_paned) ───────────────────────
        try:
            if hasattr(self, "main_paned") and self.main_paned.winfo_exists():
                s_main = self.main_paned.sash_coord(0)[0]
                ET.SubElement(root_xml, "sash_main").text = str(s_main)
                _log(f"[5] sash_main: {s_main}")
        except Exception:
            _log(f"[5] sash_main 수집 실패:\n{traceback.format_exc()}")

        # ── [6] 상하 Sash (v_paned) ──────────────────────────
        try:
            if hasattr(self, "v_paned") and self.v_paned.winfo_exists():
                s_right = self.v_paned.sash_coord(0)[1]
                ET.SubElement(root_xml, "sash_right").text = str(s_right)
                _log(f"[6] sash_right: {s_right}")
        except Exception:
            _log(f"[6] sash_right 수집 실패:\n{traceback.format_exc()}")

        # ── [7] XML 파일 기록 ────────────────────────────────
        try:
            tree = ET.ElementTree(root_xml)
            if hasattr(ET, "indent"):
                ET.indent(tree, space="  ")
            tree.write(self.config_file, encoding="utf-8", xml_declaration=True)
            _log(f"[7] 저장 완료: {self.config_file}")
        except Exception:
            _log(f"[7] tree.write 실패:\n{traceback.format_exc()}")
            # 쓰기 권한 없는 경우 홈 디렉토리로 재시도
            try:
                fallback = os.path.join(os.path.expanduser("~"), "MusicTagEditor_config.xml")
                tree.write(fallback, encoding="utf-8", xml_declaration=True)
                self.config_file = fallback
                _log(f"[7] fallback 저장 성공: {fallback}")
            except Exception:
                _log(f"[7] fallback 저장도 실패:\n{traceback.format_exc()}")

    def on_closing(self):
        """프로그램 종료 처리: config 저장 후 창 파괴.

        save_config() 성공·실패 여부와 무관하게
        root.destroy()는 finally 로 반드시 실행된다.
        """
        try:
            from datetime import datetime as _dt
            log_path = os.path.join(os.path.dirname(self.config_file), "debug.log")
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"[{_dt.now():%H:%M:%S}] on_closing 호출됨\n")
        except Exception:
            pass

        try:
            self.save_config()
        except Exception:
            pass
        finally:
            self.root.destroy()

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
                    # dialog.result_data 구조: (앨범명, 아티스트, 트랙번호, 연도, rel_id)
                    alb, artist_name, trk, dat, rel_id = dialog.result_data
                    
                    # 입력 필드 업데이트 (기존 앨범, 연도 외에 '트랙' 추가)
                    self.update_field_with_compare(self.ent_album, alb)
                    self.update_field_with_compare(self.ent_date, dat)
                    
                    # --- [수정 구간: 트랙 번호 입력 추가] ---
                    if trk and trk != '-':
                        self.update_field_with_compare(self.ent_track, trk)
                    # ---------------------------------------
                    
                    # 아티스트 정보도 필요시 업데이트 가능
                    self.update_field_with_compare(self.ent_artist, artist_name)
                    
                    # 검색 결과에서 선택된 Release ID로 이미지 다운로드 시도
                    sel = self.file_grid.selection()
                    if sel:
                        fp = self.full_file_paths.get(sel[0])
                        self.load_album_art(fp, rel_id)
                    
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
        # 그리드의 모든 헤더를 클릭했을 때 호출되는 정렬 메서드
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

    def setup_ui(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # 메인 레이아웃: 좌측(탐색기) | 우측(작업영역)
        self.main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.FLAT, sashwidth=4, bg="#F3F3F3")
        self.main_paned.pack(fill=tk.BOTH, expand=True)
        
        self.left_frame = tk.Frame(self.main_paned, bg="#F3F3F3")
        self.main_paned.add(self.left_frame, width=280)
        self.create_left_widgets()
        
        self.right_frame = tk.Frame(self.main_paned, bg="#FFFFFF")
        self.main_paned.add(self.right_frame)

        # 상단 영역: [입력필드 영역 | 앨범 아트 영역]
        top_container = tk.Frame(self.right_frame, bg="#FFFFFF")
        top_container.pack(fill=tk.X, padx=15, pady=5)
        
        # Tag 입력부 폭 조절 (상대적 비율 유지)
        self.input_area = tk.Frame(top_container, bg="#FFFFFF")
        self.input_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 앨범 아트 표시 레이블
        self.art_size = 250 
        self.art_frame = tk.Frame(top_container, bg="#FFFFFF", width=self.art_size, height=self.art_size, 
                                 highlightbackground="#DDDDDD", highlightthickness=1)
        self.art_frame.pack(side=tk.RIGHT, padx=(15, 0))
        self.art_frame.pack_propagate(False)
        self.lbl_art = tk.Label(self.art_frame, text="No Image", bg="#EEEEEE", font=('Malgun Gothic', 9))
        self.lbl_art.pack(fill=tk.BOTH, expand=True)

        self.create_input_fields()
        
        self.button_area = tk.Frame(self.right_frame, bg="#FFFFFF")
        self.button_area.pack(fill=tk.X, padx=15, pady=2)
        self.create_control_buttons()

        self.v_paned = tk.PanedWindow(self.right_frame, orient=tk.VERTICAL, sashrelief=tk.FLAT, sashwidth=4, bg="#F3F3F3")
        self.v_paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=2)
        self.create_grid_area()
        self.create_log_area()
        self.create_context_menus()

    def create_input_fields(self):
        f_grid = tk.Frame(self.input_area, bg="#FFFFFF")
        f_grid.pack(fill=tk.X)
        
        # 우클릭 메뉴 생성 (복사 기능)
        self.entry_menu = tk.Menu(self.root, tearoff=0)
        self.entry_menu.add_command(label="복사", command=self.copy_text)

        # 필드 구성 정의: (레이블 텍스트, 변수명, CLR 버튼 여부)
        fields = [
            ("제목", "ent_title", False), 
            ("가수", "ent_artist", False), 
            ("앨범음악가", "ent_albumartist", False),
            ("트랙", "ent_track", False), 
            ("앨범", "ent_album", True), 
            ("장르", "ent_genre", True), 
            ("연도", "ent_date", True), 
            ("필터링 키워드", "ent_keywords", False)
        ]

        for i, (lt, vn, cl) in enumerate(fields):
            # 레이블 영역 (텍스트 + CLR 버튼)
            lbl_c = tk.Frame(f_grid, bg="#FFFFFF")
            lbl_c.grid(row=i, column=0, sticky="e", pady=3, padx=(0, 10))
            
            tk.Label(lbl_c, text=lt, font=('Malgun Gothic', 9), bg="#FFFFFF").pack(side=tk.LEFT)
            
            # Entry(입력창) 생성
            ent = tk.Entry(f_grid, font=('Malgun Gothic', 10), relief=tk.SOLID, borderwidth=1)
            setattr(self, vn, ent)
            
            # 1. 우클릭 바인딩 (메뉴 띄우기)
            ent.bind("<Button-3>", self.show_entry_context_menu)
            # 2. 더블 클릭 시 최근 입력 기록 7개 팝업 노출
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
        
        # 필터링 키워드 아래에 파일 경로 표시 영역 ---
        path_frame = tk.Frame(self.input_area, bg="#FFFFFF")
        path_frame.pack(fill=tk.X, pady=(5, 0))
        
        tk.Label(path_frame, text="파일 경로:", font=('Malgun Gothic', 9, 'bold'), 
                 bg="#FFFFFF", fg="#666666").pack(side=tk.LEFT, padx=(10, 5))
        
        # 실제 경로가 출력될 레이블 (초기값은 빈 문자열)
        self.lbl_full_path = tk.Label(path_frame, text="", font=('Consolas', 9), 
                                      bg="#FFFFFF", fg="#0078D4", anchor="w", justify=tk.LEFT)
        self.lbl_full_path.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 그리드 너비 가변 설정
        f_grid.columnconfigure(2, weight=1)

    # --- [입력창에서 우클릭 시 메뉴 표시] ---
    def show_entry_context_menu(self, event):
        self.last_focused_entry = event.widget # 우클릭된 위젯 저장
        self.entry_menu.post(event.x_root, event.y_root)

    def copy_text(self):
        """선택된 텍스트를 클립보드에 복사"""
        try:
            # 포커스된 위젯에서 선택된 영역(Selection) 가져오기
            selected_text = self.last_focused_entry.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
            self.log(f"텍스트 복사 완료: {selected_text}")
        except:
            # 선택된 영역이 없을 경우의 예외 처리
            pass

    # --- 앨범 아트 관련 핵심 메서드 ---
    def load_album_art(self, file_path, release_id=None):
        """로컬 확인 후 없으면 온라인에서 다운로드하여 표시"""
        folder = os.path.dirname(file_path)
        art_files = ['cover.jpg', 'cover.png', 'folder.jpg', 'album.jpg']
        found_path = None

        # 1. 로컬 폴더 검색
        for f in art_files:
            p = os.path.join(folder, f)
            if os.path.exists(p):
                found_path = p
                break
        
        if found_path:
            self.display_image(found_path)
            self.log(f"로컬 이미지 로드: {os.path.basename(found_path)}")
            return

        # 2. 온라인 검색 및 다운로드 (Thread 사용)
        if release_id:
            threading.Thread(target=self.download_album_art, args=(folder, release_id), daemon=True).start()
        else:
            # Release ID가 없으면 기본 이미지 표시
            self.lbl_art.config(image='', text="No Image")

    def download_album_art(self, folder, release_id):
        """Cover Art Archive API를 통해 이미지 다운로드"""
        try:
            self.log(f"온라인 이미지 검색 중... (Release ID: {release_id})")
            url = f"https://coverartarchive.org/release/{release_id}/front-250"
            res = requests.get(url, timeout=10)
            
            if res.status_code == 200:
                save_path = os.path.join(folder, "cover.jpg")
                with open(save_path, "wb") as f:
                    f.write(res.content)
                self.root.after(0, lambda: self.display_image(save_path))
                self.log("앨범 아트 다운로드 완료: cover.jpg")
            else:
                self.root.after(0, lambda: self.lbl_art.config(text="Art Not Found"))
        except Exception as e:
            self.log(f"이미지 다운로드 실패: {e}")

    def display_image(self, img_path):
        """PIL을 사용하여 이미지를 220x220으로 리사이징하여 표시"""
        try:
            img = Image.open(img_path)
            img.thumbnail((self.art_size, self.art_size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.lbl_art.config(image=photo, text="")
            self.current_album_art = photo # 참조 유지
        except Exception as e:
            self.lbl_art.config(text="Error Loading Art")
            self.log(f"이미지 표시 오류: {e}")

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
        # 새로운 입력값을 히스토리에 저장 (최대 7개 유지, 중복 제거)
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
        # 텍스트 파싱 및 트랙 번호 추출 기능
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
        clean = regex.sub(r'[^\p{Latin}\p{Hangul}\p{Han}\p{Hiragana}\p{Katakana}\d\s\(\)\[\]\.\&\']', ' ', clean).strip()
        
        if src != clean:
            self.ent_title.delete(0, tk.END)
            self.ent_title.insert(0, clean)
            self.ent_title.config(fg="#0078D4")
            self.log(f"최종 정제 결과: '{clean}'")

    def create_control_buttons(self):
        # 1. 상단 일괄 실행 버튼 수정
        # style="Action.TButton"을 추가하고, pady(외부 간격)를 1로 조정합니다.
        self.btn_run = ttk.Button(self.button_area, 
                                  text="🚀 태그 수정 및 파일명 일괄 변경 실행 (선택 항목)", 
                                  command=self.run_process,
                                  style="Action.TButton")
        self.btn_run.pack(fill=tk.X, ipady=4, pady=1) # pady를 3~4에서 1로 줄임
        
        # 2. 하단 서브 프레임 수정
        # 버튼과의 간격을 최소화하기 위해 상단 여백(pady의 첫번째 값)을 0 또는 1로 설정
        sub = tk.Frame(self.button_area, bg="#FFFFFF")
        sub.pack(fill=tk.X, pady=(0, 1)) # 위쪽 간격은 0, 아래쪽 간격은 1
        
        # 버튼 리스트 구성
        btns = [
            ("🧹 초기화", self.clear_fields_with_color),
            ("🏷️ 파일명 자동 생성", self.generate_all_filenames),
            ("📝 제목 파싱", self.advanced_title_parse),
            ("🌐 온라인 검색", self.fetch_online_data),
            ("👤 가수 → 앨범음악가", self.copy_artist_to_albumartist)
        ]
        
        for i, (t, c) in enumerate(btns):
            sub.columnconfigure(i, weight=1)
            btn = ttk.Button(sub, text=t, command=c)
            btn.grid(row=0, column=i, sticky="ew", padx=1, ipady=3) # ipady 추가

    def create_grid_area(self):
        g_f = tk.Frame(self.v_paned, bg="white"); self.v_paned.add(g_f, height=550)
        self.cols = ("파일명", "트랙", "제목", "가수", "앨범음악가","앨범", "연도", "장르", "비트전송률")
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
        self.dir_tree.tag_configure('file', foreground='#0078D4') # 파일은 파란색
        self.dir_tree.tag_configure('folder', foreground='#333333') # 폴더는 검정색 

    def create_context_menus(self):
        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="🗑 선택한 파일 삭제", command=self.delete_selected_files)
        self.dir_context_menu = tk.Menu(self.root, tearoff=0)
        self.dir_context_menu.add_command(label="✏️ 이름 바꾸기", command=self.rename_selected_folder)
        self.dir_context_menu.add_command(label="📂 폴더 삭제", command=self.delete_selected_folder)

    def load_drives(self):
        """드라이브 목록을 로드하고, config에 저장된 마지막 드라이브를 선택한다."""
        import string
        from ctypes import windll
        d = [f"{l}:\\" for l, b in zip(string.ascii_uppercase,
             bin(windll.kernel32.GetLogicalDrives())[::-1]) if b == '1']
        self.drive_combo['values'] = d
        if not d:
            return

        # config에서 마지막 드라이브 읽기 시도
        saved_drive = ""
        try:
            if os.path.exists(self.config_file):
                xml_root = ET.parse(self.config_file).getroot()
                ld = xml_root.find("last_drive")
                if ld is not None and ld.text:
                    saved_drive = ld.text.strip()
        except Exception:
            pass

        # 저장된 드라이브가 현재 드라이브 목록에 있으면 선택, 없으면 첫 번째
        if saved_drive in d:
            self.drive_combo.set(saved_drive)
        else:
            self.drive_combo.current(0)

        self.on_drive_select(None)

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
            self.refresh_grid_list(self.selected_path)
        else:
            # 파일인 경우: 그리드를 비우고 해당 파일 하나만 추가
            self.selected_path = os.path.dirname(path)
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
                audio.get('albumartist', ['-'])[0], 
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
                        v = (f, clean_track, a.get('title', ['-'])[0], a.get('artist', ['-'])[0], a.get('albumartist', ['-'])[0],a.get('album', ['-'])[0], a.get('date', ['-'])[0], a.get('genre', ['-'])[0], f"{int(info.bitrate/1000)}k")
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
        v = self.file_grid.item(sel[0], "values")
        fp = self.full_file_paths.get(sel[0])  # 선택된 아이템의 실제 경로 가져오기
        
        # 파일 경로 레이블 업데이트 ---
        if fp:
            self.lbl_full_path.config(text=fp)
        else:
            self.lbl_full_path.config(text="")

        # --- [로직 수정 및 강화] 제목 판별부 ---
        raw_title = v[2].strip()
        file_name_only = os.path.splitext(v[0])[0]  
        
        # 깨진 문자열 판별 함수 (정규식 활용)
        def is_broken_string(s):
            """비정상적인 인코딩(깨진 문자)을 검출하는 정밀 로직"""
            if not s or s == "-": return True
            if '\ufffd' in s: return True # 유니코드 대체 문자 확인
            
            # 1. 정상 문자군 정의 (한글, 영어, 숫자, 기본 문장부호)
            # regex 라이브러리의 유니코드 속성 활용
            valid_pattern = regex.compile(r'[\p{Hangul}\p{Latin}\d\s\(\)\[\]\.\&\!\?\-\_\,\'\"]+')
            valid_chars = "".join(valid_pattern.findall(s))
            
            # 2. 비정상 문자군 정의 (인코딩 깨짐 시 주로 나타나는 라틴 확장 기호 및 특수 기호)
            # 사용자가 제시한 ´, °, ¸, ¾ 등 ASCII 범위를 벗어난 기호들 감시
            broken_pattern = regex.compile(r'[^\p{Hangul}\p{ASCII}\p{Hiragana}\p{Katakana}\p{Han}]+')
            broken_chars = "".join(broken_pattern.findall(s))
            
            # 판별 기준 A: 전체 길이 대비 정상 문자 비율이 너무 낮음 (50% 미만)
            if len(s) > 0:
                valid_ratio = len(valid_chars) / len(s)
                if valid_ratio < 0.5:
                    return True
            
            # 판별 기준 B: 깨진 문자 기호(라틴 확장 등)가 30% 이상 포함됨
            if len(s) > 0:
                broken_ratio = len(broken_chars) / len(s)
                if broken_ratio > 0.3:
                    return True
                    
            # 판별 기준 C: 특정 깨진 패턴의 연속성 (예: ´Ï°¡ 처럼 기호와 문자가 뒤섞임)
            # 일반적인 한국어/영어 문장에서는 발생하기 힘든 조합을 체크
            if regex.search(r'[^\x00-\x7F][^\x00-\x7F]{2,}', s):
                # 비-ASCII 문자가 의미 없이 나열되는 경우 (정상 한글 제외 필터 필요)
                # 한글은 \p{Hangul}로 이미 valid_chars에서 걸러지므로 
                # 남은 문자열 중 연속된 비정상 기호 확인
                remaining = regex.sub(r'[\p{Hangul}\s\d\p{Latin}]+', '', s)
                if len(remaining) > len(s) * 0.2:
                    return True

            return False
        
        if is_broken_string(raw_title):
            display_title = file_name_only
            self.log(f"⚠️ 깨진 타이틀 감지: '{raw_title[:15]}...' -> 파일명으로 대체 표시")
        else:
            display_title = raw_title

        mapping = {
            self.ent_title: display_title, # 수정된 제목 적용
            self.ent_artist: v[3], 
            self.ent_albumartist: v[4], 
            self.ent_track: v[1], 
            self.ent_album: v[5], 
            self.ent_date: v[6], 
            self.ent_genre: v[7]
        }
        
        for w, val in mapping.items():
            w.delete(0, tk.END)
            cv = "" if val == "-" else val
            
            # 트랙 번호 정수화 처리 (01 -> 1)
            if w == self.ent_track and cv.isdigit():
                cv = str(int(cv))
                
            w.insert(0, cv)
            w.config(fg="black")
            
        # 앨범 아트 로드 시도
        if fp:
            self.load_album_art(fp)
            
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
        
        # 선택된 노드의 현재 정보 안전하게 가져오기
        item_values = self.dir_tree.item(item[0], "values")
        if not item_values: return
        
        old_path = item_values[0]
        old_name = os.path.basename(old_path)
        parent_dir = os.path.dirname(old_path)

        # 팝업창 가로 넓이 확보를 위해 구분선 추가
        new_name = simpledialog.askstring("이름 바꾸기", 
                                          f"현재 폴더명: {old_name}\n" + "-"*60 + 
                                          "\n새로운 폴더 이름을 입력하세요:", 
                                          initialvalue=old_name)
        
        if new_name and new_name != old_name:
            new_path = os.path.join(parent_dir, new_name)
            try:
                os.rename(old_path, new_path)
                self.log(f"폴더명 변경 완료: {old_name} -> {new_name}")
                
                # [에러 해결 핵심] 트리를 완전히 새로 고친 후 타겟 폴더 탐색
                self.refresh_and_expand_target_only(new_path)
                
            except Exception as e:
                self.log(f"폴더명 변경 오류: {e}")
                messagebox.showerror("오류", f"이름을 바꿀 수 없습니다: {e}")

    def refresh_and_expand_target_only(self, target_path):
        """트리를 재로드하고 이름이 변경된 해당 폴더만 정확히 확장함"""
        # 1. 트리 초기화 및 드라이브부터 다시 로드 (무효화된 인덱스 정리)
        self.on_drive_select(None)
        
        # 2. 변경된 폴더 경로로 가는 길목만 찾아 확장 (비동기적 처리 방지를 위해 약간의 지연 권장하나 직접 호출)
        self.root.update_idletasks() # UI 강제 업데이트로 노드 생성 보장
        self.focus_and_expand_path(target_path)

    def focus_and_expand_path(self, target_path):
        """트리 노드를 순회하며 타겟 경로만 확장"""
        target_path = os.path.normpath(target_path)
        
        def search_node(parent):
            for child in self.dir_tree.get_children(parent):
                node_values = self.dir_tree.item(child, "values")
                if not node_values: continue
                
                node_path = os.path.normpath(node_values[0])
                
                # 현재 노드가 타겟 경로의 일부이거나 타겟 자체인 경우
                if target_path.startswith(node_path):
                    # 자식 노드들을 먼저 로드하기 위해 확장 (on_dir_open의 기능 수행)
                    self.dir_tree.item(child, open=True)
                    self.on_dir_open_manual(child) # 수동으로 하위 노드 생성 유도
                    
                    # 정확히 일치하는 폴더를 찾은 경우
                    if node_path == target_path:
                        self.dir_tree.selection_set(child)
                        self.dir_tree.focus(child)
                        self.dir_tree.see(child)
                        return True
                    
                    # 하위 단계 탐색 계속
                    if search_node(child):
                        return True
            return False

        search_node('') # 루트부터 탐색 시작

    def on_dir_open_manual(self, item_id):
        """이벤트 없이 수동으로 노드를 확장할 때 하위 목록을 로드하는 헬퍼"""
        values = self.dir_tree.item(item_id, "values")
        if values:
            path = values[0]
            self.dir_tree.delete(*self.dir_tree.get_children(item_id))
            self.insert_nodes(item_id, path)
         
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
        raw = {k: getattr(self, k).get().strip() for k in ["ent_title", "ent_artist", "ent_albumartist", "ent_track", "ent_album", "ent_genre", "ent_date"]}
        
        success_count = 0
        for item_id in targets:
            fp = self.full_file_paths.get(item_id)
            if not fp or not os.path.exists(fp): continue
            
            try:
                # 1. 태그 수정 및 저장
                audio = mutagen.File(fp, easy=True)
                mapping = {'title': 'ent_title', 'artist': 'ent_artist', 'albumartist': 'ent_albumartist', 'album': 'ent_album', 
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
        for vn in ["ent_title", "ent_artist", "ent_albumartist", "ent_track", "ent_album", "ent_genre", "ent_date"]:
            val = getattr(self, vn).get().strip()
            if val and val.upper() != "NULL":
                self.update_history(vn, val)

        # 작업 완료 후 목록 새로고침
        self.refresh_grid_list(self.selected_path)
        # messagebox.showinfo("완료", f"{success_count}개의 파일 처리가 완료되었습니다.")
        self.log(f"--- 작업 완료: 총 {success_count}개의 파일 처리됨 ---")

    def copy_artist_to_albumartist(self):
        """가수 정보를 앨범음악가로 복사 (MP3 프레임 오류 및 모든 포맷 대응)"""
        selected_items = self.file_grid.selection()
        if not selected_items:
            messagebox.showwarning("알림", "정보를 복사할 음악을 리스트에서 선택해 주세요.")
            return

        success_count = 0
        for item_id in selected_items:
            fp = self.full_file_paths.get(item_id)
            if not fp or not os.path.exists(fp): continue

            grid_values = self.file_grid.item(item_id, "values")
            grid_artist = grid_values[3].strip() if len(grid_values) > 3 else ""

            try:
                # 1. 가수 정보 확보 (그리드 우선 참조로 안정성 확보)
                artist_val = grid_artist if grid_artist and grid_artist != "-" else ""
                
                # 만약 그리드에 정보가 없다면 파일 태그 직접 읽기 시도
                if not artist_val:
                    audio_read = mutagen.File(fp)
                    if audio_read and 'artist' in audio_read and audio_read['artist']:
                        artist_val = audio_read['artist'][0]

                if artist_val:
                    self.log(f"복사 시도: {os.path.basename(fp)} (값: {artist_val})")
                    
                    # [핵심 수정] 파일 확장자에 따른 분기 처리
                    if fp.lower().endswith('.mp3'):
                        # MP3는 EasyID3를 통해 프레임 에러를 방지 (문자열로 직접 입력)
                        from mutagen.easyid3 import EasyID3
                        audio = EasyID3(fp)
                        audio['albumartist'] = artist_val  # 리스트가 아닌 문자열로 전달
                        audio.save()
                    else:
                        # FLAC, OGG 등은 Vorbis Comment 표준에 따라 리스트 형식 사용
                        audio = mutagen.File(fp)
                        audio['albumartist'] = [artist_val]
                        audio.save()

                    # UI 즉시 업데이트
                    new_values = list(grid_values)
                    new_values[4] = artist_val
                    self.file_grid.item(item_id, values=new_values)
                    
                    self.log(f"복사 완료: {os.path.basename(fp)}")
                    success_count += 1
                else:
                    self.log(f"정보 없음: {os.path.basename(fp)}")

            except Exception as e:
                self.log(f"복사 오류({os.path.basename(fp)}): {e}")

        if success_count > 0:
            self.log(f"--- 작업 완료: {success_count}개 파일 처리됨 ---")
            if len(selected_items) == 1:
                self.on_grid_click_or_select()

    def load_filename_to_title(self):
        sel = self.file_grid.selection()
        if sel: 
            f = os.path.splitext(self.file_grid.item(sel[0], "values")[0])[0]
            self.ent_title.delete(0, tk.END); self.ent_title.insert(0, f)

if __name__ == "__main__":
    root = tk.Tk()
    MusicTagEditorGUI(root)
    root.mainloop()