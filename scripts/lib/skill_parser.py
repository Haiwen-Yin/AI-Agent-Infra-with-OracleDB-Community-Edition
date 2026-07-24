"""AI Agent Infra v4.1.0 - Skill Package Parser

Parse skill packages (zip archives containing SKILL.md) and extract metadata + files.
Supports three metadata sources by priority:
1. _meta.json (ClawHub standard: slug + version)
2. SKILL.md YAML frontmatter (name + description)
3. SKILL.md ## Metadata section (existing format)
"""

import io
import hashlib
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath
from typing import Any, Dict, Tuple

MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_FILE_COUNT = 256
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


def _parse_yaml_frontmatter(content: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not content.startswith("---"):
        return result
    end = content.find("---", 3)
    if end == -1:
        return result
    fm = content[3:end].strip()
    for line in fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(\w+)\s*:\s*(.+)", line)
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip().strip('"').strip("'")
            result[key] = val
    return result


def _parse_meta_json(raw: bytes) -> Dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    result: Dict[str, Any] = {}
    if "slug" in data:
        result["skill_name"] = data["slug"]
    if "version" in data:
        result["skill_version"] = str(data["version"])
    if "publishedAt" in data:
        import time
        result["published_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(data["publishedAt"] / 1000))
    return result


def parse_skill_md(content: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "title": "",
        "skill_name": "",
        "skill_version": "1.0.0",
        "skill_type": "CUSTOM",
        "skill_format": "TEXT",
        "runtime": "PYTHON",
        "text_content": content,
        "skill_description": "",
        "parameters": None,
        "dependencies": None,
        "category": None,
        "owned_by_agent": None,
        "visibility": "SHARED",
    }

    fm = _parse_yaml_frontmatter(content)
    if "name" in fm:
        meta["skill_name"] = fm["name"]
        if not meta["title"]:
            meta["title"] = fm["name"]
    if "description" in fm:
        meta["skill_description"] = fm["description"]
    if "runtime" in fm:
        meta["runtime"] = fm["runtime"].upper()
    if "format" in fm:
        meta["skill_format"] = fm["format"].upper()

    yaml_end = 0
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            yaml_end = end + 3

    body = content[yaml_end:].lstrip("\n")

    current_section = None
    text_lines: list[str] = []

    for line in body.splitlines():
        stripped = line.strip()

        if stripped.startswith("# ") and not meta["title"]:
            meta["title"] = stripped[2:].strip()
            continue

        if stripped.startswith("## "):
            section_name = stripped[3:].strip().lower()
            if section_name in ("metadata", "元数据"):
                current_section = "metadata"
                continue
            elif section_name in ("content", "文本内容", "description"):
                current_section = "content"
                continue
            else:
                current_section = "other"
                continue

        if current_section == "metadata":
            m = re.match(r"[-*]\s+\*\*([^*]+)\*\*\s*[:：]\s*(.+)", stripped)
            if m:
                key = m.group(1).strip().lower().replace(" ", "_")
                val = m.group(2).strip()
                key_map = {
                    "name": "skill_name",
                    "skill_name": "skill_name",
                    "技能名称": "skill_name",
                    "version": "skill_version",
                    "skill_version": "skill_version",
                    "版本": "skill_version",
                    "type": "skill_type",
                    "skill_type": "skill_type",
                    "类型": "skill_type",
                    "format": "skill_format",
                    "skill_format": "skill_format",
                    "格式": "skill_format",
                    "runtime": "runtime",
                    "运行时": "runtime",
                    "category": "category",
                    "分类": "category",
                    "visibility": "visibility",
                    "可见性": "visibility",
                    "parameters": "parameters",
                    "参数": "parameters",
                    "dependencies": "dependencies",
                    "依赖": "dependencies",
                }
                mapped = key_map.get(key)
                if mapped:
                    if mapped in ("parameters", "dependencies"):
                        try:
                            meta[mapped] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            meta[mapped] = val
                    else:
                        meta[mapped] = val
            continue

        if current_section == "content":
            text_lines.append(line)

    if not meta["skill_name"]:
        name_from_title = meta["title"].lower().replace(" ", "_")
        meta["skill_name"] = re.sub(r"[^a-z0-9_]", "", name_from_title) or "unnamed_skill"

    return meta


def parse_skill_package(zip_bytes: bytes) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    if len(zip_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("Skill archive exceeds compressed size limit")
    bio = io.BytesIO(zip_bytes)
    if not zipfile.is_zipfile(bio):
        raise ValueError("Not a valid ZIP archive")

    bio.seek(0)
    with zipfile.ZipFile(bio, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILE_COUNT:
            raise ValueError("Skill archive contains too many entries")

        normalized: Dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            name = info.filename
            if "\\" in name or name.startswith("/"):
                raise ValueError(f"Unsafe archive path: {name}")
            path = PurePosixPath(name)
            if any(part in ("", ".", "..") for part in path.parts):
                raise ValueError(f"Unsafe archive path: {name}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symbolic links are not allowed: {name}")
            normalized_name = path.as_posix().rstrip("/")
            if normalized_name in normalized:
                raise ValueError(f"Duplicate archive path: {normalized_name}")
            normalized[normalized_name] = info
            if not info.is_dir():
                if info.file_size > MAX_FILE_BYTES:
                    raise ValueError(f"Skill file exceeds size limit: {name}")
                if info.compress_size == 0 and info.file_size > 0:
                    raise ValueError(f"Invalid compressed size for: {name}")
                if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    raise ValueError(f"Suspicious compression ratio for: {name}")
                total_size += info.file_size
        if total_size > MAX_TOTAL_BYTES:
            raise ValueError("Skill archive exceeds uncompressed size limit")

        skill_candidates = [name for name in normalized if PurePosixPath(name).name == "SKILL.md"]
        if len(skill_candidates) != 1:
            raise ValueError("Archive must contain exactly one SKILL.md file")
        skill_md_name = skill_candidates[0]
        package_root = PurePosixPath(skill_md_name).parent
        meta_json_name = (package_root / "_meta.json").as_posix()
        if meta_json_name not in normalized:
            meta_json_name = None

        try:
            skill_md_content = zf.read(normalized[skill_md_name]).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SKILL.md must be UTF-8") from exc
        meta = parse_skill_md(skill_md_content)

        if meta_json_name is not None:
            meta_json_data = _parse_meta_json(zf.read(normalized[meta_json_name]))
            if "skill_name" in meta_json_data:
                meta["skill_name"] = meta_json_data["skill_name"]
            if "skill_version" in meta_json_data:
                meta["skill_version"] = meta_json_data["skill_version"]
            if "published_at" in meta_json_data:
                meta["published_at"] = meta_json_data["published_at"]

        has_script = False
        resource_files: Dict[str, bytes] = {}
        package_hash = hashlib.sha256()
        for name, info in sorted(normalized.items()):
            if info.is_dir():
                continue
            path = PurePosixPath(name)
            try:
                relative = path.relative_to(package_root).as_posix()
            except ValueError as exc:
                raise ValueError(f"Archive entry is outside the Skill root: {name}") from exc
            data = zf.read(info)
            resource_files[relative] = data
            package_hash.update(relative.encode("utf-8") + b"\0")
            package_hash.update(hashlib.sha256(data).digest())
            ext = PurePosixPath(relative).suffix.lower()
            if ext in (".py", ".sh", ".bash", ".js", ".ts", ".rb", ".go"):
                has_script = True

        meta["package_checksum"] = package_hash.hexdigest()
        meta["file_hashes"] = {
            path: hashlib.sha256(data).hexdigest()
            for path, data in resource_files.items()
        }

        if has_script and meta["skill_format"] == "TEXT":
            meta["skill_format"] = "SCRIPT" if not meta["text_content"] else "HYBRID"

    return meta, resource_files
