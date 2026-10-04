"""The words in a PDF made by reportlab, without a PDF reader: its page streams are Flate (and ASCII85) coded text-drawing commands."""

import base64
import re
import zlib


def pdf_text(pdf: bytes) -> str:
    out: list[str] = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        data = stream.strip()
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data[:-2])
            data = zlib.decompress(data)
        except (ValueError, zlib.error):
            pass
        out += [m.replace(rb"\(", b"(").replace(rb"\)", b")").decode("latin-1") for m in re.findall(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj", data)]
    return "\n".join(out)
