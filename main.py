# main.py
import os
import time
import datetime
import threading
import xml.etree.ElementTree as ET

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

# ---------- превью камеры (только Android) ----------
if platform == 'android':
    from kivy_garden.xcamera import XCamera

# ---------- декодеры: OpenCV (основной) и/или pyzbar ----------
DECODER = None
try:
    import cv2
    import numpy as np
    DECODER = 'opencv'
except Exception:
    pass

try:
    from pyzbar.pyzbar import decode as _zbar_decode
    from PIL import Image
    if DECODER is None:
        DECODER = 'pyzbar'
except Exception:
    pass


def decode_raw(raw: bytes, size, fmt='RGBA'):
    """raw — сырые пиксели текстуры (RGBA), возвращает список найденных строк."""
    w, h = size
    found = []

    if DECODER == 'opencv':
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 4))
        frame = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        det = cv2.QRCodeDetector()
        for _ in range(4):  # пробуем 4 поворота
            data, _pts, _ = det.detectAndDecode(frame)
            if data:
                found.append(data)
                break
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        return found

    if DECODER == 'pyzbar':
        img = Image.frombytes('RGBA', (w, h), raw).convert('RGB')
        for angle in (0, 90, 180, 270):
            im = img if angle == 0 else img.rotate(angle, expand=True)
            for sym in _zbar_decode(im):
                try:
                    txt = sym.data.decode('utf-8')
                except UnicodeDecodeError:
                    txt = sym.data.decode('latin-1')
                if txt and txt not in found:
                    found.append(txt)
            if found:
                break

    return found


# ---------- хранилище ----------
class ScanStore:
    def __init__(self):
        self.folder = self._resolve_folder()
        self.txt_path = os.path.join(self.folder, 'scans.txt')
        self.xml_path = os.path.join(self.folder, 'scans.xml')
        if not os.path.exists(self.xml_path):
            root = ET.Element('scans')
            ET.ElementTree(root).write(self.xml_path, encoding='utf-8', xml_declaration=True)

    @staticmethod
    def _resolve_folder():
        if platform == 'android':
            base = '/storage/emulated/0/Download'
            # если общая папка недоступна — пишем в приватную папку приложения
            if not os.path.isdir(base):
                base = App.get_running_app().user_data_dir
            return os.path.join(base, 'QRScanner')
        # desktop (для отладки)
        return os.path.join(os.path.expanduser('~'), 'QRScanner')

    def add(self, content: str):
        ts = datetime.datetime.now().isoformat(timespec='seconds')
        # TXT: одна строка = один скан
        with open(self.txt_path, 'a', encoding='utf-8') as f:
            f.write(ts + '\t' + content.replace('\t', ' ').replace('\n', ' ') + '\n')
        # XML: добавляем элемент
        tree = ET.parse(self.xml_path)
        root = tree.getroot()
        el = ET.SubElement(root, 'scan', {'time': ts})
        el.text = content
        tree.write(self.xml_path, encoding='utf-8', xml_declaration=True)

    def reload_xml(self):
        """Если файл удалили/повредили — пересоздаём."""
        if not os.path.exists(self.xml_path):
            root = ET.Element('scans')
            ET.ElementTree(root).write(self.xml_path, encoding='utf-8', xml_declaration=True)


# ---------- UI ----------
KV = """
<Root>:
    orientation: 'vertical'
    BoxLayout:
        size_hint_y: 0.60
        XCamera:
            id: cam
            play: app.camera_play
            resolution: (1280, 720)
    Label:
        size_hint_y: None
        height: '44dp'
        text: app.status
        font_size: '15sp'
        color: 0.1, 0.35, 0.7, 1
        text_size: self.width - 20, None
        halign: 'center'
    BoxLayout:
        size_hint_y: None
        height: '52dp'
        spacing: '8dp'
        padding: '8dp', 0
        Button:
            text: 'Стоп' if app.auto_scan else 'Старт'
            on_release: app.toggle_scan()
        Button:
            text: 'Сканировать сейчас'
            on_release: app.scan_now()
    Label:
        size_hint_y: None
        height: '22dp'
        text: 'Папка: ' + app.folder
        font_size: '11sp'
        color: 0.4, 0.4, 0.4, 1
        text_size: self.width - 20, None
        halign: 'center'
    ScrollView:
        Label:
            size_hint_y: None
            height: self.texture_size[1]
            text: app.last_texts or 'Сканирований пока нет'
            font_size: '13sp'
            padding: '10dp', '6dp'
            text_size: self.width - 20, None
            halign: 'left'
"""


class Root(BoxLayout):
    pass


class QRApp(App):
    status = StringProperty('Инициализация...')
    folder = StringProperty('')
    last_texts = StringProperty('')
    camera_play = BooleanProperty(True)
    auto_scan = BooleanProperty(True)

    def build(self):
        self.store = ScanStore()
        self.folder = self.store.folder
        self._busy = False
        self._recent = {}       # text -> timestamp (антидубли)
        self._history = []      # [(ts, text), ...]
        self._decoder = DECODER or 'НЕТ'
        self.status = f'Декодер: {self._decoder}. Наведите камеру на QR.'

        Builder.load_string(KV)
        root = Root()

        Clock.schedule_interval(self._tick, 1.0)
        return root

    # ---------- Android lifecycle ----------
    def on_start(self):
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.CAMERA,
                                     Permission.WRITE_EXTERNAL_STORAGE])
            except Exception:
                pass

    def on_pause(self):
        self.camera_play = False
        return True

    def on_resume(self):
        self.camera_play = True

    # ---------- сканирование ----------
    def toggle_scan(self):
        self.auto_scan = not self.auto_scan
        self.status = 'Автосканирование включено' if self.auto_scan else 'Автосканирование остановлено'

    def scan_now(self):
        self._busy = False
        self._tick(0)

    def _tick(self, dt):
        if not self.auto_scan or self._busy:
            return
        try:
            texture = self.root.ids.cam.texture
        except Exception:
            texture = None
        if texture is None:
            self.status = 'Ожидание камеры...'
            return

        # копируем пиксели в главном потоке — быстро и безопасно
        try:
            raw = bytes(texture.pixels)
            size = tuple(texture.size)
        except Exception:
            return

        self._busy = True
        threading.Thread(target=self._worker, args=(raw, size), daemon=True).start()

    def _worker(self, raw, size):
        try:
            texts = decode_raw(raw, size)
        except Exception as e:
            texts = []
            Clock.schedule_once(lambda dt: setattr(self, 'status', f'Ошибка декодера: {e}'))
        Clock.schedule_once(lambda dt: self._on_decoded(texts), 0)

    def _on_decoded(self, texts):
        self._busy = False
        now = time.time()

        if not texts:
            self.status = 'Код не найден. Наведите камеру ближе...'
            return

        saved_any = False
        for text in texts:
            last = self._recent.get(text, 0)
            if now - last < 5:      # антидубль: тот же код не чаще 1 раза в 5 сек
                continue
            self._recent[text] = now
            self.store.add(text)
            self._history.insert(0, (datetime.datetime.now().strftime('%H:%M:%S'), text))
            self._history = self._history[:15]
            saved_any = True

        # чистим кэш антидубля
        self._recent = {k: v for k, v in self._recent.items() if now - v < 300}

        if saved_any:
            self.status = '✅ Сохранено в scans.txt и scans.xml'
            self.last_texts = '\n'.join(f'[{ts}] {t}' for ts, t in self._history)
        else:
            self.status = 'Этот код уже недавно сканировался'


if __name__ == '__main__':
    QRApp().run()