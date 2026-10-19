def valid_png(data: bytes) -> bool:
    """Check screenshot chunks AND bounded decoded pixel scanlines (including Adam7)."""
    if not data.startswith(PNG_MAGIC):
        return False
    offset = 8
    header = None
    compressed = bytearray()
    palette = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            return False
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            return False
        if header is None:
            if kind != b"IHDR" or length != 13:
                return False
            header = struct.unpack(">IIBBBBB", payload)
            width, height, depth, color, compression, filtering, interlace = header
            allowed = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if (not 100 <= width <= 8192 or not 100 <= height <= 8192 or
                    depth not in allowed.get(color, set()) or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                return False
        elif kind == b"IHDR":
            return False
        if kind == b"PLTE":
            palette = 0 < length <= 768 and length % 3 == 0
        if kind == b"IDAT":
            compressed.extend(payload)
        if kind == b"IEND":
            if not header or not compressed or length != 0 or end != len(data):
                return False
            width, height, depth, color, _, _, interlace = header
            if color == 3 and not palette:
                return False
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            passes = [(0, 0, 1, 1)] if interlace == 0 else [
                (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
            rows = []
            for x, y, dx, dy in passes:
                pass_width = max(0, (width - x + dx - 1) // dx)
                pass_height = max(0, (height - y + dy - 1) // dy)
                if pass_width and pass_height:
                    rows.extend([1 + (pass_width * channels * depth + 7) // 8] * pass_height)
            expected = sum(rows)
            if expected > 128 * 1024 * 1024:
                return False
            try:
                decoder = zlib.decompressobj()
                pixels = decoder.decompress(compressed, expected + 1)
                if (len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
                    return False
            except zlib.error:
                return False
            position = 0
            for row_bytes in rows:
                if pixels[position] > 4:
                    return False
                position += row_bytes
            return True
        offset = end
    return False
