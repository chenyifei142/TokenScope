# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # pyqtgraph 0.14 启动时会动态导入这两个模块；显式保留可以避免
    # PyInstaller 静态分析遗漏后，发布版在冷启动阶段报缺模块。
    hiddenimports=["PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pystray",
        "PIL",
        "matplotlib",
        "scipy",
        "OpenGL",
        "cupy",
        "colorcet",
        # pyqtgraph.__init__ 会无条件导入这些顶层模块，不能从打包产物里排除。
        "pyqtgraph.console",
        "pyqtgraph.examples",
        "pyqtgraph.flowchart",
        "pyqtgraph.jupyter",
        "pyqtgraph.opengl",
        # 项目仍然只使用 QWidget 路径，未使用的 Qt Quick / QML / PDF 组件不打包。
        "PySide6.QtNetwork",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
        "PySide6.QtTest",
        "PySide6.QtVirtualKeyboard",
    ],
    noarchive=False,
    optimize=0,
)

# PySide6 hook 仍可能把未使用的 Qt 二进制带进来；这里按前缀清理。
unused_qt_prefixes = (
    "PySide6\\Qt6Network.dll",
    "PySide6\\Qt6Pdf.dll",
    "PySide6\\Qt6Qml",
    "PySide6\\Qt6Quick.dll",
    "PySide6\\Qt6VirtualKeyboard.dll",
    "PySide6\\opengl32sw.dll",
    "PySide6\\plugins\\generic\\",
    "PySide6\\plugins\\platforminputcontexts\\",
    "PySide6\\plugins\\platforms\\qdirect2d.dll",
    "PySide6\\plugins\\platforms\\qminimal.dll",
    "PySide6\\plugins\\platforms\\qoffscreen.dll",
)
a.binaries = [
    item for item in a.binaries if not item[0].replace("/", "\\").startswith(unused_qt_prefixes)
]
a.datas = [
    item for item in a.datas if not item[0].replace("/", "\\").startswith(unused_qt_prefixes)
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TokenMeter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    version="version_info.txt",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/TokenSpider.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TokenMeter",
)
