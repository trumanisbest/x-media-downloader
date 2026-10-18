"""PyInstaller hook：gallery-dl 的 extractor/downloader 都是动态导入，需显式收集"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for pkg in ("gallery_dl", "gallery_dl.extractor", "gallery_dl.downloader",
            "gallery_dl.postprocessor"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:  # noqa: BLE001
        pass
hiddenimports = sorted(set(hiddenimports))
