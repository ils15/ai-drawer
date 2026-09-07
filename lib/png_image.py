"""Crop/composite Fusion's non-interlaced 8-bit RGB/RGBA PNGs using stdlib.

This intentionally handles the PNG format Fusion exports, not arbitrary image
formats. Decode allocation is bounded and unsupported formats fail explicitly.
"""

import struct
import zlib

MAX_PIXELS = 16_777_216
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def transform(png, crop=None, background=None):
    """Return a PNG cropped in rendered pixels, optionally over an RGB tuple."""
    if not png.startswith(SIGNATURE):
        raise ValueError("Capture did not produce a PNG")
    position, header, compressed = 8, None, bytearray()
    color_chunks = bytearray()
    while position < len(png):
        if position + 12 > len(png):
            raise ValueError("Truncated PNG chunk")
        size = struct.unpack_from(">I", png, position)[0]
        kind = png[position + 4:position + 8]
        end = position + 8 + size
        if end + 4 > len(png):
            raise ValueError("Truncated PNG data")
        data = png[position + 8:end]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != struct.unpack_from(">I", png, end)[0]:
            raise ValueError("Invalid PNG checksum")
        if kind == b"IHDR":
            if header is not None or position != 8 or size != 13:
                raise ValueError("Invalid PNG header")
            header = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            break
        elif kind in (b"sRGB", b"gAMA", b"cHRM", b"iCCP"):
            # Cropping does not change the pixel color space. Keep the export's
            # profile so viewers interpret the resulting colors consistently.
            color_chunks.extend(png[position:end + 4])
        elif kind in (b"PLTE", b"tRNS") or not kind[0] & 32:
            raise ValueError("Unsupported PNG chunk")
        position = end + 4
    else:
        raise ValueError("PNG has no end marker")
    if header is None:
        raise ValueError("PNG has no header")
    width, height, depth, color, compression, filtering, interlace = header
    if depth != 8 or color not in (2, 6) or compression or filtering or interlace:
        raise ValueError("Expected Fusion's non-interlaced 8-bit RGB/RGBA PNG")
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise ValueError("PNG exceeds the image size limit")
    channels = 4 if color == 6 else 3
    stride = width * channels
    limit = (stride + 1) * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, limit + 1)
    if len(raw) != limit or not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid PNG pixel data size")
    x, y, out_width, out_height = (0, 0, width, height) if crop is None else crop
    if (any(type(v) is not int for v in (x, y, out_width, out_height))
            or min(x, y) < 0 or min(out_width, out_height) < 1
            or x + out_width > width or y + out_height > height):
        raise ValueError("Crop must fit inside the rendered image")
    if background is not None and (
        len(background) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in background)
    ):
        raise ValueError("Background must contain three RGB bytes")
    output = bytearray()
    previous = bytearray(stride)
    for row_index in range(height):
        offset = row_index * (stride + 1)
        filter_type = raw[offset]
        row = bytearray(raw[offset + 1:offset + 1 + stride])
        if filter_type > 4:
            raise ValueError("Unsupported PNG row filter")
        if filter_type:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                above = previous[i]
                upper_left = previous[i - channels] if i >= channels else 0
                prediction = (left if filter_type == 1 else above if filter_type == 2
                              else (left + above) // 2 if filter_type == 3
                              else _paeth(left, above, upper_left))
                row[i] = (row[i] + prediction) & 255
        previous = row
        if y <= row_index < y + out_height:
            cropped = row[x * channels:(x + out_width) * channels]
            if background is not None and channels == 4:
                for i in range(0, len(cropped), 4):
                    alpha = cropped[i + 3]
                    for component in range(3):
                        cropped[i + component] = (
                            cropped[i + component] * alpha + background[component] * (255 - alpha) + 127
                        ) // 255
                    cropped[i + 3] = 255
            output.append(0)  # Emit unfiltered rows; zlib still compresses them.
            output.extend(cropped)
    header = struct.pack(">IIBBBBB", out_width, out_height, 8, color, 0, 0, 0)
    return (SIGNATURE + _chunk(b"IHDR", header) + color_chunks
            + _chunk(b"IDAT", zlib.compress(output)) + _chunk(b"IEND", b""))
