from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from .domain import AppError
from .media import popen_flags


_dialog_lock = threading.Lock()


def choose_files(mode: str = "picker") -> list[str]:
    if mode not in {"picker", "drop"}:
        raise AppError("INVALID_DIALOG_MODE", "Неизвестный способ выбора файлов.")
    if os.name != "nt":
        raise AppError("WINDOWS_REQUIRED", "Системное окно выбора и нативная drop-зона доступны в Windows.", 409)
    if not _dialog_lock.acquire(blocking=False):
        raise AppError("DIALOG_OPEN", "Окно выбора уже открыто. Найдите его на панели задач.", 409)
    try:
        # Python stdout on Windows normally follows the console code page.
        # Force UTF-8 in the child as well as the parent for Cyrillic paths.
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "sloi.native", mode], capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, cwd=Path(__file__).resolve().parents[1], timeout=600, **popen_flags())
        if result.returncode:
            raise AppError("NATIVE_DIALOG_FAILED", "Не удалось открыть системное окно. Повторите выбор файла.")
        paths = json.loads(result.stdout)
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise AppError("NATIVE_DIALOG_FAILED", "Некорректный ответ системного окна.")
        return paths
    except subprocess.TimeoutExpired as exc:
        raise AppError("DIALOG_TIMEOUT", "Окно выбора закрыто по тайм-ауту. Откройте его снова.") from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise AppError("NATIVE_DIALOG_FAILED", "Не удалось прочитать ответ системного окна. Повторите выбор файла.") from exc
    finally:
        _dialog_lock.release()


def reveal_file(path: Path) -> None:
    if os.name != "nt":
        raise AppError("WINDOWS_REQUIRED", "Открытие Проводника доступно в Windows.", 409)
    if not path.is_file():
        raise AppError("RESULT_MISSING", "Файл результата не найден.", 404)
    try:
        subprocess.Popen(["explorer.exe", "/select,", str(path.resolve())])
    except OSError as exc:
        raise AppError("EXPLORER_FAILED", "Не удалось открыть Проводник. Результат можно скачать из приложения.") from exc


def windows_picker() -> list[str]:
    import ctypes as c
    from ctypes import wintypes as w
    class OPENFILENAMEW(c.Structure):
        _fields_ = [("lStructSize", w.DWORD), ("hwndOwner", w.HWND), ("hInstance", w.HINSTANCE), ("lpstrFilter", w.LPCWSTR), ("lpstrCustomFilter", w.LPWSTR), ("nMaxCustFilter", w.DWORD), ("nFilterIndex", w.DWORD), ("lpstrFile", w.LPWSTR), ("nMaxFile", w.DWORD), ("lpstrFileTitle", w.LPWSTR), ("nMaxFileTitle", w.DWORD), ("lpstrInitialDir", w.LPCWSTR), ("lpstrTitle", w.LPCWSTR), ("Flags", w.DWORD), ("nFileOffset", w.WORD), ("nFileExtension", w.WORD), ("lpstrDefExt", w.LPCWSTR), ("lCustData", c.c_ssize_t), ("lpfnHook", c.c_void_p), ("lpTemplateName", w.LPCWSTR), ("pvReserved", c.c_void_p), ("dwReserved", w.DWORD), ("FlagsEx", w.DWORD)]
    buffer = c.create_unicode_buffer(262144)
    dialog = OPENFILENAMEW()
    dialog.lStructSize = c.sizeof(dialog)
    dialog.lpstrFilter = "Аудио и видео\0*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg;*.opus;*.wma;*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.aiff;*.aif;*.mka;*.mpga\0Все файлы\0*.*\0\0"
    dialog.lpstrFile = c.cast(buffer, w.LPWSTR)
    dialog.nMaxFile = len(buffer)
    dialog.lpstrTitle = "SLOI — выбрать исходники без копирования"
    dialog.Flags = 0x00080000 | 0x00000200 | 0x00001000 | 0x00000800 | 0x00000008
    api = c.WinDLL("comdlg32", use_last_error=True)
    api.GetOpenFileNameW.argtypes = [c.POINTER(OPENFILENAMEW)]
    api.GetOpenFileNameW.restype = w.BOOL
    if not api.GetOpenFileNameW(c.byref(dialog)):
        if api.CommDlgExtendedError():
            raise OSError("GetOpenFileNameW failed")
        return []
    pieces = buffer[:].split("\0\0", 1)[0].split("\0")
    if len(pieces) == 1:
        return pieces
    return [str(Path(pieces[0]) / name) for name in pieces[1:]]


