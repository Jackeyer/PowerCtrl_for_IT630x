import sys

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QStyleFactory

from power_supply.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
