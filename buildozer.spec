[app]
title = QR Scanner
package.name = qrscanner
package.domain = org.example
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,xml
version = 1.0

# OpenCV — самый простой путь (собирается автоматически, но APK большой ~80–120 МБ)
requirements = python3,kivy==2.3.0,kivy_garden.xcamera,opencv,pillow

orientation = portrait
fullscreen = 0

android.permissions = CAMERA,WRITE_EXTERNAL_STORAGE
android.api = 29
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True

# для сохранения в /storage/emulated/0/Download на Android 10
android.extra_manifest_application_arguments = android:requestLegacyExternalStorage="true"