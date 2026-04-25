# run_ui.py
# 이 파일은 PySide6 UI 실행 엔트리포인트입니다.

import sys
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


def main():
    """
    QApplication을 생성하고 메인 윈도우를 실행합니다.
    """
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()