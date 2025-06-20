#!/usr/bin/env python3
# main.py

import sys
import os
import json
import requests
from urllib.parse import urlparse, parse_qs
from io import StringIO

import pandas as pd

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton,
    QLabel, QScrollArea, QMessageBox,
    QHBoxLayout, QComboBox, QTableWidget, QTableWidgetItem, QSizePolicy, QTextEdit, QHeaderView
)
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView

CLIENT_ID = "6121396"  # Замените на свой
REDIRECT_URI = "https://oauth.vk.com/blank.html"
API_VERSION = "5.199"
USER_DATA_FILE = "user_data.json"

# Возможные заголовки столбцов для переименования
HEADER_OPTIONS = ["Название", "Фото", "Описание", "Цена", "Количество", "Другое"]


def save_user_data(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


class AuthWindow(QWidget):
    def __init__(self, on_token_received):
        super().__init__()
        self.on_token_received = on_token_received
        self.setWindowTitle("Авторизация ВКонтакте")
        self.resize(800, 600)
        layout = QVBoxLayout()
        self.webview = QWebEngineView()
        layout.addWidget(self.webview)
        self.setLayout(layout)
        self.start_auth()

    def start_auth(self):
        url = (
            f"https://oauth.vk.com/authorize?client_id={CLIENT_ID}"
            f"&display=page&redirect_uri={REDIRECT_URI}"
            f"&scope=market,photos,groups,offline"
            f"&response_type=token&v={API_VERSION}"
        )
        self.webview.load(QUrl(url))
        self.webview.urlChanged.connect(self.check_redirect)

    def check_redirect(self, qurl):
        if "access_token=" in qurl.toString():
            fragment = urlparse(qurl.toString()).fragment
            params = parse_qs(fragment)
            token = params.get("access_token", [None])[0]
            if token:
                save_user_data({"access_token": token})
                self.on_token_received(token)
                self.close()


class GroupSelector(QWidget):
    def __init__(self, token, on_group_selected, logout_callback):
        super().__init__()
        self.token = token
        self.on_group_selected = on_group_selected
        self.logout_callback = logout_callback
        self.setWindowTitle("Выбор сообщества")
        self.resize(600, 500)
        layout = QVBoxLayout()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll)

        logout_btn = QPushButton("Выйти")
        logout_btn.clicked.connect(self.logout)
        layout.addWidget(logout_btn)

        self.setLayout(layout)
        self.load_groups()

    def logout(self):
        if os.path.exists(USER_DATA_FILE):
            os.remove(USER_DATA_FILE)
        self.logout_callback()

    def load_groups(self):
        resp = requests.get("https://api.vk.com/method/groups.get", params={
            "access_token": self.token,
            "extended": 1,
            "filter": "admin",
            "v": API_VERSION
        }).json()
        for group in resp.get("response", {}).get("items", []):
            self.add_group_card(group)

    def add_group_card(self, group):
        card = QWidget()
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)

        image = QLabel()
        image.setFixedSize(60, 60)
        try:
            r = requests.get(group["photo_100"])
            pixmap = QPixmap()
            pixmap.loadFromData(r.content)
            image.setPixmap(pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            pass

        name = QLabel(group["name"])
        name.setStyleSheet("font-size: 16px; color: white; padding-left: 20px;")

        card_layout.addWidget(image)
        card_layout.addWidget(name)
        card.setStyleSheet(
            "QWidget { background-color: #2d2d2d; border-radius: 8px; }"
            "QWidget:hover { background-color: #3c3c3c; }"
        )

        card.mousePressEvent = lambda e, gid=group["id"], gname=group["name"]: self.on_group_selected(gid, gname)
        self.content_layout.addWidget(card)


class TableFormatWindow(QWidget):
    def __init__(self, go_back_callback):
        super().__init__()
        self.go_back_callback = go_back_callback
        self.setWindowTitle("Table Formatter")
        self.resize(900, 600)

        # Размеры шрифтов и кнопок покрупнее
        self.setStyleSheet("""
            QWidget { font-size: 14pt; }
            QPushButton { font-size: 16pt; min-height: 40px; padding: 8px; }
            QLabel { font-size: 14pt; }
            QTextEdit { font-family: Courier; font-size: 14pt; }
        """)

        layout = QVBoxLayout(self)

        # Кнопка «Назад»
        back_btn = QPushButton("← Назад")
        back_btn.clicked.connect(self.go_back_callback)
        layout.addWidget(back_btn)

        # Метка и поле ввода
        self.input_label = QLabel("Входные данные:")
        layout.addWidget(self.input_label)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Вставьте таблицу (TSV/CSV/;-CSV)...")
        self.input.setAcceptRichText(False)
        self.input.textChanged.connect(self.process_text)
        layout.addWidget(self.input)

        # Таблица создаётся один раз, но сразу скрывается
        self.table = QTableWidget()
        self.table.hide()
        layout.addWidget(self.table)

    def process_text(self):
        raw = self.input.toPlainText().strip()

        # Если поле пустое — вернуть ввод и скрыть таблицу
        if not raw:
            self.table.hide()
            self.input_label.show()
            self.input.show()
            return

        # Определяем разделитель
        first = raw.splitlines()[0]
        for sep in ['\t', ',', ';']:
            if sep in first:
                break

        # Пытаемся разобрать DataFrame
        try:
            df = pd.read_csv(StringIO(raw), sep=sep)
        except Exception as e:
            # При ошибке тоже скрываем таблицу и показываем ввод
            self.table.hide()
            self.input_label.show()
            self.input.show()
            QMessageBox.critical(self, "Ошибка при разборе таблицы", str(e))
            return

        # Успешно распарсили — прячем ввод, показываем таблицу и заполняем её
        self.input_label.hide()
        self.input.hide()
        self.table.show()
        self.populate_table(df)

    def populate_table(self, df: pd.DataFrame):
        # (сюда вставьте вашу логику разбора фото-столбца и создания виджетов)
        rows, cols = df.shape
        self.table.clear()
        self.table.setRowCount(rows + 1)
        self.table.setColumnCount(cols)
        # заголовки — комбобоксы
        for j, col in enumerate(df.columns):
            combo = QComboBox()
            combo.addItems(HEADER_OPTIONS)
            self.table.setCellWidget(0, j, combo)
        # данные
        for i in range(rows):
            for j, val in enumerate(df.iloc[i]):
                self.table.setItem(i+1, j, QTableWidgetItem(str(val)))
        # подгоняем ширины
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setDefaultSectionSize(150)
        header.setMaximumSectionSize(300)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VK Market Uploader / Table Formatter")
        self.resize(900, 600)
        user = load_user_data()
        if user and user.get("access_token"):
            self.user_token = user["access_token"]
            self.show_group_selector()
        else:
            self.show_auth()

    def show_auth(self):
        self.setCentralWidget(AuthWindow(self.on_token))

    def on_token(self, token):
        save_user_data({"access_token": token})
        self.user_token = token
        self.show_group_selector()

    def show_group_selector(self):
        self.setCentralWidget(GroupSelector(
            self.user_token,
            self.show_table_formatter,
            self.show_auth
        ))

    def show_table_formatter(self, group_id=None, group_name=None):
        self.setCentralWidget(TableFormatWindow(self.show_group_selector))

if __name__ == "__main__":
    from PySide6.QtGui import QIcon
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("img/icon.ico"))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
