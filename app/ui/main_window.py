# app/ui/main_window.py
# 이 파일은 비급 최적화 도구의 메인 PySide6 UI를 정의합니다.
# 상단 입력 섹션(현재값/목표값/희귀도 제한)과 하단 결과 섹션(상태/추천 목록/요약)을 구성합니다.

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Any

from PySide6.QtCore import Qt, Signal, QRect
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
    QTextEdit, QAbstractItemView, QListWidget, QListWidgetItem, QRadioButton, QButtonGroup, QStyleOptionButton, QStyle,
    QSizePolicy, QSpacerItem, QGraphicsOpacityEffect
)
from PySide6.QtGui import QColor, QPalette, QIcon, QPixmap

from app.loaders import load_skills_from_db
from app.models import Skill
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
from app.utils import resource_path


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


# 체크박스 헤더용
class CheckBoxHeader(QHeaderView):
    clicked = Signal(bool)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._is_checked = False

    def paintSection(self, painter, rect, logicalIndex):
        # 1. 기본 헤더 배경과 테두리를 먼저 그림
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()

        if logicalIndex == 0:
            option = QStyleOptionButton()

            # 2. 스타일에서 체크박스 인디케이터의 표준 크기를 가져옴
            # SE_CheckBoxIndicator는 보통 13~16px 정도의 고정 크기를 가집니다.
            width = self.style().pixelMetric(QStyle.PM_IndicatorWidth)
            height = self.style().pixelMetric(QStyle.PM_IndicatorHeight)

            # 3. 전체 rect 내에서 정확히 중앙 좌표 계산
            x = rect.x() + (rect.width() - width) // 2 - 4
            y = rect.y() + (rect.height() - height) // 2

            option.rect = QRect(x, y, width, height)
            option.state = QStyle.State_Enabled | QStyle.State_Active

            if self._is_checked:
                option.state |= QStyle.State_On
            else:
                option.state |= QStyle.State_Off

            # 4. 계산된 중앙 위치에 체크박스 렌더링
            self.style().drawControl(QStyle.CE_CheckBox, option, painter)

    def mousePressEvent(self, event):
        index = self.logicalIndexAt(event.pos())
        if index == 0:
            self._is_checked = not self._is_checked
            self.clicked.emit(self._is_checked)
            self.updateSection(0)
        super().mousePressEvent(event)

    def setChecked(self, state: bool):
        if self._is_checked != state:
            self._is_checked = state
            self.updateSection(0)


