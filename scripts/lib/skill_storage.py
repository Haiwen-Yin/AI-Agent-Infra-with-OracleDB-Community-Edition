"""AI Agent Infra v3.5.0 - Skill Resource Storage Abstraction Layer"""

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from .connection import execute, execute_query_one

SKILL_RESOURCE_BASE_DIR = Path(__file__).parent.parent.parent / "data" / "skill_resources"


def _ensure_base_dir() -> Path:
    SKILL_RESOURCE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    return SKILL_RESOURCE_BASE_DIR


def _get_skill_dir(skill_id: str) -> Path:
    return _ensure_base_dir() / skill_id


def _compute_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _guess_mime_type(filename: str) -> str:
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


def save_resource(skill_id: str, filename: str, content: bytes) -> Dict[str, any]:
    skill_dir = _get_skill_dir(skill_id)
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    safe_filename = Path(filename).name
    file_path = skill_dir / safe_filename
    
    file_path.write_bytes(content)
    
    checksum = _compute_checksum(content)
    size = len(content)
    mime_type = _guess_mime_type(safe_filename)
    relative_uri = f"skill_resources/{skill_id}/{safe_filename}"
    
    execute(
        """UPDATE SKILL_META SET
              RESOURCE_URI = :vuri,
              RESOURCE_FILENAME = :vfilename,
              RESOURCE_SIZE = :vsize,
              RESOURCE_MIME_TYPE = :vmimetype,
              RESOURCE_CHECKSUM = :vchecksum
           WHERE ENTITY_ID = :veid AND ENTITY_TYPE = 'SKILL'""",
        {
            "vuri": relative_uri,
            "vfilename": safe_filename,
            "vsize": size,
            "vmimetype": mime_type,
            "vchecksum": checksum,
            "veid": skill_id,
        },
    )
    
    return {
        "path": str(file_path),
        "relative_uri": relative_uri,
        "filename": safe_filename,
        "size": size,
        "mime_type": mime_type,
        "checksum": checksum,
    }


def get_resource_path(skill_id: str) -> Optional[str]:
    row = execute_query_one(
        """SELECT RESOURCE_URI FROM SKILL_META 
           WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SKILL'""",
        {"eid": skill_id},
    )
    if row is None or not row.get("resource_uri"):
        return None
    
    relative_uri = row["resource_uri"]
    file_path = SKILL_RESOURCE_BASE_DIR.parent / relative_uri
    if file_path.exists():
        return str(file_path)
    return None


def get_resource_info(skill_id: str) -> Optional[Dict[str, any]]:
    row = execute_query_one(
        """SELECT RESOURCE_URI, RESOURCE_FILENAME, RESOURCE_SIZE, 
                  RESOURCE_MIME_TYPE, RESOURCE_CHECKSUM
           FROM SKILL_META 
           WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SKILL'""",
        {"eid": skill_id},
    )
    if row is None:
        return None
    
    result = {
        "resource_uri": row.get("resource_uri"),
        "filename": row.get("resource_filename"),
        "size": row.get("resource_size"),
        "mime_type": row.get("resource_mime_type"),
        "checksum": row.get("resource_checksum"),
    }
    
    if result["resource_uri"]:
        file_path = SKILL_RESOURCE_BASE_DIR.parent / result["resource_uri"]
        result["exists"] = file_path.exists()
    else:
        result["exists"] = False
    
    return result


def delete_resource(skill_id: str) -> bool:
    skill_dir = _get_skill_dir(skill_id)
    deleted = False
    
    if skill_dir.exists():
        for f in skill_dir.iterdir():
            f.unlink()
            deleted = True
        skill_dir.rmdir()
    
    execute(
        """UPDATE SKILL_META SET
              RESOURCE_URI = NULL,
              RESOURCE_FILENAME = NULL,
              RESOURCE_SIZE = NULL,
              RESOURCE_MIME_TYPE = NULL,
              RESOURCE_CHECKSUM = NULL
           WHERE ENTITY_ID = :veid AND ENTITY_TYPE = 'SKILL'""",
        {"veid": skill_id},
    )
    
    return deleted


def resource_exists(skill_id: str) -> bool:
    return get_resource_path(skill_id) is not None


def read_resource_content(skill_id: str) -> Optional[bytes]:
    skill_dir = _get_skill_dir(skill_id)
    if not skill_dir.exists():
        p = get_resource_path(skill_id)
        if p:
            return Path(p).read_bytes()
        return None
    
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    return buf.getvalue()


def _get_server_host() -> str:
    import socket
    try:
        hostname = socket.gethostname()
        try:
            ip = socket.gethostbyname(hostname)
        except Exception:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        return f"{hostname} ({ip})"
    except Exception:
        return "unknown"


def save_resource_files(skill_id: str, files: Dict[str, bytes]) -> Dict[str, Any]:
    skill_dir = _get_skill_dir(skill_id)
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    total_size = 0
    file_count = 0
    for rel_path, content in files.items():
        safe_path = Path(rel_path)
        parts = safe_path.parts
        if parts and parts[0].startswith("."):
            continue
        target = skill_dir / safe_path.name
        target_parent = target.parent
        target_parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        total_size += len(content)
        file_count += 1
    
    checksum = hashlib.sha256(str(sorted(files.keys())).encode()).hexdigest()
    relative_uri = f"skill_resources/{skill_id}/"
    server_host = _get_server_host()
    
    execute(
        """UPDATE SKILL_META SET
              RESOURCE_URI = :vuri,
              RESOURCE_FILENAME = :vfilename,
              RESOURCE_SIZE = :vsize,
              RESOURCE_MIME_TYPE = :vmimetype,
              RESOURCE_CHECKSUM = :vchecksum,
              RESOURCE_SERVER_HOST = :vserverhost
           WHERE ENTITY_ID = :veid AND ENTITY_TYPE = 'SKILL'""",
        {
            "vuri": relative_uri,
            "vfilename": f"{file_count} files",
            "vsize": total_size,
            "vmimetype": "application/zip+extracted",
            "vchecksum": checksum,
            "vserverhost": server_host,
            "veid": skill_id,
        },
    )
    
    return {
        "path": str(skill_dir),
        "relative_uri": relative_uri,
        "file_count": file_count,
        "total_size": total_size,
    }
