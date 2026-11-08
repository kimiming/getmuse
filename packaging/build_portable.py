"""Assemble the portable Windows folder without copying any user data.

Run this after PyInstaller has produced ``dist/MuseAuto.exe`` and
``dist/MuseAutoCLI.exe``:

    python packaging/build_portable.py

The resulting folder contains empty/template mailbox and invite files plus a
blank five-column ``muse账号.xls``.  It never copies the developer's real
``outlookMail.txt``, ``changeEmailInfo``, ``registerEmail.txt.txt``,
``inviteCode.txt``, ``muse账号.xls``, logs, artifacts or GUI state.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import xlwt

HEADERS = ("账号", "创建时间", "账号-api", "邀请码", "本号邀请码")


def _write_blank_xls(path: Path) -> None:
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("muse账号")
    style = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour gray25;")
    for col, header in enumerate(HEADERS):
        sheet.write(0, col, header, style)
    for col, width in enumerate((40, 22, 120, 20, 20)):
        sheet.col(col).width = width * 256
    book.save(str(path))


def _template_settings(root: Path) -> dict:
    source = json.loads((root / "config" / "settings.json").read_text(encoding="utf-8"))
    raw = json.loads(json.dumps(source))
    raw.setdefault("vmos", {})["hosts"] = []
    raw["vmos"]["scan"] = True
    raw.setdefault("mail", {})["api_key"] = ""
    run = raw.setdefault("run", {})
    run["invite_code"] = ""
    run["mail_source"] = "onlineDispoMail"
    run["steps"] = "1,2,3,4,5,6"
    run["first_names"] = ""
    run["last_names"] = ""
    return raw


def build(root: Path, dest: Path) -> None:
    gui = root / "dist" / "MuseAuto.exe"
    cli = root / "dist" / "MuseAutoCLI.exe"
    if not gui.exists() or not cli.exists():
        raise SystemExit("先运行 PyInstaller 生成 dist/MuseAuto.exe 和 dist/MuseAutoCLI.exe")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for source in (gui, cli, root / "README.md", root / "USEDOC.md"):
        shutil.copy2(source, dest / source.name)

    (dest / "config").mkdir()
    (dest / "config" / "settings.json").write_text(
        json.dumps(_template_settings(root), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Every mailbox/invite file is a fresh template, not a copy of real data.
    (dest / "outlookMail.txt").write_text(
        "# Outlook Graph 邮箱池：一行一个\n"
        "# 格式：邮箱----密码----client_id----refresh_token\n"
        "# 将你的账号行粘贴到这里后运行；程序会按行消耗。\n",
        encoding="utf-8",
    )
    (dest / "registerEmail.txt.txt").write_text(
        "# 自选注册邮箱池：一行一个\n"
        "# 格式：邮箱----取验证码API\n",
        encoding="utf-8",
    )
    (dest / "inviteCode.txt").write_text(
        "# 邀请码池：一行一个，默认每个码使用 30 次\n"
        "# 格式：邀请码\n"
        "# 程序会回写：邀请码---用了N次\n",
        encoding="utf-8",
    )

    change_dir = dest / "changeEmailInfo"
    change_dir.mkdir()
    (change_dir / "changeEmail.txt").write_text(
        "# 步骤2 换绑邮箱池：一行一个邮箱\n",
        encoding="utf-8",
    )
    (change_dir / "changeEmailapi.txt").write_text(
        "# 步骤2 yich8 取码 API 模板，填写后再运行步骤2\n"
        "# 示例：http://mail.yich8.com/api/controller.php?...&username=旧邮箱&password=...\n",
        encoding="utf-8",
    )

    _write_blank_xls(dest / "muse账号.xls")
    for name in ("logs", "artifacts", "data"):
        (dest / name).mkdir()

    print(f"已生成干净便携包：{dest}")
    print("未复制：outlookMail.txt / changeEmailInfo / registerEmail.txt.txt / inviteCode.txt / muse账号.xls / logs / artifacts / data")
    print("下一步：填写 config/settings.json 和三个邮箱/邀请码文件后再运行")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--dest", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    dest = Path(args.dest).resolve() if args.dest else root / "dist" / "MuseAuto-Portable"
    build(root, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
