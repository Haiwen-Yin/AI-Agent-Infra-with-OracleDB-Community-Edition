"""Resource-bounded image/document parser, invoked as a private child process."""
import base64
import io
import json
from pathlib import Path
import resource
import sys
import sysconfig
import tempfile
import warnings
import zipfile

# The parser is launched with ``python -I`` so caller-controlled PYTHONPATH
# and user site directories cannot influence document handling.  ``-I`` also
# omits the interpreter's own installed site-packages on some system Python
# builds, however; add only the interpreter-owned paths reported by
# ``sysconfig`` so the verified Pillow/pypdf wheels remain available without
# re-enabling arbitrary import locations.
for _site_path in (sysconfig.get_paths().get("purelib"), sysconfig.get_paths().get("platlib")):
    if _site_path and _site_path not in sys.path:
        sys.path.append(_site_path)
# Generated packages carry their approved offline dependencies in a sibling
# ``vendor`` directory.  ``python -I`` intentionally ignores PYTHONPATH, so
# resolve that one package-owned directory explicitly; no caller-controlled
# import path is reintroduced.
_package_root = Path(__file__).resolve().parents[2]
_vendor_path = _package_root / "vendor"
if _vendor_path.is_dir() and str(_vendor_path) not in sys.path:
    sys.path.append(str(_vendor_path))
# ``zipimport`` does not search a directory for wheel archives.  The release
# package intentionally keeps its offline dependencies as wheels, so add the
# approved archives themselves to the isolated interpreter path.  This keeps
# ``python -I`` hermetic while making the bundled Pillow path work just like
# the pypdf path in the managed-input parser.
if _vendor_path.is_dir():
    for _wheel in sorted(_vendor_path.glob("*.whl")):
        _wheel_value = str(_wheel)
        if _wheel_value not in sys.path:
            sys.path.append(_wheel_value)
        # Pillow contains a native ``_imaging`` extension.  zipimport can
        # serve its Python modules from a wheel but cannot load that shared
        # object directly from the archive, so unpack only the approved
        # Pillow wheel into a private temporary directory.  Validate every
        # member before extraction to keep the isolated parser path bounded
        # even if a package is moved between hosts.
        if _wheel.name.startswith("pillow-"):
            _unpack_root = Path(tempfile.mkdtemp(prefix="cx-managed-pillow-"))
            _root_resolved = _unpack_root.resolve()
            with zipfile.ZipFile(_wheel) as _archive:
                for _member in _archive.infolist():
                    _candidate = (_unpack_root / _member.filename).resolve()
                    if not _candidate.is_relative_to(_root_resolved):
                        raise RuntimeError("Bundled Pillow wheel contains an invalid path")
                _archive.extractall(_unpack_root)
            sys.path.insert(0, str(_unpack_root))
            break


def parse(media_type, data):
    if not 1 <= len(data) <= 4194304:
        raise ValueError("Managed input must be between 1 byte and 4 MiB")
    if media_type in {"image/png", "image/jpeg"}:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 4000000
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"} or image.width * image.height > 4000000 or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Unsupported or oversized image")
                image.load()
                normalized = image.convert("RGB")
                output = io.BytesIO()
                normalized.save(output, format="PNG")
                blob = output.getvalue()
                if len(blob) > 4194304:
                    raise ValueError("Normalized image exceeds 4 MiB")
                return {"media_type": "image/png", "content": base64.b64encode(blob).decode(), "extracted": None,
                        "width": image.width, "height": image.height, "metadata_removed": True}
    if media_type in {"text/plain", "text/markdown"}:
        text = data.decode("utf-8-sig")
        if "\x00" in text or len(text.encode()) > 65536:
            raise ValueError("Text document exceeds its bounded extraction limit")
    elif media_type == "application/pdf":
        from pypdf import PdfReader
        if not data.startswith(b"%PDF-") or any(marker in data for marker in (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/OpenAction", b"/XFA")):
            raise ValueError("Active or embedded PDF content is not supported")
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 30:
            raise ValueError("Encrypted PDFs and documents over 30 pages are not supported")
        from pypdf.generic import IndirectObject, DictionaryObject, ArrayObject
        active = frozenset({"/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/EmbeddedFiles", "/RichMedia", "/OpenAction", "/AA", "/XFA", "/SubmitForm", "/ImportData"})
        seen = set()
        def inspect(item, depth=0):
            if depth > 40 or len(seen) > 10000:
                raise ValueError("PDF object graph exceeds parser limits")
            if isinstance(item, IndirectObject):
                identity = (item.idnum, item.generation)
                if identity in seen:
                    return
                seen.add(identity)
                return inspect(item.get_object(), depth + 1)
            if isinstance(item, DictionaryObject):
                if any(str(key) in active for key in item) or str(item.get("/S", "")) in active:
                    raise ValueError("Active PDF objects are not supported")
                for nested in item.values():
                    inspect(nested, depth + 1)
            elif isinstance(item, ArrayObject):
                for nested in item:
                    inspect(nested, depth + 1)
        inspect(reader.trailer)
        pieces, total = [], 0
        for page in reader.pages:
            piece = page.extract_text() or ""
            total += len(piece.encode())
            if total > 65536:
                raise ValueError("PDF extraction exceeds 64 KiB")
            pieces.append(piece)
        text = "\n".join(pieces)
        if len(text.encode()) > 65536:
            raise ValueError("PDF extraction exceeds 64 KiB")
        if not text.strip():
            raise ValueError("The PDF has no extractable text; OCR is not available")
    else:
        raise ValueError("Supported inputs are PNG, JPEG, UTF-8 text/Markdown and text PDFs")
    return {"media_type": media_type, "content": base64.b64encode(data).decode(), "extracted": text}


def main():
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        request = json.loads(sys.stdin.buffer.read(6000000))
        result = parse(request["media_type"], base64.b64decode(request["content"], validate=True))
        print(json.dumps({"ok": True, "result": result}))
    except Exception:
        # Parser errors may contain document strings. Only a bounded local
        # category crosses the child-process boundary.
        print(json.dumps({"ok": False, "error_code": "INVALID_MANAGED_INPUT"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
