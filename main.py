#!/usr/bin/env python3
# main.py

import sys
import os
import json
import requests
from urllib.parse import urlparse, parse_qs
from io import StringIO
import time

import pandas as pd

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton,
    QLabel, QScrollArea, QMessageBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QComboBox, QTableWidget, QTableWidgetItem, QSizePolicy,
    QTextEdit, QHeaderView, QProgressDialog, QInputDialog
)
from PySide6.QtGui import QFont, QPixmap, QIcon
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView

CLIENT_ID = "6121396"  # Замените на свой
REDIRECT_URI = "https://oauth.vk.com/blank.html"
API_VERSION = "5.199"
USER_DATA_FILE = "user_data.json"

HEADER_OPTIONS = ["Не использовать", "Название", "Фото", "Описание", "Цена", "Количество", "Другое"]

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
    def __init__(self, token, group_id, group_name, go_back_callback):
        super().__init__()
        self.token = token
        self.group_id = group_id
        self.group_name = group_name
        self.go_back_callback = go_back_callback
        self.setWindowTitle(f"Table Formatter - {group_name}")
        self.resize(900, 600)

        self.column_types = {}
        self.df = None
        self.selected_category_id = None

        self.setStyleSheet("""
            QWidget { font-size: 14pt; }
            QPushButton { font-size: 16pt; min-height: 40px; padding: 8px; }
            QLabel { font-size: 14pt; }
            QTextEdit { font-family: Courier; font-size: 14pt; }
        """)

        layout = QVBoxLayout(self)

        back_btn = QPushButton("← Назад")
        back_btn.clicked.connect(self.go_back_callback)
        layout.addWidget(back_btn)

        self.input_label = QLabel("Входные данные:")
        layout.addWidget(self.input_label)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Вставьте таблицу (TSV/CSV/;-CSV)...")
        self.input.setAcceptRichText(False)
        self.input.textChanged.connect(self.process_text)
        layout.addWidget(self.input)

        self.upload_btn = QPushButton("Добавить товары")
        self.upload_btn.clicked.connect(self.upload_items)
        self.upload_btn.setEnabled(False)
        layout.addWidget(self.upload_btn)

        self.table = QTableWidget()
        self.table.hide()
        layout.addWidget(self.table)

    def get_product_categories(self):
        """Получаем список категорий для товаров сообщества"""
        try:
            response = requests.get(
                "https://api.vk.com/method/market.getCategories",
                params={
                    "owner_id": f"-{abs(self.group_id)}",
                    "access_token": self.token,
                    "v": API_VERSION
                }
            ).json()

            if "error" in response:
                QMessageBox.critical(self, "Ошибка",
                                     f"Ошибка при получении категорий: {response['error']['error_msg']}")
                return None

            return response.get("response", {}).get("items", [])

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при получении категорий: {str(e)}")
            return None

    def show_category_dialog(self):
        """Показываем диалог выбора категории"""
        categories = self.get_product_categories()
        if not categories:
            # Создаем базовые категории, если их нет
            categories = [
                {"id": 1, "name": "Одежда"},
                {"id": 2, "name": "Обувь"},
                {"id": 3, "name": "Аксессуары"},
                {"id": 4, "name": "Электроника"},
                {"id": 5, "name": "Другое"}
            ]

        dialog = QDialog(self)
        dialog.setWindowTitle("Выбор категории")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout()

        label = QLabel("Выберите категорию для товаров:")
        layout.addWidget(label)

        category_combo = QComboBox()
        for category in categories:
            category_combo.addItem(category["name"], category["id"])

        # Добавляем возможность создания новой категории
        category_combo.addItem("+ Создать новую категорию", -1)
        layout.addWidget(category_combo)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.Accepted:
            selected_id = category_combo.currentData()
            if selected_id == -1:
                # Создаем новую категорию
                new_category, ok = QInputDialog.getText(
                    self, "Новая категория", "Введите название новой категории:")
                if ok and new_category:
                    # Здесь можно добавить логику создания категории через API
                    return {"id": len(categories)+1, "name": new_category}
                return None
            return {"id": selected_id, "name": category_combo.currentText()}
        return None

    def process_text(self):
        raw = self.input.toPlainText().strip()

        if not raw:
            self.table.hide()
            self.input_label.show()
            self.input.show()
            self.upload_btn.setEnabled(False)
            return

        first = raw.splitlines()[0]
        for sep in ['\t', ',', ';']:
            if sep in first:
                break

        try:
            self.df = pd.read_csv(StringIO(raw), sep=sep)
        except Exception as e:
            self.table.hide()
            self.input_label.show()
            self.input.show()
            self.upload_btn.setEnabled(False)
            QMessageBox.critical(self, "Ошибка при разборе таблицы", str(e))
            return

        self.input_label.hide()
        self.input.hide()
        self.table.show()
        self.upload_btn.setEnabled(True)
        self.populate_table(self.df)

    def populate_table(self, df: pd.DataFrame):
        rows, cols = df.shape
        self.table.clear()
        self.table.setRowCount(rows + 1)
        self.table.setColumnCount(cols)

        for j, col in enumerate(df.columns):
            combo = QComboBox()
            combo.addItems(HEADER_OPTIONS)
            combo.setCurrentText("Не использовать")
            combo.currentTextChanged.connect(lambda text, col=j: self.update_column_type(col, text))
            self.table.setCellWidget(0, j, combo)

        for i in range(rows):
            for j, val in enumerate(df.iloc[i]):
                self.table.setItem(i+1, j, QTableWidgetItem(str(val)))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setDefaultSectionSize(150)
        header.setMaximumSectionSize(300)

    def update_column_type(self, column_index, column_type):
        self.column_types[column_index] = column_type

    def upload_items(self):
        if not hasattr(self, 'df') or self.df is None:
            QMessageBox.warning(self, "Ошибка", "Нет данных для загрузки")
            return

        # Выбираем категорию
        category = self.show_category_dialog()
        if not category:
            return

        self.selected_category_id = category["id"]
        category_name = category["name"]

        # Собираем данные из таблицы, игнорируя колонки с "Не использовать"
        items = []
        required_fields = {"Название", "Описание", "Цена"}
        used_columns = {k: v for k, v in self.column_types.items() if v != "Не использовать"}

        # Проверяем обязательные поля
        missing_fields = required_fields - set(used_columns.values())
        if missing_fields:
            QMessageBox.warning(self, "Ошибка",
                                f"Не выбраны обязательные поля: {', '.join(missing_fields)}")
            return

        for i in range(len(self.df)):
            item = {
                "name": "",
                "description": "",
                "price": 0,
                "quantity": 1,
                "photo_url": "",
                "category": category_name
            }

            for j in used_columns:
                col_type = used_columns[j]
                value = str(self.df.iloc[i, j])

                if col_type == "Название":
                    item["name"] = value
                elif col_type == "Описание":
                    item["description"] = value
                elif col_type == "Цена":
                    try:
                        item["price"] = float(value)
                    except:
                        item["price"] = 0
                elif col_type == "Количество":
                    try:
                        item["quantity"] = int(value)
                    except:
                        item["quantity"] = 1
                elif col_type == "Фото":
                    item["photo_url"] = value

            # Проверка данных перед добавлением
            if len(item["name"]) < 4:
                QMessageBox.warning(self, "Ошибка",
                                    f"Строка {i+1}: Название слишком короткое (мин. 4 символа)")
                continue

            if not item["description"]:
                QMessageBox.warning(self, "Ошибка",
                                    f"Строка {i+1}: Отсутствует описание")
                continue

            if item["price"] <= 0:
                QMessageBox.warning(self, "Ошибка",
                                    f"Строка {i+1}: Цена должна быть больше 0")
                continue

            items.append(item)

        if not items:
            QMessageBox.warning(self, "Ошибка", "Нет товаров для загрузки после проверки")
            return

        progress = QProgressDialog("Загрузка товаров...", "Отмена", 0, len(items), self)
        progress.setWindowTitle("Загрузка")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        success_count = 0
        for i, item in enumerate(items):
            progress.setValue(i)
            if progress.wasCanceled():
                break

            try:
                # Загрузка фото (если указано)
                photo_ids = []
                if item["photo_url"]:
                    try:
                        # Получаем сервер для загрузки
                        upload_server = requests.get(
                            "https://api.vk.com/method/photos.getMarketUploadServer",
                            params={
                                "group_id": abs(self.group_id),
                                "main_photo": 1,
                                "access_token": self.token,
                                "v": API_VERSION
                            }
                        ).json()

                        if "error" in upload_server:
                            raise Exception(upload_server["error"]["error_msg"])

                        upload_url = upload_server["response"]["upload_url"]

                        # Загружаем фото по URL
                        photo_data = requests.get(item["photo_url"], timeout=10).content
                        upload_response = requests.post(
                            upload_url,
                            files={"file": ("photo.jpg", photo_data, "image/jpeg")},
                            timeout=30
                        ).json()

                        if "error" in upload_response:
                            raise Exception(upload_response["error"]["error_msg"])

                        # Сохраняем фото
                        save_response = requests.get(
                            "https://api.vk.com/method/photos.saveMarketPhoto",
                            params={
                                "group_id": abs(self.group_id),
                                "photo": upload_response["photo"],
                                "server": upload_response["server"],
                                "hash": upload_response["hash"],
                                "crop_data": upload_response.get("crop_data", ""),
                                "crop_hash": upload_response.get("crop_hash", ""),
                                "access_token": self.token,
                                "v": API_VERSION
                            }
                        ).json()

                        if "error" in save_response:
                            raise Exception(save_response["error"]["error_msg"])

                        photo_ids = [str(photo["id"]) for photo in save_response["response"]]

                    except Exception as e:
                        print(f"Ошибка загрузки фото: {str(e)}")
                        QMessageBox.warning(self, "Ошибка фото",
                                            f"Не удалось загрузить фото для товара {item['name']}: {str(e)}")

                # Создаем товар в сообществе (ключевое изменение - owner_id с минусом)
                params = {
                    "owner_id": f"-{abs(self.group_id)}",  # Отрицательный ID для сообщества
                    "name": item["name"],
                    "description": item["description"],
                    "category_id": self.selected_category_id,
                    "price": item["price"],
                    "access_token": self.token,
                    "v": API_VERSION
                }

                if photo_ids:
                    params["main_photo_id"] = photo_ids[0]

                response = requests.get("https://api.vk.com/method/market.add", params=params).json()

                if "error" in response:
                    error_msg = response['error']['error_msg']
                    if "name should be at least 4 letters" in error_msg:
                        error_msg = "Название должно содержать минимум 4 символа"
                    QMessageBox.warning(self, "Ошибка",
                                        f"Ошибка при добавлении товара {item['name']}:\n{error_msg}")
                else:
                    success_count += 1

                time.sleep(0.5)  # Задержка между запросами

            except Exception as e:
                QMessageBox.warning(self, "Ошибка",
                                    f"Ошибка при добавлении товара {item['name']}:\n{str(e)}")

        progress.setValue(len(items))
        QMessageBox.information(
            self,
            "Готово",
            f"Загрузка завершена!\nУспешно добавлено: {success_count}/{len(items)} товаров\n"
            f"Категория: {category_name}"
        )

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VK Product Uploader")
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

    def show_table_formatter(self, group_id, group_name):
        self.setCentralWidget(TableFormatWindow(
            self.user_token,
            group_id,
            group_name,
            self.show_group_selector
        ))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("img/icon.ico"))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())