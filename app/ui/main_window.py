# app/ui/main_window.py
# 이 파일은 비급 최적화 도구의 메인 PySide6 UI를 정의합니다.
# 상단 입력 섹션(현재값/목표값/희귀도 제한)과 하단 결과 섹션(상태/추천 목록/요약)을 구성합니다.

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMenu,
    QDialog,
    QTextEdit, QAbstractItemView, QListWidget, QListWidgetItem, QRadioButton, QButtonGroup
)
from PySide6.QtGui import QColor, QPalette

from app.loaders import load_json
from app.translator import load_kr_dict, translate
from app.normalizer import normalize_skill
from app.grouper import group_skills
from app.optimizer import (
    STAT_ORDER,
    StatBlock,
    GoalConfig,
    RarityConstraint,
)
from app.snapshot import (
    apply_book_actions_until,
)
from app.greedy_optimizer import optimize_greedy_actions
from app.settings_store import load_settings, save_settings
from app.constants import RARITY_ORDER, RARITY_COLORS, RARITY_DEFAULT_COUNTS, ATTRIBUTE_STATS, MARTIAL_STATS, \
    STAT_SECTIONS


def format_growth_text(delta: Dict[str, int], potential: bool = False) -> str:
    """
    증가 벡터를 보기 좋은 문자열로 변환합니다.

    Args:
        delta: 증가량 dict
        potential: 잠재력 표시 여부

    Returns:
        str: 예) "근력+1, 검+2" / "검 잠재력+1, 민첩 잠재력+1"
    """
    if not delta:
        return "-"

    parts = []
    for stat, value in sorted(delta.items(), key=lambda x: x[0]):
        if potential:
            parts.append(f"{stat} 잠재력+{value}")
        else:
            parts.append(f"{stat}+{value}")
    return ", ".join(parts)


# 한글입력 즉시 갱신용
class ImeAwareLineEdit(QLineEdit):
    """
    IME(입력기) 입력 텍스트 처리에 특화된 QLineEdit 클래스입니다.

    이 클래스는 QLineEdit의 동작을 커스터마이징하여 IME에서 제공하는 조합 중인 텍스트(preedit text)를 처리하며,
    IME 상호작용으로 인해 전체 텍스트가 변경될 때마다 사용자 정의 시그널을 발생시킵니다.

    :ivar imeTextChanged: IME 텍스트가 변경될 때 발생하는 시그널입니다.
                          기존 텍스트와 조합 중인 텍스트, 그리고 커서 위치가 결합된 문자열을 전달합니다.
    :type imeTextChanged: Signal
    """
    imeTextChanged = Signal(str)

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)

        text = self.text()
        preedit = event.preeditString()

        cursor = self.cursorPosition()
        combined = text[:cursor] + preedit + text[cursor:]

        self.imeTextChanged.emit(combined)


