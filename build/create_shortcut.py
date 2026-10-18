"""用 IShellLinkW 创建 .lnk 快捷方式（纯 ctypes，不依赖 pywin32）"""
import ctypes
import os
import sys
from ctypes import wintypes, byref, POINTER

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def iid(text):
    g = GUID()
    ole32.IIDFromString(text, byref(g))
    return g


CLSID_SHELL_LINK = iid("{00021401-0000-0000-C000-000000000046}")
IID_ISHELL_LINK_W = iid("{000214F9-0000-0000-C000-000000000046}")
IID_IPERSIST_FILE = iid("{0000010b-0000-0000-C000-000000000046}")

LPCOLESTR = ctypes.c_wchar_p


def vtable_call(ptr, index, restype, *argtypes):
    """取 COM 虚函数表第 index 个方法（自动补 this 指针参数）"""
    addr = ctypes.cast(ptr, POINTER(POINTER(ctypes.c_void_p))).contents[index]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(addr)


def create_shortcut(link_path, target, workdir="", icon="", desc=""):
    ole32.CoInitialize(None)
    pobj = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(byref(CLSID_SHELL_LINK), None, 1,  # CLSCTX_INPROC_SERVER
                                byref(IID_ISHELL_LINK_W), byref(pobj))
    if hr != 0:
        raise OSError("CoCreateInstance failed: 0x%08x" % hr)

    set_path = vtable_call(pobj, 20, wintypes.HRESULT, LPCOLESTR)
    set_wd = vtable_call(pobj, 9, wintypes.HRESULT, LPCOLESTR)
    set_desc = vtable_call(pobj, 7, wintypes.HRESULT, LPCOLESTR)
    set_icon = vtable_call(pobj, 17, wintypes.HRESULT, wintypes.INT, LPCOLESTR)
    set_show = vtable_call(pobj, 15, wintypes.HRESULT, wintypes.INT)

    set_path(pobj, target)
    if workdir:
        set_wd(pobj, workdir)
    if desc:
        set_desc(pobj, desc)
    if icon:
        set_icon(pobj, 0, icon)
    set_show(pobj, 1)  # SW_SHOWNORMAL

    # IUnknown::QueryInterface(riid, ppv) → IPersistFile
    qi = vtable_call(pobj, 0, wintypes.HRESULT, POINTER(GUID),
                     POINTER(ctypes.c_void_p))
    ppf = ctypes.c_void_p()
    hr = qi(pobj, byref(IID_IPERSIST_FILE), byref(ppf))
    if hr != 0:
        raise OSError("QueryInterface(IPersistFile) failed: 0x%08x" % hr)

    # IPersistFile::Save(lpwszFileName, fRemember)
    save = vtable_call(ppf, 6, wintypes.HRESULT, LPCOLESTR, wintypes.BOOL)
    hr = save(ppf, link_path, True)
    if hr != 0:
        raise OSError("IPersistFile.Save failed: 0x%08x" % hr)
    ole32.CoUninitialize()
    return link_path


def desktop_dir():
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)  # CSIDL_DESKTOP
    return buf.value


def start_menu_dir():
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.shell32.SHGetFolderPathW(None, 2, None, 0, buf)  # CSIDL_PROGRAMS
    return buf.value


if __name__ == "__main__":
    target = sys.argv[1]
    workdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(target)
    name = sys.argv[3] if len(sys.argv) > 3 else "X 媒体下载器"
    desc = "下载 X (Twitter) 博主的图片与视频"
    made = []
    for folder in (desktop_dir(), start_menu_dir()):
        if not folder or not os.path.isdir(folder):
            continue
        path = os.path.join(folder, name + ".lnk")
        try:
            create_shortcut(path, target, workdir, target, desc)
            made.append(path)
        except Exception as exc:  # noqa: BLE001
            print("FAIL", path, exc)
    for p in made:
        print("OK  ", p)
