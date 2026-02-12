from pathlib import Path


def normalize_version_str(version_str: str) -> str | None:
    version = (version_str or "").replace("-", ".").replace("_", ".")
    if not version or version.startswith("0."):
        return None
    if len(version.split(".")) == 2:
        version = f"{version}.0"
    return version


def format_percent(current: int, total: int) -> str:
    return f"{(current / total * 100):.2f}%" if total > 0 else "0.00%"


def get_year_repositories_from_md(md_file: str | Path) -> dict[str, dict[str, dict[str, int]]]:
    md_path = Path(md_file)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    lines = md_path.read_text(encoding="utf-8").splitlines()
    result: dict[str, dict[str, dict[str, int]]] = {}
    current_language: str | None = None
    in_table = False
    header_found = False

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("## Summary"):
            break
        if line.startswith("## ") and not line.startswith("## Summary"):
            current_language = line[3:].strip()
            if current_language:
                result[current_language] = {}
                in_table = False
                header_found = False
            continue
        if line.startswith("|---") or line.startswith("|------"):
            if header_found and current_language:
                in_table = True
            continue
        if "| Year |" in line and "All Repos |" in line:
            header_found = True
            in_table = False
            continue
        if current_language and in_table and line.startswith("|") and "|" in line[1:]:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 3:
                continue
            try:
                year = parts[0]
                all_repos = int(parts[1].replace(",", ""))
                stars_10_plus = int(parts[2].replace(",", ""))
            except (ValueError, IndexError):
                continue
            result[current_language][year] = {
                "all": all_repos,
                "stars_10_plus": stars_10_plus,
            }

    return result

