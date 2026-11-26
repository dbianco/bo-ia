"""Writes generated issues as small two-column PDF files, to test extraction
end to end. Only what that needs: one font, one size, text in content order."""
from __future__ import annotations

from collections.abc import Sequence

COLUMN_LINES = 60
COLUMNS = (40, 310)


def _literal(text: str) -> bytes:
    encoded = text.encode("cp1252")
    return b"(" + encoded.replace(b"\\", rb"\\").replace(b"(", rb"\(").replace(b")", rb"\)") + b")"


def write_pdf(pages: Sequence[str]) -> bytes:
    objects: list[bytes] = []
    font = 3
    kids = [font + 1 + 2 * i for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for kid, page in zip(kids, pages, strict=True):
        operations = []
        for position, line in enumerate(page.split("\n")):
            column, row = divmod(position, COLUMN_LINES)
            # A page with more lines than fit keeps going below: extraction does not mind.
            x = COLUMNS[min(column, len(COLUMNS) - 1)]
            y = 800 - 12 * (row if column < len(COLUMNS) else position - COLUMN_LINES)
            operations.append(b"BT /F1 6 Tf %d %d Td %s Tj ET" % (x, y, _literal(line)))
        stream = b"\n".join(operations)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font} 0 R >> >> "
            f"/Contents {kid + 1} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, start)
    return bytes(out)
