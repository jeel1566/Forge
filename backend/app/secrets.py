import ctypes
import sys


if sys.platform == "win32":
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def protect(value: str) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Forge credential storage currently requires Windows DPAPI.")
    source = ctypes.create_string_buffer(value.encode())
    source_blob = DataBlob(len(source.raw) - 1, ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    protected = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source_blob), None, None, None, None, 0, ctypes.byref(protected)):
        raise OSError("Windows could not protect the credential.")
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(protected.pbData)