def windows_drop() -> list[str]:
    import ctypes as c
    from ctypes import wintypes as w
    user = c.WinDLL("user32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    shell = c.WinDLL("shell32", use_last_error=True)
    gdi = c.WinDLL("gdi32", use_last_error=True)
    LRESULT = c.c_ssize_t
    WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    class WNDCLASS(c.Structure):
        _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", c.c_int), ("cbWndExtra", c.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]
    user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DefWindowProcW.restype = LRESULT
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
    user.CreateWindowExW.restype = w.HWND
    user.DestroyWindow.argtypes = [w.HWND]
    user.ShowWindow.argtypes = [w.HWND, c.c_int]
    user.UpdateWindow.argtypes = [w.HWND]
    user.SetForegroundWindow.argtypes = [w.HWND]
    user.RegisterClassW.argtypes = [c.POINTER(WNDCLASS)]
    user.GetMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    user.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    user.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    user.DispatchMessageW.restype = LRESULT
    kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
    kernel.GetModuleHandleW.restype = w.HMODULE
    shell.DragAcceptFiles.argtypes = [w.HWND, w.BOOL]
    shell.DragQueryFileW.argtypes = [w.HANDLE, w.UINT, w.LPWSTR, w.UINT]
    shell.DragQueryFileW.restype = w.UINT
    shell.DragFinish.argtypes = [w.HANDLE]
    gdi.CreateSolidBrush.argtypes = [w.DWORD]
    gdi.CreateSolidBrush.restype = w.HBRUSH
    gdi.DeleteObject.argtypes = [w.HANDLE]
    paths: list[str] = []
    @WNDPROC
    def window_proc(hwnd, message, wp, lp):
        if message == 0x0233:
            count = shell.DragQueryFileW(w.HANDLE(wp), 0xFFFFFFFF, None, 0)
            for index in range(count):
                length = shell.DragQueryFileW(w.HANDLE(wp), index, None, 0)
                buffer = c.create_unicode_buffer(length + 1)
                shell.DragQueryFileW(w.HANDLE(wp), index, buffer, length + 1)
                paths.append(buffer.value)
            shell.DragFinish(w.HANDLE(wp))
            user.DestroyWindow(hwnd)
            return 0
        if message == 0x0010:
            user.DestroyWindow(hwnd)
            return 0
        if message == 0x0002:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(hwnd, message, wp, lp)
    instance = kernel.GetModuleHandleW(None)
    brush = gdi.CreateSolidBrush(0xE4F6CC)
    wc = WNDCLASS(0, window_proc, 0, 0, instance, None, None, brush, None, "SloiNativeDrop")
    if not user.RegisterClassW(c.byref(wc)):
        raise c.WinError(c.get_last_error())
    width, height = 630, 280
    x = max(0, (user.GetSystemMetrics(0) - width) // 2)
    y = max(0, (user.GetSystemMetrics(1) - height) // 2)
    hwnd = user.CreateWindowExW(0x00000008 | 0x00040000, wc.lpszClassName, "SLOI  /  ZERO-COPY DROP", 0x00CF0000, x, y, width, height, None, None, instance, None)
    if not hwnd:
        raise c.WinError(c.get_last_error())
    text = "ПЕРЕТАЩИТЕ АУДИО ИЛИ ВИДЕО СЮДА\n\nМожно несколько файлов из Проводника.\nИсходники останутся на своих местах.\n\nЗакройте это окно для отмены."
    user.CreateWindowExW(0, "STATIC", text, 0x50000001, 25, 42, 570, 155, hwnd, None, instance, None)
    shell.DragAcceptFiles(hwnd, True)
    user.ShowWindow(hwnd, 5)
    user.UpdateWindow(hwnd)
    user.SetForegroundWindow(hwnd)
    msg = w.MSG()
    while user.GetMessageW(c.byref(msg), None, 0, 0) > 0:
        user.TranslateMessage(c.byref(msg))
        user.DispatchMessageW(c.byref(msg))
    gdi.DeleteObject(brush)
    return paths


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit(2)
    selected = windows_drop() if len(sys.argv) > 1 and sys.argv[1] == "drop" else windows_picker()
    print(json.dumps(selected, ensure_ascii=False))
