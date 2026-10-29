"""確認済みの配布対象だけをZIP化。個人の実行ログは収録しない。"""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


FILES = [
    "README.md",
    "requirements.txt",
    ".python-version",
    "pyproject.toml",
    "uv.lock",
    ".env.lmstudio.example",
    ".env.openrouter.example",
    "start-gui.cmd",
    *[
        "src/" + name
        for name in [
            "agent.py",
            "steps.py",
            "configs.py",
            "models.py",
            "llm.py",
            "prompts.py",
            "custom_logger.py",
            "security.py",
        ]
    ],
    *[
        "workshop/" + name
        for name in [
            "__init__.py",
            "__main__.py",
            "checks.py",
            "embeddings.py",
            "gui.py",
            "package.py",
            "runner_lock.py",
            "run_log.py",
            "search.py",
            "service.py",
            "test_embeddings.py",
            "test_gui.py",
            "test_workshop.py",
            "test_security.py",
            "README.md",
            "CODE_GUIDE.md",
            "INSTALL_WINDOWS.md",
            "QUESTIONS.md",
            "SOURCE.md",
            "STATUS.md",
            "SECURITY_AUDIT.md",
            "requirements.txt",
            "requirements.lock.txt",
            "corpus-manifest.json",
        ]
    ],
    "data/XYZ_system_QA.csv",
    "data/XYZシステムリリースノート.pdf",
    "data/XYZシステム統合ユーザーマニュアル.pdf",
    "workshop/examples/security-audit.json",
    "workshop/examples/secure-lmstudio-run.json",
    "workshop/examples/secure-lmstudio-run.log",
    "workshop/examples/openrouter-success.json",
    "workshop/examples/openrouter-success.log",
    "workshop/examples/release-verification.json",
]


def package():
    payload = {}
    for name in FILES:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("配布ファイルの参照先が不正です")
        data = path.read_bytes()
        if path.suffix != ".pdf" and re.search(rb"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{20,}", data):
            raise ValueError("配布物にAPIキー形式の値が含まれています: " + name)
        payload["chapter4/" + name] = data
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    payload["chapter4/RELEASE_MANIFEST.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    target = ROOT / "dist" / "helpdesk-workshop-secure-20261029.zip"
    target.parent.mkdir(exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(suffix=".zip", dir=target.parent)
    os.close(descriptor)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for name, data in sorted(payload.items()):
                archive.writestr(name, data)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n", encoding="ascii")
    # 既存の案内から辿った場合も対策版を受け取る。
    alias = target.parent / "helpdesk-workshop.zip"
    alias.write_bytes(target.read_bytes())
    alias.with_suffix(".zip.sha256").write_text(digest + "  " + alias.name + "\n", encoding="ascii")
    print(f"{target} ({target.stat().st_size:,} bytes)")
    return target


if __name__ == "__main__":
    package()
