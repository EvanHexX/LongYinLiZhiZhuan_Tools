# app/appearance_converter.py
"""
이 모듈은 외형 데이터를 관리하는 PySide6 GUI 어플리케이션입니다.
선택한 행의 데이터를 이름 제외 수치값부터 슬래시(/)로 변환하며,
내보내기 시 자동으로 클립보드에 복사합니다.
"""

import sys
import os
import csv
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton,
                               QTableWidget, QTableWidgetItem, QLineEdit,
                               QLabel, QHBoxLayout, QMessageBox, QHeaderView)
from PySide6.QtGui import QGuiApplication  # ✅ 클립보드 사용을 위해 추가
from PySide6.QtCore import Qt

# ✅ 사용자 환경에 맞춘 경로 설정
DATA_FILE_PATH = "../data/appearance_data.csv"


class AppearanceManager(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_csv_to_table()

    def init_ui(self):
        self.setWindowTitle("Appearance Table Manager")
        self.setGeometry(100, 100, 900, 600)
        layout = QVBoxLayout()

        # 테이블 설정 📊
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.label_info = QLabel("선택한 행의 데이터 (자동 복사됨):")
        layout.addWidget(self.label_info)

        self.io_field = QLineEdit()
        self.io_field.setPlaceholderText("내보내기 시 여기에 결과가 표시되고 클립보드에 복사됩니다.")
        layout.addWidget(self.io_field)

        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("선택 행 내보내기 & 복사")
        self.btn_add = QPushButton("데이터 추가")
        self.btn_delete = QPushButton("선택 행 삭제")
        self.btn_save = QPushButton("CSV 저장")

        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # 시그널 연결
        self.btn_export.clicked.connect(self.export_selected_row)
        self.btn_add.clicked.connect(self.add_row_from_field)
        self.btn_delete.clicked.connect(self.delete_selected_row)
        self.btn_save.clicked.connect(self.save_table_to_csv)

    def load_csv_to_table(self):
        """
        ✅ 핵심 기능: CSV 로드 후 테이블 헤더 및 데이터 세팅
        """
        if not os.path.exists(DATA_FILE_PATH):
            return

        self.table.setRowCount(0)
        try:
            with open(DATA_FILE_PATH, "r", encoding="utf-8") as f:
                reader = list(csv.reader(f))
                if not reader: return

                header = [h.strip() for h in reader[0]]
                self.table.setColumnCount(len(header))
                self.table.setHorizontalHeaderLabels(header)

                for row_idx, row_data in enumerate(reader[1:]):
                    self.table.insertRow(row_idx)
                    for col_idx, value in enumerate(row_data):
                        self.table.setItem(row_idx, col_idx, QTableWidgetItem(value.strip()))
        except Exception as e:
            print(f"로드 오류: {e}")

    def export_selected_row(self):
        """
        ✅ 핵심 수정: 사용처 규칙 반영
        - 이름 제외 후 1~10번째 데이터를 가져오되,
        - 8번째 자리에 5번째(index 4) 데이터의 값을 한 번 더 삽입합니다.
        """
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "알림", "행을 선택해주세요.")
            return

        # 1. 이름 제외 모든 수치 데이터 수집 (얼굴형~피부색)
        raw_values = []
        for col in range(1, self.table.columnCount()):
            item = self.table.item(selected_row, col)
            raw_values.append(item.text() if item else "0")

        # 2. 규칙 적용: 8번째 자리에 5번째 값(index 4)을 추가 삽입
        # 예: [0, 0, 1, 2, 3, 4, 5, -1, -1, 0] -> 5번째 값 '3' 추출
        # 결과: [0, 0, 1, 2, 3, 4, 5, '3', -1, -1, 0]
        if len(raw_values) >= 5:
            extra_value = raw_values[4]  # 5번째 데이터
            raw_values.insert(7, extra_value)  # 8번째 자리(index 7)에 삽입

        formatted = "/".join(raw_values)

        # 필드 표시 및 클립보드 복사
        self.io_field.setText(formatted)
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(formatted)

        self.label_info.setText(f"규칙 적용 복사 완료: {formatted}")

    def add_row_from_field(self):
        """
        ✅ 핵심 수정: 추가 시에는 중복된 8번째 데이터를 제거하고 테이블에 입력
        """
        raw_text = self.io_field.text().strip()
        if not raw_text: return

        parts = [p.strip() for p in raw_text.split('/')]

        # 8번째 자리에 중복 데이터가 들어있는 상태라면(길이가 11인 경우) 해당 값 제거
        if len(parts) > 10:
            parts.pop(7)  # 삽입되었던 8번째 값 제거하여 원본 CSV 구조(10개 컬럼)로 복원

        new_row_idx = self.table.rowCount()
        self.table.insertRow(new_row_idx)
        self.table.setItem(new_row_idx, 0, QTableWidgetItem(f"New_Char_{new_row_idx + 1}"))

        # 테이블의 수치 컬럼(1~10번)에 순서대로 채움
        for i, val in enumerate(parts):
            table_col = i + 1
            if table_col < self.table.columnCount():
                self.table.setItem(new_row_idx, table_col, QTableWidgetItem(val))

        self.io_field.clear()

    def delete_selected_row(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            self.table.removeRow(selected_row)

    def save_table_to_csv(self):
        try:
            with open(DATA_FILE_PATH, "w", encoding="utf-8", newline='') as f:
                writer = csv.writer(f)
                headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                writer.writerow(headers)

                for row in range(self.table.rowCount()):
                    row_data = [self.table.item(row, col).text() if self.table.item(row, col) else ""
                                for col in range(self.table.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "성공", "CSV 파일이 업데이트되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"저장 실패: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AppearanceManager()
    window.show()
    sys.exit(app.exec())