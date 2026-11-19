"""Escribe build/version_info.txt: el nombre y la versión que lleva dentro el .exe (los ve
Windows en Propiedades > Detalles, y la firma de código exige que estén puestos).
build.ps1 lo ejecuta antes de PyInstaller."""

from pathlib import Path

from version import VERSION

NAME = "Claude Usage"
TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', 'Sergio Bernabé'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'ClaudeUsage'),
      StringStruct('LegalCopyright', 'Sergio Bernabé · Licencia MIT'),
      StringStruct('OriginalFilename', 'ClaudeUsage.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x040A, 1200])])
  ]
)
"""


def version_numbers(version):
    parts = [int(n) for n in version.split(".")[:3]]
    return tuple(parts + [0] * (4 - len(parts)))


def main():
    target = Path(__file__).with_name("build") / "version_info.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_text(TEMPLATE.format(nums=version_numbers(VERSION), name=NAME,
                                      version=VERSION), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