# 이미지 버튼
class ImageButton(QLabel):
    # 클릭했을 때 발생할 신호 정의
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)  # 마우스 올리면 손가락 모양으로

        # 투명도 효과 설정 (오버 효과용)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)  # 기본은 불투명
        self.setGraphicsEffect(self.opacity_effect)

    # 마우스가 들어왔을 때 (Hover In)
    def enterEvent(self, event):
        self.opacity_effect.setOpacity(0.8)  # 살짝 투명하게 해서 "불 들어온" 느낌
        super().enterEvent(event)

    # 마우스가 나갔을 때 (Hover Out)
    def leaveEvent(self, event):
        self.opacity_effect.setOpacity(1.0)  # 다시 원래대로
        super().leaveEvent(event)

    # 마우스 버튼을 눌렀다 뗐을 때 (Click)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()  # 클릭 신호 발사!
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    """
    비급 최적화 메인 윈도우입니다.
    """

    def __init__(self):
        super().__init__()

        self.state_table = None
        self.target_table = None
        self.current_table = None
        self.setWindowIcon(QIcon(resource_path("assets/icon.ico")))
        self.setWindowTitle("비급 최적화 도구 by HexX")
        self.resize(1650, 1120)
        self.banner = resource_path("assets/banner.png")
        self.logo = resource_path("assets/lylzz_logo.png")

        # 핵심 데이터 캐시
        self.skills = []
        self.groups = []
        self.initial_state: StatBlock | None = None
        self.result_actions = []
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
        # 헤더 선택 상태
        self._select_all_target = True

        self.settings = load_settings()

        self._build_ui()

        # 기본 경로 자동 입력
        self.db_path_edit.setText(self.settings.get("db_path", "data/skills_kr.db"))

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
        # root.addLayout(top_bar)
        root.addWidget(top_bar)

        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, 1)

        # 상단 섹션
        top_section = QWidget()
        top_layout = QHBoxLayout(top_section)
        top_section.setMaximumHeight(400)

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
        플랜 관리 및 실행 버튼 바를 깔끔하게 정렬하여 생성합니다.
        """
        self.topbar_height = 180
        # 1. 배경 이미지를 가질 컨테이너 위젯 생성
        top_bar_container = QWidget()  # Topbar 최상단 컨테이너
        """ top_bar의 최상단 컨테이너"""
        top_bar_container.setMinimumHeight(self.topbar_height)
        top_bar_container.setObjectName("TopBarContainer")  # 스타일 시트용 ID

        # 메인 레이아웃 (수평정렬)
        main_h_layout = QHBoxLayout(top_bar_container)
        """ 메인 레이아웃 (수평정렬: topbar를 가로로 나눔) """
        main_h_layout.setContentsMargins(10, 0, 10, 0)  # 좌, 상, 우, 하
        main_h_layout.setSpacing(5)
        # 로고영역
        logo_area_layout = QVBoxLayout()
        logo_spacer = QSpacerItem(200, 20, QSizePolicy.Minimum, QSizePolicy.Maximum)
        logo_area_layout.addItem(logo_spacer)
        # 메뉴영역
        main_menu_v_layout = QVBoxLayout()
        """ topbar의 메뉴영역의 레이아웃 """
        btn_filter = QPushButton("비급 포함/제외 관리")
        """ 비급 필터 버튼 """
        btn_filter.setFixedWidth(140)
        btn_filter.clicked.connect(self._open_skill_filter_dialog)
        btn_talents = QPushButton("목표천부설정")
        """ 목표 천부 설정 버튼 """
        btn_talents.setFixedWidth(140)
        self.btn_solve = QPushButton("최적화 실행")
        """ 최적화 버튼 """
        self.btn_solve.setFixedWidth(140)
        self.btn_solve.setEnabled(False)
        self.btn_solve.clicked.connect(self._solve)
        btn_close = QPushButton("종료")
        btn_close.clicked.connect(self.close)  # 현재 창을 닫음
        """ 종료 버튼 """
        main_menu_v_layout.addWidget(btn_filter)
        main_menu_v_layout.addWidget(btn_talents)
        main_menu_v_layout.addWidget(self.btn_solve)
        main_menu_v_layout.addWidget(btn_close)
        # 로그영역
        log_v_layout = QVBoxLayout()
        contents_margin_top = 16
        contents_margin_bottom = 14
        log_v_layout.setContentsMargins(10, contents_margin_top, 0, contents_margin_bottom)
        log_v_layout.setSpacing(5)
        # 로그 텍스트
        self.log_label = QLabel("비급 최적화 도구 1.3.14")                # 로그 표시용
        self.status_label = QLabel("데이터를 로드하세요.")       # 상태라벨
        self.status_label.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        # 스테이터스 텍스트가 가능한 많은 가로 공간을 차지하도록 설정
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        log_v_layout.addWidget(self.log_label)
        log_v_layout.addStretch(1)                          # 로그와 상태라벨 사이벌리기
        log_v_layout.addWidget(self.status_label)
        # 가장 우측 레이아웃
        right_v_layout = QVBoxLayout()
        """ 가장 우측의 레이아웃을 세로로 분할하는 레이아웃 """
        right_v_layout.setContentsMargins(18, contents_margin_top, 0, contents_margin_bottom)
        self.btn_settings = QPushButton("설정")          # 설정버튼
        self.btn_settings.setFixedWidth(80)             # 버튼 크기 고정
        self.btn_settings.clicked.connect(self._open_settings_dialog)
        right_v_layout.addWidget(self.btn_settings, alignment=Qt.AlignRight)  # 설정버튼 우측정렬
        right_v_layout.addStretch(1)  # 설정과 플랜저장/불러오기 버튼 사이의 공간
        # 플랜부분
        right_h_layout = QHBoxLayout()
        """ 가장 오른쪽 수평분할 레이아웃 안의 수직분할레이아웃 하단의 수평분할레이아웃, 플랜저장/불러오기삽입용 """
        self.plan_name_combo = QComboBox()
        self.plan_name_combo.setPlaceholderText("새 플랜을 만들거나 불러오세요")
        self.plan_name_combo.setFixedWidth(240)
        # 플랜 버튼들
        self.btn_plan_save = QPushButton("저장")
        self.btn_plan_load = QPushButton("불러오기")
        self.btn_plan_delete = QPushButton("삭제")
        for btn in [self.btn_plan_load, self.btn_plan_save, self.btn_plan_delete]:
            btn.setFixedWidth(80)  # 모든 플랜 버튼 크기 통일
        self.btn_plan_save.clicked.connect(self._save_plan)
        self.btn_plan_load.clicked.connect(self._load_plan)
        self.btn_plan_delete.clicked.connect(self._delete_plan)
        # right_h_layout에 플랜 버튼들 추가
        right_h_layout.addWidget(self.plan_name_combo)
        right_h_layout.addWidget(self.btn_plan_save)
        right_h_layout.addWidget(self.btn_plan_load)
        right_h_layout.addWidget(self.btn_plan_delete)
        right_v_layout.addLayout(right_h_layout)  # 가장 우측 레이아웃 최하단에 플랜버튼 들어있는 수평레이아웃 추가

        # 메인 레이아웃에 수평 정렬로 추가.
        main_h_layout.addLayout(logo_area_layout)       # 로고영역만큼 비우기
        main_h_layout.addLayout(main_menu_v_layout)     # 메인메뉴 추가
        main_h_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Fixed, QSizePolicy.Fixed))
        main_h_layout.addLayout(log_v_layout)           # 로그레이아웃 추가
        main_h_layout.addLayout(right_v_layout)         # 우측 메뉴영역 추가

        # 로고
        self.logo_label = ImageButton(top_bar_container)
        logo_pixmap = QPixmap(self.logo)  # 로고 이미지 경로
        scaled_pixmap = logo_pixmap.scaledToHeight(self.topbar_height, Qt.SmoothTransformation)
        self.logo_label.setPixmap(scaled_pixmap)
        self.logo_label.setFixedSize(scaled_pixmap.size())
        # 3. 로고 위치 조정 (레이아웃 밖에서 독립적으로 움직임)
        self.logo_label.move(10, 0)  # 위치에 고정 (밀어내지 않음)
        self.logo_label.setToolTip(self._make_simple_tooltip("   최적화 실행   "))  # 툴팁
        self.logo_label.clicked.connect(self._solve)
        # 파일 환경 변수
        self.db_path_edit = QLineEdit("data/skills_kr.db")

        return top_bar_container

    def _open_settings_dialog(self):
        """
        DB 경로 / 커스텀 ID 범위를 설정하는 환경설정 다이얼로그입니다.
        """
        from PySide6.QtWidgets import QSpinBox as _QSpinBox
        from app.ui.db_manager_dialog import SkillDbManagerDialog

        dlg = QDialog(self)
        dlg.setWindowTitle("환경설정")
        dlg.resize(760, 160)

        layout = QGridLayout(dlg)

        # ── DB 경로
        db_edit = QLineEdit(self.db_path_edit.text())
        btn_db = QPushButton("선택")

        def pick_db():
            path, _ = QFileDialog.getOpenFileName(dlg, "비급 DB 선택", "", "SQLite DB (*.db);;All Files (*.*)")
            if path:
                db_edit.setText(path)

        btn_db.clicked.connect(pick_db)

        layout.addWidget(QLabel("비급 DB"), 0, 0)
        layout.addWidget(db_edit, 0, 1)
        layout.addWidget(btn_db, 0, 2)

        # ── 커스텀 ID 시작값
        custom_id_spin = _QSpinBox()
        custom_id_spin.setRange(0, 9_999_999)
        custom_id_spin.setValue(self.settings.get("custom_id_min", 1000))
        custom_id_spin.setToolTip(
            "이 값 이상의 ID를 가진 비급은 '커스텀 데이터'로 간주되어 DB 관리 창에서 삭제할 수 있습니다."
        )

        layout.addWidget(QLabel("커스텀 ID 시작값"), 1, 0)
        layout.addWidget(custom_id_spin, 1, 1)

        # ── DB 관리 버튼
        btn_manage = QPushButton("비급 DB 관리...")
        btn_manage.setToolTip("비급 데이터를 추가 / 수정 / 삭제합니다.")

        def open_manager():
            db_path = db_edit.text().strip() or self.db_path_edit.text().strip()
            custom_min = custom_id_spin.value()
            mgr = SkillDbManagerDialog(db_path, custom_id_min=custom_min, parent=dlg)
            mgr.exec()
            if mgr.data_changed:
                self.db_path_edit.setText(db_path)
                self.settings["db_path"] = db_path
                self.settings["custom_id_min"] = custom_min
                save_settings(self.settings)
                dlg.accept()
                self._load_data(silent=False)

        btn_manage.clicked.connect(open_manager)
        layout.addWidget(btn_manage, 1, 2)

        # ── 저장 / 취소
        btn_save = QPushButton("저장 후 다시 로드")
        btn_cancel = QPushButton("취소")

        def save_and_reload():
            self.db_path_edit.setText(db_edit.text().strip())
            self.settings["db_path"] = self.db_path_edit.text().strip()
            self.settings["custom_id_min"] = custom_id_spin.value()
            save_settings(self.settings)
            dlg.accept()
            self._load_data(silent=False)

        btn_save.clicked.connect(save_and_reload)
        btn_cancel.clicked.connect(dlg.reject)

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
        current_growth = format_growth_text(group.delta_current, potential=False)
        potential_growth = format_growth_text(group.delta_potential, potential=True)
        tooltip = f"""
            <div style='font-family: "Malgun Gothic", sans-serif; padding: 5px;'>
            <div style='text-align: center;'>
            <hr style='border: 0; border-top: 0px solid #555; margin: 0px 0;'>
            <b style='color: {RARITY_COLORS.get(skill.rare, "#FFFFFF")};'>[{skill.rare}] {skill.name}</b></div>
            <hr style='border: 0; border-top: 0px solid #555; margin: 0px 0;'>
                <table style='border-collapse: collapse;'>
                <tr><td style='color: #AAAAAA; padding-right: 10px;'>희귀도</td><td style='color: {RARITY_COLORS.get(skill.rare, "#FFFFFF")};'>{skill.rare}</td></tr>
                <tr><td style='color: #AAAAAA; padding-right: 10px;'>출처</td><td>{skill.force_name}</td></tr>
                <tr><td style='color: #AAAAAA; padding-right: 10px;'>종류</td><td>{skill.type_name}</td></tr>
                <tr><td style='color: #AAAAAA; padding-right: 10px;'>요구치</td><td>{needs}</td></tr>
                <tr><td style='color: #AAAAAA; padding-right: 10px;'>현재 증가</td><td>{current_growth}</td></tr>
                <tr><td style='color: #AAAAAA; padding-right: 10px;'>잠재 증가</td><td>{potential_growth}</td></tr>
                </table>
            </div>
            """

        return tooltip

    @staticmethod
    def _make_simple_tooltip(text, color="#FFFFFF") -> str:
        """
        비급 hover tooltip 내용을 생성합니다.
        """
        tooltip = f"""
                <div style='font-family: "Malgun Gothic", sans-serif; padding: 5px;'>
                <div style='text-align: center;'>
                <hr style='border: 0; border-top: 0px solid #555; margin: 0px 0;'>
                <b style='color: {color};'>{text}</b></div>
                <hr style='border: 0; border-top: 0px solid #555; margin: 0px 0;'>
                </div>
                """
        return tooltip

    @staticmethod
    def _make_summary_tooltip(force, skill_type, rare, name) -> str:
        """
        비급 hover tooltip 내용을 생성합니다.
        """
        tooltip = f"""
                <div style='font-family: Malgun Gothic;'>
                    <b style='color: {RARITY_COLORS.get(rare, "#FFFFFF")};'>[{rare}] {name}</b><br>
                    무력: {force}<br>
                    종류: {skill_type}
                </div>
                """

        return tooltip

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

        tables_layout = QHBoxLayout()
        self.target_tables = {}

        for title, stats in STAT_SECTIONS:
            sub_box = QGroupBox(title)
            layout = QVBoxLayout(sub_box)

            table = QTableWidget(len(stats), 4)
            table.setHorizontalHeaderLabels(["", "항목", "목표 현재값", "목표 잠재력"])
            table.verticalHeader().setVisible(False)
            # 커스텀 헤더 적용
            header = CheckBoxHeader(Qt.Horizontal, table)
            table.setHorizontalHeader(header)
            header.setChecked(True)
            # 클로저(Closure)를 사용하여 해당 테이블만 제어하는 함수 연결
            # 람다식에서 table=table과 같이 기본 인자를 사용하여 현재 루프의 테이블을 고정합니다.
            header.clicked.connect(lambda checked, t=table: self._set_table_checkbox(t, checked))

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

    def _set_table_checkbox(self, table: QTableWidget, checked: bool):
        """특정 테이블 내의 모든 체크박스 상태를 변경합니다."""
        for row in range(table.rowCount()):
            wrapper = table.cellWidget(row, 0)
            chk = getattr(wrapper, "checkbox", None)
            if chk:
                # 시그널 발생을 방지하려면 blockSignals를 쓸 수 있지만,
                # 여기서는 단순 UI 반영이므로 직접 설정합니다.
                chk.setChecked(checked)

    def _on_header_checkbox_toggled(self, checked: bool):
        if checked:
            self._select_all_results()
        else:
            self._deselect_all_results()

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

    def _select_all_results(self):
        last_row = self.result_table.rowCount() - 1
        if last_row >= 0:
            wrapper = self.result_table.cellWidget(last_row, 0)
            chk = getattr(wrapper, "checkbox", None)
            if chk:
                chk.setChecked(True)

        # 헤더 체크박스 상태 업데이트
        # self.header.setChecked(True)

    def _deselect_all_results(self):
        if self.result_table.rowCount() > 0:
            wrapper = self.result_table.cellWidget(0, 0)
            chk = getattr(wrapper, "checkbox", None)
            if chk:
                chk.setChecked(False)

        # 헤더 체크박스 상태 업데이트
        # self.header.setChecked(False)

    def _build_rarity_group(self):
        """
        희귀도별 최대 사용 권수 섹션을 생성합니다.
        "희귀도 제한"
        """
        box = QGroupBox("희귀도 제한")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(10, 38, 10, 14)  # 좌, 상, 우, 하 순서 (28px은 예시값이므로 조절 필요)
        outer.setSpacing(0)
        self.rarity_table = QTableWidget(0, 3)
        self.rarity_table.setHorizontalHeaderLabels(["", "희귀도", "최대 권수"])
        self.rarity_table.verticalHeader().setVisible(False)
        # 커스텀 헤더 적용
        header = CheckBoxHeader(Qt.Horizontal, self.rarity_table)
        self.rarity_table.setHorizontalHeader(header)
        header.setChecked(True)
        header.clicked.connect(lambda checked, t=self.rarity_table: self._set_table_checkbox(t, checked))

        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.rarity_table.setColumnWidth(0, 42)  # 사용 체크박스

        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
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

        # ✅ 가장 마지막에 체크된 행 번호 찾기
        if not self.completed_action_rows:
            # 체크된 게 하나도 없다면 초기 상태 표시
            max_checked_row = -1
            current_state = self.initial_state
            changed_info = {}
        else:
            max_checked_row = max(self.completed_action_rows)

            # 0행부터 가장 마지막 체크된 행(max_checked_row)까지 스탯 적용
            # (중간에 비어있는 행이 없다고 가정 - 위 로직에서 채워주므로)
            current_state = apply_book_actions_until(
                initial_state=self.initial_state,
                groups=self.result_groups,
                actions=self.result_actions,
                count=max_checked_row + 1,
            )

            # 강조 표시: 현재 선택(클릭)한 행이 체크되어 있다면 해당 행의 증가치를 강조
            changed_info = {}
            if row in self.completed_action_rows:
                action = self.result_actions[row]
                group = self.result_groups[action.group_index]
                for stat, val in group.delta_current.items():
                    if val > 0:
                        changed_info.setdefault(stat, {})["current"] = True
                for stat, val in group.delta_potential.items():
                    if val > 0:
                        changed_info.setdefault(stat, {})["potential"] = True

        # 좌측 테이블 갱신
        self._update_state_table(current_state, changed=changed_info)

        # # 0행부터 현재 행까지의 상태 계산
        # state = apply_book_actions_until(
        #     initial_state=self.initial_state,
        #     groups=self.result_groups,
        #     actions=self.result_actions,
        #     count=row + 1,
        # )
        #
        # # '현재 행'에서 실제로 증가하는 값(delta)을 추출하여 강조 표시 데이터로 전달
        # action = self.result_actions[row]
        # group = self.result_groups[action.group_index]
        #
        # changed_info = {}
        # for stat in group.delta_current:
        #     if group.delta_current[stat] > 0:
        #         changed_info.setdefault(stat, {})["current"] = True
        # for stat in group.delta_potential:
        #     if group.delta_potential[stat] > 0:
        #         changed_info.setdefault(stat, {})["potential"] = True
        #
        # self._update_state_table(state, changed=changed_info)

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
        # INFO 결과 테이블에서 행 클릭시 누적변경 되는 이벤트 연결부분 현재 체크박스로 대체하여 제외 중
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
    def _browse_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "비급 DB 선택", "", "SQLite DB (*.db);;All Files (*.*)")
        if path:
            self.db_path_edit.setText(path)

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
                cur_font = item_cur.font()
                if stat_changed.get("current"):
                    item_cur.setForeground(self.CHANGED_STAT_FG)  # 변경 시 파란색 (최우선)
                    cur_font.setBold(True)
                elif not is_target_enabled:
                    item_cur.setForeground(self.DISABLED_STAT_FG)  # 미선택 시 회색
                    cur_font.setBold(False)
                else:
                    item_cur.setForeground(self.NORMAL_STAT_FG)  # 기본 검정
                    cur_font.setBold(False)
                item_cur.setFont(cur_font)

                # 3. 잠재값(Potential) 색상 결정
                pot_font = item_pot.font()
                if stat_changed.get("potential"):
                    item_pot.setForeground(self.CHANGED_STAT_FG)  # 변경 시 파란색 (최우선)
                    pot_font.setBold(True)
                elif not is_target_enabled:
                    item_pot.setForeground(self.DISABLED_STAT_FG)  # 미선택 시 회색
                    pot_font.setBold(False)
                else:
                    item_pot.setForeground(self.NORMAL_STAT_FG)  # 기본 검정
                    pot_font.setBold(False)
                item_pot.setFont(pot_font)

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
            db_path = self.db_path_edit.text().strip()

            self.skills = load_skills_from_db(db_path)

            self.groups = group_skills(self.skills)
            self._populate_rarity_table()

            self.initial_state = self._build_initial_state_from_ui()
            self._update_state_table(self.initial_state)

            self.btn_solve.setEnabled(True)
            self.status_label.setText(f"로드 완료 | 비급 {len(self.skills)}개 | 그룹 {len(self.groups)}개")
            self.settings["db_path"] = db_path
            save_settings(self.settings)
            self._refresh_plan_list()

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
            # 기존 완료 체크를 제외 목록에 반영
            self._sync_excluded_from_completed_actions()
            # 새 최적화 실행 전 이전 결과 UI/상태 초기화
            self.completed_action_rows.clear()
            self._last_combo_indices.clear()
            self.result_actions = []
            self.result_groups = []
            self.result_table.setRowCount(0)
            self.rarity_summary_table.setRowCount(0)
            self.books_summary_table.setRowCount(0)
            self._update_state_table(self.initial_state)


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
            # self.result_groups = filtered_groups
            self.result_groups = self._build_filtered_groups()

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
            if action.group_index >= len(self.result_groups):
                print(f"⚠️ 경고: 잘못된 그룹 인덱스 접근 ({action.group_index})")
                continue
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

        # 블로킹(Signal Blocking)을 통해 무한 루프 방지
        self.result_table.blockSignals(True)

        if checked:
            # 현재 행 포함, 이전의 모든 행을 체크 상태로 만듦
            for r in range(0, row + 1):
                self._set_row_checkbox_state(r, True)
                self.completed_action_rows.add(r)
        else:
            # 현재 행 포함, 이후의 모든 행을 체크 해제 상태로 만듦
            for r in range(row, len(self.result_actions)):
                self._set_row_checkbox_state(r, False)
                self.completed_action_rows.discard(r)

        self.result_table.blockSignals(False)

        # 콤보박스 활성/비활성 처리 및 상태 반영
        if row > 0 and not checked:  # 체크 해제 시, 누적상태 전달하기 위해, 1개라도 체크되고 현재체크가 안되었을때 바로전 행을 전달
            self._apply_result_row_state(row - 1)
        else:
            self._apply_result_row_state(row)
        self._rebuild_usage_summary()

    def _set_row_checkbox_state(self, row: int, state: bool):
        """행의 체크박스 상태를 물리적으로 변경하는 헬퍼 함수"""
        wrapper = self.result_table.cellWidget(row, 0)
        chk = getattr(wrapper, "checkbox", None)
        if chk:
            chk.blockSignals(True)  # 개별 시그널 차단하여 재귀 호출 방지
            chk.setChecked(state)
            chk.blockSignals(False)

        # 콤보박스 활성화 여부도 제어
        combo = self.result_table.cellWidget(row, 3)
        if isinstance(combo, QComboBox):
            combo.setEnabled(not state)

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
            done_text = "완료" if 0 < info["rows"] == info["completed"] else ""

            # 사용된 비급 목록
            self.add_item(self.books_summary_table, row, 0, done_text, editable=False)
            self.add_item(self.books_summary_table, row, 1, rare, RARITY_COLORS.get(rare, "#FFFFFF"))
            self.add_item(self.books_summary_table, row, 2, name, RARITY_COLORS.get(rare, "#FFFFFF"))
            self.add_item(self.books_summary_table, row, 3, skill_type)
            self.add_item(self.books_summary_table, row, 4, force)
            self.add_item(self.books_summary_table, row, 5, info["levels"])

            # 툴팁추가
            target_item = self.books_summary_table.item(row, 2)

            if target_item:
                target_item.setToolTip(self._make_summary_tooltip(force, skill_type, rare, name))

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
            "계획 저장",
            "저장할 계획 이름:",
            text=default_name,
        )

        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.warning(self, "저장 실패", "계획 이름을 입력하세요.")
            return

        data = {
            "version": 2,
            "engine": "greedy_abc_needs",
            "current_values": self._collect_current_ui_values(),
            "goal_values": self._collect_goal_ui_values(),
            "rarity_limits": self._collect_rarity_ui_values(),
            "skill_filter_rules": self.skill_filter_rules,
            "excluded_skill_ids": sorted(list(self.excluded_skill_ids)),
            "completed_action_rows": sorted(list(self.completed_action_rows)),
            "result_rows": self._collect_result_rows(),
        }

        save_plan(name, data)
        self._refresh_plan_list()

        idx = self.plan_name_combo.findText(name)
        if idx >= 0:
            self.plan_name_combo.setCurrentIndex(idx)

        QMessageBox.information(self, "저장 완료", f"계획 저장 완료: {name}")

    def _load_plan(self):
        from app.plan_store import load_plan

        name = self.plan_name_combo.currentText().strip()
        if not name:
            return

        if not self.groups:
            QMessageBox.warning(self, "불러오기 실패", "먼저 데이터를 로드하세요.")
            return

        data = load_plan(name)

        self._restore_current_ui_values(data.get("current_values", {}))
        self._restore_goal_ui_values(data.get("goal_values", {}))
        self._restore_rarity_ui_values(data.get("rarity_limits", {}))

        self.skill_filter_rules = data.get(
            "skill_filter_rules",
            [{"action": "include", "kind": "all", "label": "전체"}],
        )
        self.excluded_skill_ids = set(data.get("excluded_skill_ids", []))

        self.initial_state = self._build_initial_state_from_ui()

        # 중요: 플랜의 필터 규칙/제외목록을 복원한 뒤 result_groups 재생성
        self.result_groups = self._build_filtered_groups()

        self._update_state_table(self.initial_state)
        self._restore_result_rows(data.get("result_rows", []))

        QMessageBox.information(self, "불러오기 완료", f"계획 불러오기 완료: {name}")

    def _delete_plan(self):
        from app.plan_store import delete_plan

        name = self.plan_name_combo.currentText()
        if not name:
            return
        # 삭제 확인 팝업
        reply = QMessageBox.question(
            self, "계획 삭제 확인",
            f"'{name}' 계획을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            from app.plan_store import delete_plan
            delete_plan(name)
            self._refresh_plan_list()
            self.status_label.setText(f"계획이 삭제되었습니다: {name}")

    # 플랜 저장용 헬퍼 함수들
    def _build_filtered_groups(self):  # Filter group 생성 헬퍼
        filtered_groups = []

        for g in self.groups:
            new_skills = [s for s in g.skills if self._is_skill_allowed_by_filter_rules(s)]
            if not new_skills:
                continue

            filtered_groups.append(self._clone_group_with_skills(g, new_skills))

        return filtered_groups

    def _find_result_group_index_for_saved_row(self, saved_row: dict) -> int:  # 그룹 찾기 헬퍼
        group_key = saved_row.get("group_key")

        if group_key:
            for idx, g in enumerate(self.result_groups):
                if g.key == group_key:
                    return idx

        old_index = int(saved_row.get("group_index", -1))
        if 0 <= old_index < len(self.result_groups):
            return old_index

        return -1

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
            group = self.result_groups[action.group_index]
            skill_index = getattr(action, "selected_skill_index", action.default_skill_index)
            skill = group.skills[skill_index]

            rows.append({
                "row": row,
                "group_index": action.group_index,
                "group_key": group.key,
                "book_no_in_group": action.book_no_in_group,
                "levels_used": action.levels_used,
                "default_skill_index": action.default_skill_index,
                "selected_skill_index": skill_index,
                "selected_skill_id": skill.id,
                "selected_skill_name": skill.name,
                "rare": skill.rare,
                "type_name": skill.type_name,
                "force_name": skill.force_name,
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
        self._last_combo_indices = {}

        for saved in rows:
            group_index = self._find_result_group_index_for_saved_row(saved)
            if group_index < 0:
                continue

            group = self.result_groups[group_index]

            selected_skill_id = saved.get("selected_skill_id")
            selected_skill_name = saved.get("selected_skill_name", "")

            selected_idx = -1

            if selected_skill_id is not None:
                for idx, sk in enumerate(group.skills):
                    if sk.id == selected_skill_id:
                        selected_idx = idx
                        break

            if selected_idx < 0 and selected_skill_name:
                for idx, sk in enumerate(group.skills):
                    if sk.name == selected_skill_name:
                        selected_idx = idx
                        break

            if selected_idx < 0:
                selected_idx = int(saved.get("selected_skill_index", 0))

            if selected_idx < 0 or selected_idx >= len(group.skills):
                selected_idx = 0

            action = BookAction(
                group_index=group_index,
                book_no_in_group=int(saved.get("book_no_in_group", 1)),
                levels_used=int(saved.get("levels_used", 1)),
                default_skill_index=int(saved.get("default_skill_index", selected_idx)),
                selected_skill_index=selected_idx,
            )

            self.result_actions.append(action)

            if saved.get("completed", False):
                self.completed_action_rows.add(len(self.result_actions) - 1)

        self._populate_result_table()

        for row, action in enumerate(self.result_actions):
            combo = self.result_table.cellWidget(row, 3)
            if isinstance(combo, QComboBox):
                combo.setCurrentIndex(action.selected_skill_index)
                self._last_combo_indices[row] = action.selected_skill_index

                if row in self.completed_action_rows:
                    combo.setEnabled(False)

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
        # ──────── 4,5 이외의 행들은 일반적으로 전부 같으나, 비목적 스탯을 올리기 위한 비급은 같은 그룹으로 묶일 수 있음 그경우,
        #  그룹의 현재증가 잠재증가가 달라질 수 있어서 9,10에 변경해야함
        self.add_item(self.result_table, row, 4, skill.type_name, editable=False)
        self.add_item(self.result_table, row, 5, skill.force_name, editable=False)
        self.add_item(self.result_table, row, 9, skill.delta_current, editable=False)
        self.add_item(self.result_table, row, 10, skill.delta_potential, editable=False)

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