class MainWindow(QMainWindow):
    """
    비급 최적화 메인 윈도우입니다.
    """

    def __init__(self):
        super().__init__()

        self.state_table = None
        self.target_table = None
        self.current_table = None
        self.setWindowTitle("비급 최적화 도구 by HexX")
        self.resize(1650, 980)

        # 핵심 데이터 캐시
        self.skills = []
        self.groups = []
        self.initial_state: StatBlock | None = None
        self.result_actions = []
        self.kr_dict = {}
        self.excluded_skill_ids = set()
        self.plan_name_combo = None
        self.current_tables = {}
        self.target_tables = {}
        self.state_tables = {}
        # 선택한 비급 상태변수 (중복선택 방지용)
        self._updating_combo = False
        self._last_combo_indices = {}
        # 완료 체크용
        self.completed_action_rows = set()
        # 추가 / 제외 필터용
        self.skill_filter_rules = [
            {"action": "include", "kind": "all", "label": "전체"}
        ]
        # 결과 캐시
        self.result_groups = []

        self.settings = load_settings()

        self._build_ui()

        # 기본 경로 자동 입력
        self.json_path_edit.setText(self.settings.get("json_path", "data/martial_skills.json"))
        self.dict_path_edit.setText(self.settings.get("dict_path", "data/kr_dict.lua"))

        self.DISABLED_STAT_FG = QColor("#8A8A8A")  # 목표 제외 스탯
        self.CHANGED_STAT_FG = QColor("#6BB6FF")  # 선택 행에서 상승한 값
        self.NORMAL_STAT_FG = self.palette().color(QPalette.ColorRole.WindowText)  # 윈도우 기본값

        # UI 실행 후 자동 로드
        self._load_data(silent=True)

    # 메인 UI 레이아웃
    def _build_ui(self):
        """
        메인 UI 레이아웃을 구성합니다.
        """
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)

        # 상단 파일/실행 바
        top_bar = self._build_top_bar()
        root.addLayout(top_bar)

        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, 1)

        # 상단 섹션
        top_section = QWidget()
        top_layout = QHBoxLayout(top_section)

        self.current_group = self._build_current_group()
        self.target_group = self._build_target_group()
        self.rarity_group = self._build_rarity_group()

        top_layout.addWidget(self.current_group, 2)
        top_layout.addWidget(self.target_group, 2)
        top_layout.addWidget(self.rarity_group, 1)

        splitter.addWidget(top_section)

        # 하단 섹션
        bottom_section = QWidget()
        bottom_layout = QHBoxLayout(bottom_section)

        self.state_group = self._build_state_group()
        self.result_group = self._build_result_group()

        bottom_layout.addWidget(self.state_group, 1)
        bottom_layout.addWidget(self.result_group, 2)

        splitter.addWidget(bottom_section)
        splitter.setSizes([420, 560])

    def _build_top_bar(self):
        """
        파일 경로 입력 및 실행 버튼 바를 생성합니다.
        """
        layout = QGridLayout()

        self.json_path_edit = QLineEdit("data/martial_skills.json")
        self.dict_path_edit = QLineEdit("data/kr_dict.lua")
        self.btn_settings = QPushButton("환경설정")
        self.btn_settings.clicked.connect(self._open_settings_dialog)

        self.btn_solve = QPushButton("최적화 실행")
        self.btn_solve.clicked.connect(self._solve)
        self.btn_solve.setEnabled(False)

        self.status_label = QLabel("데이터를 로드하세요.")

        layout.addWidget(self.btn_solve, 1, 3)
        layout.addWidget(self.status_label, 0, 4, 2, 1)

        layout.addWidget(self.btn_settings, 0, 3)
        layout.addWidget(self.btn_solve, 1, 4)
        layout.addWidget(self.status_label, 0, 5, 2, 1)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(4, 1)

        self.plan_name_combo = QComboBox()

        self.btn_plan_save = QPushButton("저장")
        self.btn_plan_save.clicked.connect(self._save_plan)

        self.btn_plan_load = QPushButton("불러오기")
        self.btn_plan_load.clicked.connect(self._load_plan)

        self.btn_plan_delete = QPushButton("삭제")
        self.btn_plan_delete.clicked.connect(self._delete_plan)

        layout.addWidget(QLabel("플랜"), 2, 0)
        layout.addWidget(self.plan_name_combo, 2, 1)
        layout.addWidget(self.btn_plan_load, 2, 2)
        layout.addWidget(self.btn_plan_save, 2, 3)
        layout.addWidget(self.btn_plan_delete, 2, 4)

        return layout

    def _open_settings_dialog(self):
        """
        JSON / KR_DICT 경로를 설정하는 환경설정 다이얼로그입니다.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("환경설정")
        dlg.resize(720, 180)

        layout = QGridLayout(dlg)

        json_edit = QLineEdit(self.json_path_edit.text())
        dict_edit = QLineEdit(self.dict_path_edit.text())

        btn_json = QPushButton("선택")
        btn_dict = QPushButton("선택")

        def pick_json():
            path, _ = QFileDialog.getOpenFileName(dlg, "비급 JSON 선택", "", "JSON Files (*.json)")
            if path:
                json_edit.setText(path)

        def pick_dict():
            path, _ = QFileDialog.getOpenFileName(dlg, "KR_DICT Lua 선택", "", "Lua Files (*.lua);;All Files (*.*)")
            if path:
                dict_edit.setText(path)

        btn_json.clicked.connect(pick_json)
        btn_dict.clicked.connect(pick_dict)

        btn_save = QPushButton("저장 후 다시 로드")
        btn_cancel = QPushButton("취소")

        def save_and_reload():
            self.json_path_edit.setText(json_edit.text().strip())
            self.dict_path_edit.setText(dict_edit.text().strip())

            self.settings["json_path"] = self.json_path_edit.text().strip()
            self.settings["dict_path"] = self.dict_path_edit.text().strip()
            save_settings(self.settings)

            dlg.accept()
            self._load_data(silent=False)

        btn_save.clicked.connect(save_and_reload)
        btn_cancel.clicked.connect(dlg.reject)

        layout.addWidget(QLabel("비급 JSON"), 0, 0)
        layout.addWidget(json_edit, 0, 1)
        layout.addWidget(btn_json, 0, 2)

        layout.addWidget(QLabel("KR_DICT Lua"), 1, 0)
        layout.addWidget(dict_edit, 1, 1)
        layout.addWidget(btn_dict, 1, 2)

        layout.addWidget(btn_save, 2, 1)
        layout.addWidget(btn_cancel, 2, 2)

        dlg.exec()

    # 툴팁 UI
    @staticmethod
    def _make_skill_tooltip(skill, group) -> str:
        """
        비급 hover tooltip 내용을 생성합니다.
        """
        needs = skill.needs if skill.needs else "없음"

        return (
            f"<b>{skill.name}</b><br>"
            f"ID: {skill.id}<br>"
            f"희귀도: {skill.rare}<br>"
            f"종류: {skill.type_name}<br>"
            f"출처: {skill.force_name}<br>"
            f"요구치: {needs}<br>"
            f"현재 증가: {format_growth_text(group.delta_current, potential=False)}<br>"
            f"잠재 증가: {format_growth_text(group.delta_potential, potential=True)}"
        )

    # 데이터 채우기
    def _build_current_group(self):
        """
        현재값 입력 섹션을 속성 / 무학 2열로 구성합니다.
        """
        box = QGroupBox("현재값")
        outer = QHBoxLayout(box)

        self.current_tables = {}

        for title, stats in STAT_SECTIONS:
            sub_box = QGroupBox(title)
            layout = QVBoxLayout(sub_box)

            table = QTableWidget(len(stats), 3)
            table.setHorizontalHeaderLabels(["항목", "현재값", "잠재력"])
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

            for row, stat in enumerate(stats):
                self.add_item(table, row, 0, stat)
                self.add_item(table, row, 1, "10", editable=True)
                self.add_item(table, row, 2, "60", editable=True)

            layout.addWidget(table)
            outer.addWidget(sub_box)

            self.current_tables[title] = table

        return box

    def _build_target_group(self):
        """
        목표값 입력 섹션을 속성 / 무학 2열로 구성합니다.
        체크박스 전체 선택 / 전체 해제를 제공합니다.
        """
        box = QGroupBox("목표값")
        outer = QVBoxLayout(box)

        btn_layout = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")

        btn_all.clicked.connect(lambda: self._set_all_target_checks(True))
        btn_none.clicked.connect(lambda: self._set_all_target_checks(False))

        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch(1)

        btn_filter = QPushButton("비급 포함/제외 관리")
        btn_filter.clicked.connect(self._open_skill_filter_dialog)

        btn_layout.addWidget(btn_filter)

        outer.addLayout(btn_layout)

        tables_layout = QHBoxLayout()
        self.target_tables = {}

        for title, stats in STAT_SECTIONS:
            sub_box = QGroupBox(title)
            layout = QVBoxLayout(sub_box)

            table = QTableWidget(len(stats), 4)
            table.setHorizontalHeaderLabels(["사용", "항목", "목표 현재값", "목표 잠재력"])
            table.verticalHeader().setVisible(False)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.Stretch)
            header.setSectionResizeMode(0, QHeaderView.Fixed)
            table.setColumnWidth(0, 42)  # 사용 체크박스

            for row, stat in enumerate(stats):
                wrapper, chk = self._make_centered_checkbox(True)
                table.setCellWidget(row, 0, wrapper)

                self.add_item(table, row, 1, stat)
                self.add_item(table, row, 2, "120", editable=True)
                self.add_item(table, row, 3, "120", editable=True)

            layout.addWidget(table)
            tables_layout.addWidget(sub_box)

            self.target_tables[title] = table

        outer.addLayout(tables_layout)
        return box

    def _build_rarity_group(self):
        """
        희귀도별 최대 사용 권수 섹션을 생성합니다.
        "희귀도 제한"
        """
        box = QGroupBox("희귀도 제한")
        outer = QVBoxLayout(box)

        btn_layout = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")

        btn_all.clicked.connect(lambda: self._set_all_rarity_checks(True))
        btn_none.clicked.connect(lambda: self._set_all_rarity_checks(False))

        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch(1)

        outer.addLayout(btn_layout)

        self.rarity_table = QTableWidget(0, 3)
        self.rarity_table.setHorizontalHeaderLabels(["사용", "희귀도", "최대 권수"])
        self.rarity_table.verticalHeader().setVisible(False)
        header_rarity_table = self.rarity_table.horizontalHeader()
        header_rarity_table.setSectionResizeMode(QHeaderView.Stretch)
        header_rarity_table.setSectionResizeMode(0, QHeaderView.Fixed)
        self.rarity_table.setColumnWidth(0, 42)

        outer.addWidget(self.rarity_table)
        return box

    def _set_all_rarity_checks(self, checked: bool):
        """
        희귀도 제한 섹션의 모든 사용 체크박스를 선택/해제합니다.
        """
        for row in range(self.rarity_table.rowCount()):
            wrapper = self.rarity_table.cellWidget(row, 0)
            chk = getattr(wrapper, "checkbox", None)
            if isinstance(chk, QCheckBox):
                chk.setChecked(checked)

    def _build_state_group(self):
        """
        누적 상태 섹션을 속성 / 무학 2열로 구성합니다.
        """
        box = QGroupBox("누적 상태")
        outer = QHBoxLayout(box)

        self.state_tables = {}

        for title, stats in STAT_SECTIONS:
            sub_box = QGroupBox(title)
            layout = QVBoxLayout(sub_box)

            table = QTableWidget(len(stats), 3)
            table.setHorizontalHeaderLabels(["항목", "현재값", "잠재력"])
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

            for row, stat in enumerate(stats):
                table.setItem(row, 0, QTableWidgetItem(stat))
                table.setItem(row, 1, QTableWidgetItem("10"))
                table.setItem(row, 2, QTableWidgetItem("60"))

            layout.addWidget(table)
            outer.addWidget(sub_box)

            self.state_tables[title] = table

        return box

    def _on_result_cell_clicked(self, row: int, col: int):
        """
        결과 테이블 셀 클릭 시 해당 행까지의 누적 상태를 반영합니다.
        QComboBox 셀이 selectionChanged를 발생시키지 않는 경우를 보완합니다.
        """
        self._apply_result_row_state(row)

    # 누적 상태 반영 함수
    def _apply_result_row_state(self, row: int):
        """
        결과 목록의 특정 행까지 액션을 적용한 누적 상태를 좌측 상태표에 반영합니다.
        """
        if self.initial_state is None or row < 0 or row >= len(self.result_actions):
            return

        # 0행부터 현재 행까지의 상태 계산
        state = apply_book_actions_until(
            initial_state=self.initial_state,
            groups=self.result_groups,
            actions=self.result_actions,
            count=row + 1,
        )

        # ✅ 핵심 수정: '현재 행'에서 실제로 증가하는 값(delta)을 추출하여 강조 표시 데이터로 전달
        action = self.result_actions[row]
        group = self.result_groups[action.group_index]

        changed_info = {}
        for stat in group.delta_current:
            if group.delta_current[stat] > 0:
                changed_info.setdefault(stat, {})["current"] = True
        for stat in group.delta_potential:
            if group.delta_potential[stat] > 0:
                changed_info.setdefault(stat, {})["potential"] = True

        self._update_state_table(state, changed=changed_info)

    # 그룹 상세 정보 팝업창
    def _show_group_detail_dialog(self, row: int):
        """
        선택한 결과 행의 성장치 그룹 상세 정보를 표시합니다.
        """
        if row < 0 or row >= len(self.result_actions):
            return

        action = self.result_actions[row]
        group = self.result_groups[action.group_index]

        dlg = QDialog(self)
        dlg.setWindowTitle("그룹 상세 보기")
        dlg.resize(720, 520)

        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)

        lines = []
        lines.append("[성장치 그룹 상세]")
        lines.append("")
        lines.append(f"그룹 수량: {group.count}")
        lines.append(f"현재 증가: {format_growth_text(group.delta_current, potential=False)}")
        lines.append(f"잠재 증가: {format_growth_text(group.delta_potential, potential=True)}")
        lines.append("")
        lines.append("[그룹 내 비급 목록]")

        for idx, sk in enumerate(group.skills, start=1):
            needs = sk.needs if sk.needs else "없음"
            lines.append(
                f"{idx}. [{sk.rare}] {sk.name} / ID: {sk.id} / 종류: {sk.type_name} / 출처: {sk.force_name} / 요구치: {needs}"
            )

        text.setPlainText("\n".join(lines))

        layout.addWidget(text)

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.exec()

    # 우클릭 메뉴
    def _open_result_context_menu(self, pos):
        """
        결과 테이블 우클릭 메뉴를 엽니다.
        """
        row = self.result_table.rowAt(pos.y())
        if row < 0 or row >= len(self.result_actions):
            return

        self.result_table.selectRow(row)

        menu = QMenu(self)
        act_detail = menu.addAction("그룹 상세 보기")

        action = menu.exec(self.result_table.viewport().mapToGlobal(pos))

        if action == act_detail:
            self._show_group_detail_dialog(row)

    # ─ 결과창 관련 함수
    def _build_result_group(self):
        """
        결과창
        :return:
        """
        box = QGroupBox("추천 비급 목록 / 사용 요약")
        layout = QVBoxLayout(box)

        # 결과 테이블
        self.result_table = QTableWidget(0, 11)
        self.result_table.setHorizontalHeaderLabels(
            ["완료", "순서", "희귀도", "비급명", "종류", "출처", "사용 단계", "책 번호", "그룹 수량", "현재 증가", "잠재 증가"]
        )

        header_result_table = self.result_table.horizontalHeader()
        header_result_table.setSectionResizeMode(QHeaderView.Interactive)
        self.result_table.setColumnWidth(0, 42)  # 완료
        self.result_table.setColumnWidth(1, 48)  # 순서
        self.result_table.setColumnWidth(2, 70)  # 희귀도
        self.result_table.setColumnWidth(3, 120)  # 비급명
        self.result_table.setColumnWidth(4, 70)  # 종류
        self.result_table.setColumnWidth(5, 90)  # 출처
        self.result_table.setColumnWidth(6, 70)  # 사용 단계
        self.result_table.setColumnWidth(7, 70)  # 그룹 내 권
        self.result_table.setColumnWidth(8, 70)  # 그룹 수량

        self.result_table.verticalHeader().setVisible(False)
        stretch_columns = [9, 10]
        for col in stretch_columns:
            header_result_table.setSectionResizeMode(col, QHeaderView.Stretch)
        self.result_table.itemSelectionChanged.connect(self._on_result_selection_changed)
        # TODO 결과 테이블에서 행 클릭시 누적변경 되는 이벤트 연결부분 현재 체크박스로 대체하여 제외 중
        # self.result_table.cellClicked.connect(self._on_result_cell_clicked)

        self.result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_table.customContextMenuRequested.connect(self._open_result_context_menu)

        # 하단 요약 영역
        summary_splitter = QSplitter(Qt.Horizontal)

        rarity_box = QGroupBox("희귀도별 사용 권수")
        rarity_layout = QVBoxLayout(rarity_box)
        self.rarity_summary_table = QTableWidget(0, 3)
        self.rarity_summary_table.setHorizontalHeaderLabels(["희귀도", "사용 권수", "총 단계"])
        self.rarity_summary_table.verticalHeader().setVisible(False)
        self.rarity_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        rarity_layout.addWidget(self.rarity_summary_table)

        books_box = QGroupBox("사용된 비급 목록")
        books_layout = QVBoxLayout(books_box)
        self.books_summary_table = QTableWidget(0, 6)
        self.books_summary_table.setHorizontalHeaderLabels(
            ["완료", "희귀도", "비급명", "종류", "출처", "총 단계"]
        )
        self.books_summary_table.verticalHeader().setVisible(False)
        self.books_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        header_books_summary_table = self.books_summary_table.horizontalHeader()
        fixed_columns = [0]
        for col in fixed_columns:
            header_books_summary_table.setSectionResizeMode(col, QHeaderView.Fixed)
        books_layout.addWidget(self.books_summary_table)
        self.books_summary_table.setColumnWidth(0, 48)  # 완료 체크박스

        summary_splitter.addWidget(rarity_box)
        summary_splitter.addWidget(books_box)
        summary_splitter.setSizes([300, 700])

        layout.addWidget(self.result_table, 3)
        layout.addWidget(summary_splitter, 2)

        return box

    def _set_all_target_checks(self, checked: bool):
        """
        목표값 섹션의 모든 사용 체크박스를 선택/해제합니다.
        """
        for table in self.target_tables.values():
            for row in range(table.rowCount()):
                wrapper = table.cellWidget(row, 0)
                chk = getattr(wrapper, "checkbox", None)
                if chk:
                    chk.setChecked(checked)

    def _fill_default_tables(self):
        for row, stat in enumerate(STAT_ORDER):
            # 현재값
            self.current_table.setItem(row, 0, QTableWidgetItem(stat))
            self.current_table.setItem(row, 1, QTableWidgetItem("10"))
            self.current_table.setItem(row, 2, QTableWidgetItem("60"))

            # 목표값
            wrapper, chk = self._make_centered_checkbox(True)
            self.target_table.setCellWidget(row, 0, wrapper)
            self.target_table.setItem(row, 1, QTableWidgetItem(stat))
            self.target_table.setItem(row, 2, QTableWidgetItem("120"))
            self.target_table.setItem(row, 3, QTableWidgetItem("120"))

            # 상태표
            self.state_table.setItem(row, 0, QTableWidgetItem(stat))
            self.state_table.setItem(row, 1, QTableWidgetItem("10"))
            self.state_table.setItem(row, 2, QTableWidgetItem("60"))

    # 환경설정 내부 기능
    def _browse_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "비급 JSON 선택", "", "JSON Files (*.json)")
        if path:
            self.json_path_edit.setText(path)

    def _browse_dict(self):
        path, _ = QFileDialog.getOpenFileName(self, "KR_DICT Lua 선택", "", "Lua Files (*.lua);;All Files (*.*)")
        if path:
            self.dict_path_edit.setText(path)

    @staticmethod
    def _safe_int_from_item(table: QTableWidget, row: int, col: int, default: int = 0) -> int:
        item = table.item(row, col)
        if item is None:
            return default
        try:
            return int(item.text().strip())
        except Exception:
            return default

    # UI 초기상태 생성
    def _build_initial_state_from_ui(self) -> StatBlock:
        """
        속성 / 무학으로 분리된 현재값 테이블에서 초기 상태를 생성합니다.
        """
        current = {}
        potential = {}

        for title, stats in STAT_SECTIONS:
            table = self.current_tables[title]

            for row, stat in enumerate(stats):
                cur = self._safe_int_from_item(table, row, 1, 10)
                pot = self._safe_int_from_item(table, row, 2, 60)

                current[stat] = min(cur, pot)
                potential[stat] = pot

        return StatBlock(current=current, potential=potential)

    def _build_goal_from_ui(self) -> GoalConfig:
        """
        속성 / 무학으로 분리된 목표값 테이블에서 목표 설정을 생성합니다.
        """
        enabled = {}
        target_current = {}
        target_potential = {}

        for title, stats in STAT_SECTIONS:
            table = self.target_tables[title]

            for row, stat in enumerate(stats):
                wrapper = table.cellWidget(row, 0)
                chk = getattr(wrapper, "checkbox", None)
                enabled[stat] = bool(chk.isChecked()) if chk else True
                target_current[stat] = self._safe_int_from_item(table, row, 2, 120)
                target_potential[stat] = self._safe_int_from_item(table, row, 3, 120)

        return GoalConfig(
            enabled=enabled,
            target_current=target_current,
            target_potential=target_potential,
        )

    def _build_rarity_constraint_from_ui(self) -> RarityConstraint:
        enabled = {}
        max_books = {}

        for row in range(self.rarity_table.rowCount()):
            wrapper = self.rarity_table.cellWidget(row, 0)
            chk = getattr(wrapper, "checkbox", None)
            rare_item = self.rarity_table.item(row, 1)
            rare = rare_item.text().strip() if rare_item else ""

            enabled[rare] = bool(chk.isChecked()) if chk else True
            max_books[rare] = self._safe_int_from_item(self.rarity_table, row, 2, 999)

        return RarityConstraint(enabled=enabled, max_books=max_books)

    def _populate_rarity_table(self):
        existing_rarities = {g.skills[0].rare for g in self.groups}
        rarity_names = sorted(
            existing_rarities,
            key=lambda x: RARITY_ORDER.index(x) if x in RARITY_ORDER else 999
        )
        self.rarity_table.setRowCount(len(rarity_names))

        for row, rare in enumerate(rarity_names):
            wrapper, chk = self._make_centered_checkbox(True)
            self.rarity_table.setCellWidget(row, 0, wrapper)

            self.add_item(self.rarity_table, row, 1, rare, RARITY_COLORS.get(rare, "#FFFFFF"))
            # 최대권수
            default_count = RARITY_DEFAULT_COUNTS.get(rare, "999")
            self.add_item(self.rarity_table, row, 2, default_count, editable=True)

    # 누적상태 갱신
    def _update_state_table(self, state: StatBlock | None, changed: dict | None = None):
        changed = changed or {}
        enabled_map = self._get_goal_enabled_map()

        for title, stats in STAT_SECTIONS:
            table = self.state_tables[title]

            for row, stat in enumerate(stats):
                val_cur = state.current.get(stat, 0)
                val_pot = state.potential.get(stat, 0)

                item_name = QTableWidgetItem(stat)
                item_cur = QTableWidgetItem(str(val_cur))
                item_pot = QTableWidgetItem(str(val_pot))

                # 중앙 정렬 및 편집 금지 설정
                for item in [item_name, item_cur, item_pot]:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                stat_changed = changed.get(stat, {})
                is_target_enabled = enabled_map.get(stat, True)

                # 1. 스탯 명칭 색상 결정
                if not is_target_enabled:
                    item_name.setForeground(self.DISABLED_STAT_FG)
                else:
                    item_name.setForeground(self.NORMAL_STAT_FG)

                # 2. 현재값(Current) 색상 결정
                if stat_changed.get("current"):
                    item_cur.setForeground(self.CHANGED_STAT_FG)  # 변경 시 파란색 (최우선)
                elif not is_target_enabled:
                    item_cur.setForeground(self.DISABLED_STAT_FG)  # 미선택 시 회색
                else:
                    item_cur.setForeground(self.NORMAL_STAT_FG)  # 기본 검정

                # 3. 잠재값(Potential) 색상 결정
                if stat_changed.get("potential"):
                    item_pot.setForeground(self.CHANGED_STAT_FG)  # 변경 시 파란색 (최우선)
                elif not is_target_enabled:
                    item_pot.setForeground(self.DISABLED_STAT_FG)  # 미선택 시 회색
                else:
                    item_pot.setForeground(self.NORMAL_STAT_FG)  # 기본 검정

                table.setItem(row, 0, item_name)
                table.setItem(row, 1, item_cur)
                table.setItem(row, 2, item_pot)

    # 목표 체크 여부 헬퍼
    def _get_goal_enabled_map(self) -> dict:
        enabled = {}

        for title, stats in STAT_SECTIONS:
            table = self.target_tables[title]

            for row, stat in enumerate(stats):
                wrapper = table.cellWidget(row, 0)
                chk = getattr(wrapper, "checkbox", None)
                enabled[stat] = bool(chk.isChecked()) if chk else True

        return enabled

    def _load_data(self, silent: bool = False):
        try:
            json_path = self.json_path_edit.text().strip()
            dict_path = self.dict_path_edit.text().strip()

            data = load_json(json_path)
            self.kr_dict = load_kr_dict(dict_path)

            self.skills = []
            for raw in data["skills"]:
                skill = normalize_skill(raw)
                skill.name = translate(skill.name, self.kr_dict)
                skill.rare = translate(skill.rare, self.kr_dict)
                skill.type_name = translate(skill.type_name, self.kr_dict)
                skill.force_name = translate(skill.force_name, self.kr_dict)
                skill.needs = translate(skill.needs, self.kr_dict)
                self.skills.append(skill)

            self.groups = group_skills(self.skills)
            self._populate_rarity_table()

            self.initial_state = self._build_initial_state_from_ui()
            self._update_state_table(self.initial_state)

            self.btn_solve.setEnabled(True)
            self.status_label.setText(f"로드 완료 | 비급 {len(self.skills)}개 | 그룹 {len(self.groups)}개")
            self.settings["json_path"] = json_path
            self.settings["dict_path"] = dict_path
            save_settings(self.settings)
            self._refresh_plan_list()

            # TODO need parsing 확인용
            need_count = sum(1 for s in self.skills if s.need_current)
            print("needs 파싱된 비급 수:", need_count)

        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "로드 오류", str(e))
            else:
                self.status_label.setText("자동 로드 실패: 환경설정을 확인하세요.")

    def _refresh_plan_list(self):
        from app.plan_store import list_plans
        self.plan_name_combo.clear()
        self.plan_name_combo.addItems(list_plans())

    # ─ 최적화 함수
    def _solve(self):
        try:
            if not self.groups:
                QMessageBox.warning(self, "경고", "먼저 데이터를 로드하세요.")
                return

            self.initial_state = self._build_initial_state_from_ui()
            goal = self._build_goal_from_ui()
            rarity_constraint = self._build_rarity_constraint_from_ui()

            self.status_label.setText("최적화 실행 중...")
            QApplication.processEvents()

            self._sync_excluded_from_completed_actions()

            filtered_groups = []

            for g in self.groups:
                new_skills = [s for s in g.skills if self._is_skill_allowed_by_filter_rules(s)]
                if not new_skills:
                    continue

                new_g = self._clone_group_with_skills(g, new_skills)
                filtered_groups.append(new_g)
            self.result_groups = filtered_groups

            result = optimize_greedy_actions(
                initial_state=self.initial_state,
                goal=goal,
                rarity_constraint=rarity_constraint,
                groups=self.result_groups,
                max_iterations=300,
            )

            if not result.success and not result.actions:
                QMessageBox.information(self, "결과", result.message)
                self.result_table.setRowCount(0)
                self.rarity_summary_table.setRowCount(0)
                self.books_summary_table.setRowCount(0)
                self._update_state_table(self.initial_state)
                self.status_label.setText(result.message)
                return

            if not result.success:
                QMessageBox.information(self, "부분 결과", result.message)

            self.result_actions = result.actions
            self._populate_result_table()
            self._update_state_table(self.initial_state)
            self._rebuild_usage_summary()
            self.status_label.setText(
                f"{'성공' if result.success else '부분 결과'} | "
                f"비급 {result.used_books_total}권 | 총 단계 {result.used_levels_total} | "
                f"초과 {result.overshoot_score}"
            )

            order_msg = "권 단위 정렬 성공"

            self._populate_result_table()
            self._update_state_table(self.initial_state)
            self._rebuild_usage_summary()

            self.status_label.setText(
                f"성공 | 비급 {result.used_books_total}권 | 총 단계 {result.used_levels_total} | "
                f"초과 {result.overshoot_score} | {order_msg}"
            )

        except Exception as e:
            QMessageBox.critical(self, "최적화 오류", str(e))

    # ─ 필터 판단 함수
    def _rule_matches_skill(self, rule: dict, skill) -> bool:
        kind = rule.get("kind")

        if kind == "all":
            return True

        if kind == "skill":
            return skill.id == rule.get("skill_id")

        if kind == "force":
            return skill.force_name == rule.get("force_name")

        if kind == "filter":
            force = rule.get("force_name")
            type_name = rule.get("type_name")
            rare = rule.get("rare")

            if force and force != "전체" and skill.force_name != force:
                return False
            if type_name and type_name != "전체" and skill.type_name != type_name:
                return False
            if rare and rare != "전체" and skill.rare != rare:
                return False

            return True

        return False

    def _is_skill_allowed_by_filter_rules(self, skill) -> bool:
        """
        포함/제외 규칙을 위에서 아래 순서대로 적용합니다.
        마지막으로 매칭된 규칙이 최종 허용 여부를 결정합니다.
        """
        if skill.id in self.excluded_skill_ids:
            return False

        # 룰이 비어 있으면 안전하게 전체 허용
        if not self.skill_filter_rules:
            return True

        allowed = False

        for rule in self.skill_filter_rules:
            if self._rule_matches_skill(rule, skill):
                allowed = rule.get("action") == "include"

        return allowed

    def _clone_group_with_skills(self, group, skills):
        from app.models import SkillGroup

        return SkillGroup(
            key=group.key,
            delta_current=dict(group.delta_current),
            delta_potential=dict(group.delta_potential),
            skills=list(skills),
        )

    # ─ 비급 추가 / 제외 법칙용 다이얼로그
    def _open_skill_filter_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("비급 포함/제외 관리")
        dlg.resize(980, 620)

        layout = QVBoxLayout(dlg)

        mode_layout = QHBoxLayout()

        layout.addLayout(mode_layout)

        filter_layout = QHBoxLayout()

        force_combo = QComboBox()
        type_combo = QComboBox()
        rare_combo = QComboBox()

        search_edit = ImeAwareLineEdit()

        force_values = sorted({s.force_name for s in self.skills})
        type_values = sorted({s.type_name for s in self.skills})
        rare_values = sorted(
            {s.rare for s in self.skills},
            key=lambda x: RARITY_ORDER.index(x) if x in RARITY_ORDER else 999,
        )

        force_combo.addItem("전체")
        force_combo.addItems(force_values)

        type_combo.addItem("전체")
        type_combo.addItems(type_values)

        rare_combo.addItem("전체")
        rare_combo.addItems(rare_values)

        search_edit.setPlaceholderText("비급명 검색")

        filter_layout.addWidget(QLabel("출처"))
        filter_layout.addWidget(force_combo)
        filter_layout.addWidget(QLabel("종류"))
        filter_layout.addWidget(type_combo)
        filter_layout.addWidget(QLabel("희귀도"))
        filter_layout.addWidget(rare_combo)
        filter_layout.addWidget(QLabel("검색"))
        filter_layout.addWidget(search_edit)

        layout.addLayout(filter_layout)

        body_layout = QHBoxLayout()

        skill_list = QListWidget()
        rule_list = QListWidget()

        body_layout.addWidget(skill_list, 2)
        body_layout.addWidget(rule_list, 2)

        layout.addLayout(body_layout, 1)

        btn_layout = QHBoxLayout()

        btn_start_include_all = QPushButton("전체 허용으로 시작")
        btn_start_exclude_all = QPushButton("전체 제외로 시작")
        btn_add_skill = QPushButton("선택 비급 추가")
        btn_exclude_skill = QPushButton("선택 비급 제외")
        btn_add_filter = QPushButton("현재 필터 추가")
        btn_exclude_filter = QPushButton("현재 필터 제외")
        btn_remove_rule = QPushButton("선택 규칙 제거")
        btn_reset_rules = QPushButton("규칙 초기화")
        btn_close = QPushButton("닫기")

        btn_layout.addWidget(btn_start_include_all)
        btn_layout.addWidget(btn_start_exclude_all)
        btn_layout.addWidget(btn_add_skill)
        btn_layout.addWidget(btn_add_filter)
        btn_layout.addWidget(btn_exclude_filter)
        btn_layout.addWidget(btn_remove_rule)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_reset_rules)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)
        skill_list.itemDoubleClicked.connect(lambda _item: add_selected_skill_rule("include"))
        rule_list.itemDoubleClicked.connect(lambda _item: on_remove_rule())

        def action_text(action: str) -> str:
            return "추가" if action == "include" else "제외"

        def make_rule_label(rule: dict) -> str:
            action = action_text(rule.get("action", "include"))
            kind = rule.get("kind")

            if kind == "all":
                return f"[{action}] 전체"

            if kind == "skill":
                return (
                    f"[{action}] 비급 | {rule.get('label')} | "
                    f"{rule.get('rare')} / {rule.get('type_name')} / {rule.get('force_name')}"
                )

            if kind == "force":
                return f"[{action}] 출처 전체 | {rule.get('force_name')}"

            if kind == "filter":
                return (
                    f"[{action}] 필터 | "
                    f"출처={rule.get('force_name') or '전체'}, "
                    f"종류={rule.get('type_name') or '전체'}, "
                    f"희귀도={rule.get('rare') or '전체'}"
                )

            return str(rule)

        def refresh_rules():
            rule_list.clear()
            for rule in self.skill_filter_rules:
                item = QListWidgetItem(make_rule_label(rule))
                item.setData(Qt.UserRole, rule)
                rule_list.addItem(item)

        def filtered_skills():
            force = force_combo.currentText()
            type_name = type_combo.currentText()
            rare = rare_combo.currentText()
            keyword = search_state["text"].strip()

            result = []
            for s in self.skills:
                if force != "전체" and s.force_name != force:
                    continue
                if type_name != "전체" and s.type_name != type_name:
                    continue
                if rare != "전체" and s.rare != rare:
                    continue
                if keyword and keyword not in s.name:
                    continue
                result.append(s)
            return result

        def refresh_skill_list():
            skill_list.clear()
            for s in filtered_skills():
                text = f"[{s.rare}] {s.name} | {s.type_name} | {s.force_name} | ID:{s.id}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, s.id)
                item.setForeground(QColor(RARITY_COLORS.get(s.rare, "#FFFFFF")))
                skill_list.addItem(item)

        # 룰 추가 함수
        def add_rule(rule: dict):
            self.skill_filter_rules.append(rule)
            refresh_rules()

        # 개별 비급 추가
        def add_selected_skill_rule(action: str):
            """
            개별 비급 추가
            :return: None
            """
            item = skill_list.currentItem()
            if not item:
                return

            sid = item.data(Qt.UserRole)
            skill = next((s for s in self.skills if s.id == sid), None)
            if not skill:
                return

            add_rule({
                "action": action,
                "kind": "skill",
                "label": skill.name,
                "skill_id": skill.id,
                "rare": skill.rare,
                "type_name": skill.type_name,
                "force_name": skill.force_name,
            })

        # 필터 전체 추가
        def add_filter_rule(action: str):
            add_rule({
                "action": action,
                "kind": "filter",
                "label": "필터",
                "skill_id": None,
                "rare": rare_combo.currentText(),
                "type_name": type_combo.currentText(),
                "force_name": force_combo.currentText(),
            })

        def on_remove_rule():
            row = rule_list.currentRow()
            if row < 0:
                return
            self.skill_filter_rules.pop(row)
            refresh_rules()

        # 버튼 연결
        def start_include_all():
            self.skill_filter_rules = [
                {"action": "include", "kind": "all", "label": "전체"}
            ]
            refresh_rules()

        def start_exclude_all():
            self.skill_filter_rules = [
                {"action": "exclude", "kind": "all", "label": "전체"}
            ]
            refresh_rules()

        def reset_rules():
            self.skill_filter_rules = [
                {"action": "include", "kind": "all", "label": "전체"}
            ]
            refresh_rules()

        btn_start_include_all.clicked.connect(start_include_all)
        btn_start_exclude_all.clicked.connect(start_exclude_all)
        btn_reset_rules.clicked.connect(reset_rules)

        force_combo.currentIndexChanged.connect(refresh_skill_list)
        type_combo.currentIndexChanged.connect(refresh_skill_list)
        rare_combo.currentIndexChanged.connect(refresh_skill_list)
        search_state = {"text": ""}

        def on_search_changed(text):
            search_state["text"] = text
            refresh_skill_list()

        search_edit.textChanged.connect(on_search_changed)
        search_edit.imeTextChanged.connect(on_search_changed)

        btn_add_skill.clicked.connect(lambda: add_selected_skill_rule("include"))
        btn_exclude_skill.clicked.connect(lambda: add_selected_skill_rule("exclude"))
        btn_add_filter.clicked.connect(lambda: add_filter_rule("include"))
        btn_exclude_filter.clicked.connect(lambda: add_filter_rule("exclude"))
        btn_remove_rule.clicked.connect(on_remove_rule)
        btn_close.clicked.connect(dlg.accept)

        refresh_skill_list()
        refresh_rules()

        dlg.exec()

    # 완료된 비급 내역 동기화
    def _sync_excluded_from_completed_actions(self):
        """
        추천 비급 목록에서 완료 체크된 행의 실제 선택 비급을
        excluded_skill_ids에 반영합니다.

        완료된 비급은 다음 최적화에서 항상 제외됩니다.
        """
        # 기존 수동 제외 목록을 보존하려면 clear하지 않는 쪽이 안전합니다.
        # 여기서는 완료된 비급 ID만 추가합니다.
        for row in self.completed_action_rows:
            if row < 0 or row >= self.result_table.rowCount():
                continue

            name = self._get_selected_skill_name_for_row(row)
            type_name = self._get_type_for_row(row)
            force = self._get_force_for_row(row)

            for g in self.groups:
                for s in g.skills:
                    if (
                            s.name == name
                            and s.type_name == type_name
                            and s.force_name == force
                    ):
                        self.excluded_skill_ids.add(s.id)
                        break

    # 결과표에 내용넣기
    def _populate_result_table(self):
        self.result_table.setRowCount(len(self.result_actions))

        for row, action in enumerate(self.result_actions):
            group = self.result_groups[action.group_index]
            selected_idx = getattr(action, "selected_skill_index", action.default_skill_index)
            selected_idx = max(0, min(selected_idx, len(group.skills) - 1))

            default_idx = selected_idx
            default_skill = group.skills[default_idx]
            action.selected_skill_index = default_idx  # UI 선택값 → BookAction 반영 초기값 세팅

            # 체크박스
            wrapper, chk = self._make_centered_checkbox(row in self.completed_action_rows)
            if chk:
                chk.stateChanged.connect(lambda _state, r=row: self._on_result_completed_changed(r))
            self.result_table.setCellWidget(row, 0, wrapper)
            # 순서
            self.add_item(self.result_table, row, 1, str(row + 1))
            # 등급
            self.add_item(self.result_table, row, 2, default_skill.rare,
                          color=RARITY_COLORS.get(default_skill.rare, "#FFFFFF"), editable=False)
            # 드롭다운
            combo = QComboBox()
            color = RARITY_COLORS.get(default_skill.rare, "#FFFFFF")
            # 콤보박스 스타일시트
            style = f"""
                QComboBox {{
                    color: {color};
                    font-weight: bold;
                }}
                QComboBox QAbstractItemView {{
                    color: {color};
                }}
            """
            combo.setStyleSheet(style)
            for sk in group.skills:
                combo.addItem(sk.name)
            combo.setCurrentIndex(default_idx)
            combo.setToolTip(self._make_skill_tooltip(default_skill, group))  # 툴팁
            self._last_combo_indices[row] = default_idx  # 선택한 비급 상태변수 (중복선택 방지용)
            combo.currentIndexChanged.connect(lambda _idx, r=row: self._on_result_skill_combo_changed(r))
            self.result_table.setCellWidget(row, 3, combo)
            # 종류
            self.add_item(self.result_table, row, 4, default_skill.type_name, editable=False)
            # 출처
            self.add_item(self.result_table, row, 5, default_skill.force_name, editable=False)
            # 사용 단계, 그룹 내 권, 그룹 수량
            self.add_item(self.result_table, row, 6, str(action.levels_used), editable=False)
            self.add_item(self.result_table, row, 7, str(action.book_no_in_group), editable=False)
            self.add_item(self.result_table, row, 8, str(group.count), editable=False)
            self.result_table.setItem(row, 9,
                                      QTableWidgetItem(format_growth_text(group.delta_current, potential=False)))
            self.result_table.setItem(row, 10,
                                      QTableWidgetItem(format_growth_text(group.delta_potential, potential=True)))

    def _on_result_completed_changed(self, row: int):
        wrapper = self.result_table.cellWidget(row, 0)
        chk = getattr(wrapper, "checkbox", None)
        checked = bool(chk.isChecked()) if chk else False

        if checked:
            self.completed_action_rows.add(row)
        else:
            self.completed_action_rows.discard(row)

        # 완료 체크 시 현재 index 저장
        idx = self._get_selected_skill_index_for_row(row)
        if idx >= 0:
            self._last_combo_indices[row] = idx

        combo = self.result_table.cellWidget(row, 3)
        if isinstance(combo, QComboBox):
            combo.setEnabled(not checked)

        self._apply_result_row_state(row)
        self._rebuild_usage_summary()

    def _on_result_skill_combo_changed(self, row: int):
        """
        결과 목록의 비급 드롭다운 선택이 바뀌었을 때,
        같은 그룹 내 중복 선택을 방지하고 출처/종류/요약을 갱신합니다.
        """
        if self._updating_combo:
            return

        if row in self.completed_action_rows:
            previous = self._last_combo_indices.get(row, 0)
            self._set_result_combo_index(row, previous)
            return

        if row < 0 or row >= len(self.result_actions):
            return

        action = self.result_actions[row]
        group = self.result_groups[action.group_index]

        combo = self.result_table.cellWidget(row, 3)
        if not isinstance(combo, QComboBox):
            return

        idx = combo.currentIndex()
        if idx < 0 or idx >= len(group.skills):
            return

        previous = self._last_combo_indices.get(row, idx)

        ok = self._resolve_group_skill_conflicts(row)
        if not ok:
            QMessageBox.warning(
                self,
                "선택 불가",
                "같은 그룹 내에서 사용할 수 있는 다른 비급이 없거나, 완료된 단계와 충돌합니다.",
            )
            self._set_result_combo_index(row, previous)
            return

        selected_skill = group.skills[idx]
        action.selected_skill_index = idx  # UI 선택값 → BookAction 반영
        self._last_combo_indices[row] = idx
        # 툴팁 갱신
        combo.setToolTip(self._make_skill_tooltip(selected_skill, group))
        self.add_item(self.result_table, row, 2, selected_skill.rare,
                      color=RARITY_COLORS.get(selected_skill.rare, "#FFFFFF"))
        self.add_item(self.result_table, row, 4, selected_skill.type_name)
        self.add_item(self.result_table, row, 5, selected_skill.force_name)
        self._rebuild_usage_summary()

    def _get_rarity_for_row(self, row: int) -> str:
        item = self.result_table.item(row, 2)
        return item.text().strip() if item else ""

    def _get_selected_skill_name_for_row(self, row: int) -> str:
        combo = self.result_table.cellWidget(row, 3)
        if isinstance(combo, QComboBox):
            return combo.currentText().strip()
        item = self.result_table.item(row, 3)
        return item.text().strip() if item else ""

    def _get_type_for_row(self, row: int) -> str:
        item = self.result_table.item(row, 4)
        return item.text().strip() if item else ""

    def _get_force_for_row(self, row: int) -> str:
        item = self.result_table.item(row, 5)
        return item.text().strip() if item else ""

    def _get_levels_for_row(self, row: int) -> int:
        item = self.result_table.item(row, 6)
        try:
            return int(item.text().strip()) if item else 0
        except Exception:
            return 0

    def _rebuild_usage_summary(self):
        """
        결과 테이블의 현재 드롭다운 선택 상태를 바탕으로
        희귀도별 사용 권수 / 실제 사용 비급 목록 요약을 갱신합니다.
        """
        rarity_count = defaultdict(int)
        rarity_levels = defaultdict(int)

        book_usage = defaultdict(lambda: {"books": 0, "levels": 0})

        for row in range(self.result_table.rowCount()):
            rare = self._get_rarity_for_row(row)
            name = self._get_selected_skill_name_for_row(row)
            levels = self._get_levels_for_row(row)

            rarity_count[rare] += 1
            rarity_levels[rare] += levels

            skill_type = self._get_type_for_row(row)
            force = self._get_force_for_row(row)
            key = (rare, name, skill_type, force)
            book_usage[key]["books"] += 1
            book_usage[key]["levels"] += levels

        # 희귀도별 사용 권수 요약 테이블
        rarity_items = sorted(rarity_count.items(), key=lambda x: RARITY_ORDER.index(x[0]))
        # 전체 행 추가 + 1
        self.rarity_summary_table.setRowCount(len(rarity_items) + 1)
        # 수정불가 적용
        self.rarity_summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # 전체 사용 권수
        total_books = sum(rarity_count.values())
        total_levels = sum(rarity_levels.values())
        self.add_item(self.rarity_summary_table, 0, 0, "전체", editable=False)
        self.add_item(self.rarity_summary_table, 0, 1, total_books, editable=False)
        self.add_item(self.rarity_summary_table, 0, 2, total_levels, editable=False)

        for row, (rare, books) in enumerate(rarity_items, start=1):
            self.add_item(self.rarity_summary_table, row, 0, rare, color=RARITY_COLORS.get(rare, "#FFFFFF"),
                          editable=False)
            self.add_item(self.rarity_summary_table, row, 1, books)
            self.add_item(self.rarity_summary_table, row, 2, rarity_levels[rare])

        book_usage = defaultdict(lambda: {"rows": 0, "completed": 0, "levels": 0})

        for row in range(self.result_table.rowCount()):
            rare = self._get_rarity_for_row(row)
            name = self._get_selected_skill_name_for_row(row)
            type_name = self._get_type_for_row(row)
            force = self._get_force_for_row(row)
            levels = self._get_levels_for_row(row)

            key = (rare, name, type_name, force)
            book_usage[key]["rows"] += 1
            book_usage[key]["levels"] += levels

            if row in self.completed_action_rows:
                book_usage[key]["completed"] += 1

        # 사용된 비급 목록 테이블
        book_items = sorted(book_usage.items(), key=lambda x: (x[0][0], x[0][1]))
        self.books_summary_table.setRowCount(len(book_items))
        self.books_summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        for row, ((rare, name, skill_type, force), info) in enumerate(book_items):
            done_text = "완료" if info["rows"] > 0 and info["completed"] == info["rows"] else ""

            # 사용된 비급 목록
            self.add_item(self.books_summary_table, row, 0, done_text, editable=False)
            self.add_item(self.books_summary_table, row, 1, rare, RARITY_COLORS.get(rare, "#FFFFFF"))
            self.add_item(self.books_summary_table, row, 2, name, RARITY_COLORS.get(rare, "#FFFFFF"))
            self.add_item(self.books_summary_table, row, 3, skill_type)
            self.add_item(self.books_summary_table, row, 4, force)
            # self.add_item(self.books_summary_table, row, 5, info["books"])
            self.add_item(self.books_summary_table, row, 5, info["levels"])

    def _get_excluded_keys(self):
        keys = set()
        for sid in self.excluded_skill_ids:
            for g in self.groups:
                for s in g.skills:
                    if s.id == sid:
                        keys.add((s.rare, s.name, s.force_name))
        return keys

    def _on_exclude_changed(self):
        self.excluded_skill_ids.clear()

        for row in range(self.books_summary_table.rowCount()):
            wrapper = self.books_summary_table.cellWidget(row, 0)
            if not wrapper:
                continue
            chk = wrapper.findChild(QCheckBox)

            # 찾은 체크박스의 체크 상태를 확인
            if not chk or not chk.isChecked():
                continue

            # item(row, 2)는 비급명, item(row, 3)은 종류(문파)입니다.
            name_item = self.books_summary_table.item(row, 2)
            force_item = self.books_summary_table.item(row, 3)

            if not name_item or not force_item:
                continue

            name = name_item.text()
            force = force_item.text()

            for g in self.groups:
                for s in g.skills:
                    if s.name == name and s.force_name == force:
                        self.excluded_skill_ids.add(s.id)

    def _on_result_selection_changed(self):
        selected = self.result_table.selectionModel().selectedRows()
        if not selected:
            return

        self._apply_result_row_state(selected[0].row())

    # ─ 저장 기능
    # 저장 / 불러오기 / 삭제
    def _save_plan(self):
        from app.plan_store import save_plan

        default_name = self.plan_name_combo.currentText().strip() or "새_플랜"

        name, ok = QInputDialog.getText(
            self,
            "플랜 저장",
            "저장할 플랜 이름:",
            text=default_name,
        )

        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.warning(self, "저장 실패", "플랜 이름을 입력하세요.")
            return

        data = {
            "version": 1,
            "current_values": self._collect_current_ui_values(),
            "goal_values": self._collect_goal_ui_values(),
            "rarity_limits": self._collect_rarity_ui_values(),
            "result_rows": self._collect_result_rows(),
            "completed_action_rows": sorted(list(self.completed_action_rows)),
            "filter_mode": self.filter_mode,
            "skill_filter_rules": self.skill_filter_rules,
            "excluded_skill_ids": sorted(list(self.excluded_skill_ids)),
        }

        save_plan(name, data)
        self._refresh_plan_list()

        idx = self.plan_name_combo.findText(name)
        if idx >= 0:
            self.plan_name_combo.setCurrentIndex(idx)

        QMessageBox.information(self, "저장 완료", f"플랜 저장 완료: {name}")

    def _load_plan(self):
        from app.plan_store import load_plan

        name = self.plan_name_combo.currentText().strip()
        if not name:
            return

        if not self.groups:
            QMessageBox.warning(self, "불러오기 실패", "먼저 데이터를 로드하세요.")
            return

        data = load_plan(name)

        # UI 복원
        self._restore_current_ui_values(data.get("current_values", {}))
        self._restore_goal_ui_values(data.get("goal_values", {}))
        self._restore_rarity_ui_values(data.get("rarity_limits", {}))

        # 필터 로드
        self.filter_mode = data.get("filter_mode", "exclude")
        self.skill_filter_rules = data.get(
            "skill_filter_rules",
            [{"action": "include", "kind": "all", "label": "전체"}]
        )
        self.excluded_skill_ids = set(data.get("excluded_skill_ids", []))

        self.initial_state = self._build_initial_state_from_ui()
        self._update_state_table(self.initial_state)

        self._restore_result_rows(data.get("result_rows", []))

        QMessageBox.information(self, "불러오기 완료", f"플랜 불러오기 완료: {name}")

    def _delete_plan(self):
        from app.plan_store import delete_plan

        name = self.plan_name_combo.currentText()
        if not name:
            return

        delete_plan(name)
        self._refresh_plan_list()

    # 플랜 저장용 헬퍼 함수들
    def _collect_current_ui_values(self) -> dict:
        data = {}

        for title, stats in STAT_SECTIONS:
            table = self.current_tables[title]
            for row, stat in enumerate(stats):
                data[stat] = {
                    "current": self._safe_int_from_item(table, row, 1, 10),
                    "potential": self._safe_int_from_item(table, row, 2, 60),
                }

        return data

    def _collect_goal_ui_values(self) -> dict:
        data = {}

        for title, stats in STAT_SECTIONS:
            table = self.target_tables[title]
            for row, stat in enumerate(stats):
                wrapper = table.cellWidget(row, 0)
                chk = getattr(wrapper, "checkbox", None)

                data[stat] = {
                    "enabled": bool(chk.isChecked()) if chk else True,
                    "target_current": self._safe_int_from_item(table, row, 2, 120),
                    "target_potential": self._safe_int_from_item(table, row, 3, 120),
                }

        return data

    def _collect_rarity_ui_values(self) -> dict:
        data = {}

        for row in range(self.rarity_table.rowCount()):
            wrapper = self.rarity_table.cellWidget(row, 0)
            chk = getattr(wrapper, "checkbox", None)
            rare_item = self.rarity_table.item(row, 1)
            rare = rare_item.text().strip() if rare_item else ""

            data[rare] = {
                "enabled": bool(chk.isChecked()) if chk else True,
                "max_books": self._safe_int_from_item(self.rarity_table, row, 2, 999),
            }

        return data

    def _collect_result_rows(self) -> list[dict]:
        rows = []

        for row, action in enumerate(self.result_actions):
            rows.append({
                "row": row,
                "group_index": action.group_index,
                "book_no_in_group": action.book_no_in_group,
                "levels_used": action.levels_used,
                "selected_skill_name": self._get_selected_skill_name_for_row(row),
                "rare": self._get_rarity_for_row(row),
                "type_name": self._get_type_for_row(row),
                "force_name": self._get_force_for_row(row),
                "completed": row in self.completed_action_rows,
            })

        return rows

    # 로드 시 UI 복원용 헬퍼 함수들
    def _restore_current_ui_values(self, data: dict):
        for title, stats in STAT_SECTIONS:
            table = self.current_tables[title]
            for row, stat in enumerate(stats):
                item = data.get(stat, {})
                table.setItem(row, 1, QTableWidgetItem(str(item.get("current", 10))))
                table.setItem(row, 2, QTableWidgetItem(str(item.get("potential", 60))))

    def _restore_goal_ui_values(self, data: dict):
        for title, stats in STAT_SECTIONS:
            table = self.target_tables[title]
            for row, stat in enumerate(stats):
                item = data.get(stat, {})

                wrapper = table.cellWidget(row, 0)
                chk = getattr(wrapper, "checkbox", None)
                if chk:
                    chk.setChecked(bool(item.get("enabled", True)))

                table.setItem(row, 2, QTableWidgetItem(str(item.get("target_current", 120))))
                table.setItem(row, 3, QTableWidgetItem(str(item.get("target_potential", 120))))

    def _restore_rarity_ui_values(self, data: dict):
        for row in range(self.rarity_table.rowCount()):
            rare_item = self.rarity_table.item(row, 1)
            rare = rare_item.text().strip() if rare_item else ""
            item = data.get(rare, {})

            wrapper = self.rarity_table.cellWidget(row, 0)
            chk = getattr(wrapper, "checkbox", None)
            if chk:
                chk.setChecked(bool(item.get("enabled", True)))

            self.rarity_table.setItem(row, 2, QTableWidgetItem(str(item.get("max_books", 999))))

    # 결과표 복원함수
    def _restore_result_rows(self, rows: list[dict]):
        from app.snapshot import BookAction

        self.result_actions = []
        self.completed_action_rows = set()

        for item in rows:
            self.result_actions.append(
                BookAction(
                    group_index=int(item["group_index"]),
                    book_no_in_group=int(item.get("book_no_in_group", 1)),
                    levels_used=int(item["levels_used"]),
                    default_skill_index=0,
                )
            )

            if item.get("completed", False):
                self.completed_action_rows.add(len(self.result_actions) - 1)

        self._populate_result_table()

        # 저장된 비급명으로 드롭다운 복원
        for row, item in enumerate(rows):
            combo = self.result_table.cellWidget(row, 3)
            if isinstance(combo, QComboBox):
                name = item.get("selected_skill_name", "")
                idx = combo.findText(name)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

                if row in self.completed_action_rows:  # 완료된 행 드랍다운 잠금
                    combo.setEnabled(False)

        for row in range(len(self.result_actions)):
            combo = self.result_table.cellWidget(row, 3)
            if isinstance(combo, QComboBox):
                self._last_combo_indices[row] = combo.currentIndex()
        self._rebuild_usage_summary()

    # 드랍다운: 선택된 그룹 내 skill index helper
    def _get_selected_skill_index_for_row(self, row: int) -> int:
        combo = self.result_table.cellWidget(row, 3)
        if isinstance(combo, QComboBox):
            return combo.currentIndex()
        return -1

    # 드랍다운: 같은 그룹 행 찾기 helper
    def _rows_for_same_group(self, group_index: int) -> list[int]:
        rows = []

        for row, action in enumerate(self.result_actions):
            if action.group_index == group_index:
                rows.append(row)

        return rows

    # 드랍다운: 사용 중인 skill index 수집 helper
    def _used_skill_indices_in_group(self, group_index: int, except_row: int | None = None) -> set[int]:
        used = set()

        for row in self._rows_for_same_group(group_index):
            if except_row is not None and row == except_row:
                continue

            idx = self._get_selected_skill_index_for_row(row)
            if idx >= 0:
                used.add(idx)

        return used

    # 드랍다운: 특정 행에 선택 가능한 대체 비급 찾기
    def _find_available_skill_index_for_row(self, row: int, preferred: int | None = None) -> int:
        if row < 0 or row >= len(self.result_actions):
            return -1

        action = self.result_actions[row]
        group = self.result_groups[action.group_index]

        used = self._used_skill_indices_in_group(action.group_index, except_row=row)

        if preferred is not None and 0 <= preferred < len(group.skills) and preferred not in used:
            return preferred

        for idx in range(len(group.skills)):
            if idx not in used:
                return idx

        return -1

    # 드랍다운: 행 콤보 선택 변경 helper
    def _set_result_combo_index(self, row: int, index: int):
        combo = self.result_table.cellWidget(row, 3)
        if not isinstance(combo, QComboBox):
            return

        self._updating_combo = True
        combo.setCurrentIndex(index)
        self._updating_combo = False

        self._last_combo_indices[row] = index

        action = self.result_actions[row]
        action.selected_skill_index = index

        group = self.result_groups[action.group_index]
        skill = group.skills[index]

        combo.setToolTip(self._make_skill_tooltip(skill, group))

        self.add_item(
            self.result_table,
            row,
            2,
            skill.rare,
            color=RARITY_COLORS.get(skill.rare, "#FFFFFF"),
            editable=False,
        )
        # FIXME 4,5 이외의 행들도 변경?
        self.add_item(self.result_table, row, 4, skill.type_name, editable=False)
        self.add_item(self.result_table, row, 5, skill.force_name, editable=False)

    # 드랍다운: 중복선택 자동 변경 함수
    def _resolve_group_skill_conflicts(self, changed_row: int) -> bool:
        """
        changed_row에서 선택한 비급 때문에 같은 그룹 내 중복 선택이 생기면,
        다른 미완료 행을 가능한 대체 비급으로 자동 변경합니다.

        완료된 행과 충돌하면 변경 불가입니다.
        """
        if changed_row < 0 or changed_row >= len(self.result_actions):
            return True

        changed_action = self.result_actions[changed_row]
        group_index = changed_action.group_index
        changed_idx = self._get_selected_skill_index_for_row(changed_row)

        if changed_idx < 0:
            return True

        same_rows = self._rows_for_same_group(group_index)

        for row in same_rows:
            if row == changed_row:
                continue

            other_idx = self._get_selected_skill_index_for_row(row)
            if other_idx != changed_idx:
                continue

            # 완료된 행과 충돌하면 changed_row 변경을 거부해야 함
            if row in self.completed_action_rows:
                return False

            # 미완료 행이면 다른 비급으로 자동 대체
            replacement = self._find_available_skill_index_for_row(row, preferred=None)
            if replacement < 0:
                return False

            self._set_result_combo_index(row, replacement)

        return True

    # 가운데 정렬, 수정불가 등
    @staticmethod
    def add_item(table, row, col, text, color=None, editable=False):
        """
        가운데 정렬, 색상추가가능, 수정가능
        :rtype: None
        """

        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignCenter)  # 여기서 중앙 정렬

        if color:
            item.setForeground(QColor(color))
        if editable:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

        table.setItem(row, col, item)

    # 체크박스 중앙정렬용
    @staticmethod
    def _make_centered_checkbox(checked: bool = True) -> tuple[QWidget, QCheckBox]:
        """
        테이블 셀 안에 체크박스를 가운데 정렬해 넣기 위한 래퍼 위젯을 생성합니다.
        """
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)

        chk = QCheckBox()
        chk.setChecked(checked)

        layout.addStretch(1)
        layout.addWidget(chk)
        layout.addStretch(1)

        wrapper.checkbox = chk
        return wrapper, chk
