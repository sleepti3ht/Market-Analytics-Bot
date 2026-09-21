# gather_review_context.py
"""Собирает код проекта в 4 небольших markdown-файла,
чтобы вложения не обрезались при загрузке в чат."""
import re
from pathlib import Path

ROOT = Path(__file__).parent

PARTS = {
    "REVIEW_part1_core.md": [
        "main.py", "config.py", "shared_state.py", "start_dashboard.py",
    ],
    "REVIEW_part2_api_analyzer.md": [
        "api/lis_skins_ws.py", "api/market_csgo.py", "analyzer/metrics.py",
    ],
    "REVIEW_part3_storage_notifications.md": [
        "storage/db.py", "notifications/telegram_bot.py", "notifications/telegram_app.py",
    ],
    "REVIEW_part4_dashboard_meta.md": [
        "dashboard/app.py", "requirements.txt", ".gitignore",
    ],
}

SECRET_PATTERNS = [
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),  # telegram token
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
]


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def main() -> None:
    all_included = []
    for out_name, rel_paths in PARTS.items():
        blocks = [f"# {out_name}", ""]
        for rel in rel_paths:
            p = ROOT / rel
            if not p.exists():
                blocks.append(f"---\n## {rel}\n**FILE NOT FOUND**")
                continue
            all_included.append(p)
            fence = "python" if p.suffix == ".py" else "text"
            blocks.append(f"---\n## {rel}\n```{fence}")
            blocks.append(read_text(p).rstrip())
            blocks.append("```")
        out = ROOT / out_name
        out.write_text("\n".join(blocks), encoding="utf-8")
        print(f"[OK] {out_name}: {out.stat().st_size / 1024:.1f} KB")

    warns = []
    for p in all_included:
        text = read_text(p)
        if any(pat.search(text) for pat in SECRET_PATTERNS):
            warns.append(str(p.relative_to(ROOT)))
    if warns:
        print(f"[STOP] Похоже на секреты в: {warns} — проверь перед отправкой")
    else:
        print("[OK] Секретоподобных строк нет. Можно отправлять.")
    print("\nКидай мне part1..part4 по очереди (или все четыре вложениями в одно сообщение).")


if __name__ == "__main__":
    main()