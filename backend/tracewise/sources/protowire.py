"""Just enough protobuf decoding for Loki's push format, without generated code."""

import struct


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def fields(buf: bytes):
    """Yield (field number, wire type, value) for each field in a message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            val, i = _varint(buf, i)
        elif wt == 1:
            val, i = buf[i:i + 8], i + 8
        elif wt == 2:
            n, i = _varint(buf, i)
            val, i = buf[i:i + n], i + n
        elif wt == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        yield num, wt, val


def double(raw: bytes) -> float:
    return struct.unpack("<d", raw)[0]


def loki_push(buf: bytes) -> list[dict]:
    """logproto.PushRequest -> [{"labels": '{a="b"}', "entries": [(ns, line, {meta})]}]."""
    streams = []
    for num, _, stream in fields(buf):
        if num != 1:
            continue
        labels, entries = "", []
        for snum, _, sval in fields(stream):
            if snum == 1:
                labels = sval.decode("utf-8", "replace")
            elif snum == 2:
                ns, line, meta = 0, "", {}
                for enum, _, evalue in fields(sval):
                    if enum == 1:
                        secs = nanos = 0
                        for tnum, _, tval in fields(evalue):
                            secs, nanos = (tval, nanos) if tnum == 1 else (secs, tval)
                        ns = secs * 1_000_000_000 + nanos
                    elif enum == 2:
                        line = evalue.decode("utf-8", "replace")
                    elif enum == 3:
                        pair = dict((n, v.decode("utf-8", "replace")) for n, _, v in fields(evalue))
                        if 1 in pair:
                            meta[pair[1]] = pair.get(2, "")
                entries.append((ns, line, meta))
        streams.append({"labels": labels, "entries": entries})
    return streams
