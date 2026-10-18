"""Выборочное чтение SoundResource и поиск точных ссылок на DAT; только локально."""
import ctypes
import hashlib
import json
import struct
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT.parent
ZSTD = Path(r'C:\Program Files\Git\mingw64\bin\libzstd.dll')


def table(data, field, stride):
    relative, count = struct.unpack_from('<II', data, field)
    start = field + relative
    if start + count * stride > len(data):
        raise ValueError('Таблица выходит за границы индекса')
    return [data[start+i*stride:start+(i+1)*stride] for i in range(count)]


class Reader:
    def __init__(self):
        self.index = (ROOT / 'enshrouded.kfc').read_bytes()
        if self.index[:4] != b'KFC4':
            raise ValueError('Ожидался KFC4')
        self.keys = table(self.index, 96, 32)
        self.values = [struct.unpack('<II', x) for x in table(self.index, 104, 8)]
        self.chunks = [struct.unpack('<IIIII', x) for x in table(self.index, 136, 20)]
        self.contents = dict(zip(table(self.index, 72, 16), table(self.index, 80, 16)))
        self.z = ctypes.CDLL(str(ZSTD))
        self.z.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        self.z.ZSTD_decompress.restype = ctypes.c_size_t
        self.cache = {}

    def resource(self, index):
        offset, packed_size = self.values[index]
        size = packed_size & 0xffffff
        if size > 1024 * 1024:
            raise ValueError('Лимит отдельного дескриптора 1 МиБ')
        result = bytearray()
        end = offset + size
        for ci, (co, storage_size, compressed_size, uo, us) in enumerate(self.chunks):
            if offset < uo+us and end > uo:
                if us > 32*1024*1024 or compressed_size > storage_size:
                    raise ValueError('Некорректный размер блока')
                if ci not in self.cache:
                    with (ROOT / 'enshrouded.kfc_resources').open('rb') as f:
                        f.seek(co)
                        source = f.read(compressed_size)
                    if len(source) != compressed_size:
                        raise ValueError('Неполный сжатый блок')
                    destination = ctypes.create_string_buffer(us)
                    actual = self.z.ZSTD_decompress(destination, us, source, len(source))
                    if actual != us:
                        raise ValueError(f'Ошибка декомпрессии: {actual}')
                    if len(self.cache) >= 4:
                        self.cache.pop(next(iter(self.cache)))
                    self.cache[ci] = destination.raw
                result.extend(self.cache[ci][max(offset,uo)-uo:min(end,uo+us)-uo])
        if len(result) != size:
            raise ValueError('Не удалось полностью прочитать ресурс')
        return bytes(result)

    def sound(self, i):
        b = self.resource(i)
        # Предварительно наблюдаемая структура. Поля сверяются по границам,
        # а 16-байтная ссылка — по точному совпадению с ключом индекса.
        if len(b) < 64:
            return None
        relative, length = struct.unpack_from('<II', b, 56)
        start = 56 + relative
        if start + length > len(b):
            return None
        name = b[start:start+length].decode('utf-8', errors='replace')
        links = []
        for pos in range(0, len(b)-15, 4):
            h = b[pos:pos+16]
            if h in self.contents:
                offset, flags, container, padding = struct.unpack('<IHHQ', self.contents[h])
                links.append(dict(field_offset=pos, hash=h.hex(), container=container,
                                  offset=offset, size=struct.unpack_from('<I', h)[0]))
        return dict(index=i, resource_id_hex=self.keys[i].hex(), name=name,
                    descriptor_size=len(b), links=links, header_hex=b[:64].hex())


def main():
    reader = Reader()
    sounds = [i for i, k in enumerate(reader.keys) if struct.unpack_from('<I', k, 16)[0] == 0xdf74e485]
    # Сначала короткие дескрипторы: избегаем встроенных больших массивов.
    records = []
    for i in sorted(sounds, key=lambda i: reader.values[i][0]):
        if reader.values[i][1] & 0xffffff <= 512:
            record = reader.sound(i)
            if record:
                records.append(record)
    output = PROJECT / 'local' / 'sound-catalog-001.json'
    with output.open('x', encoding='utf-8') as f:
        json.dump(dict(kfc_sha256=hashlib.sha256(reader.index).hexdigest(),
                       sound_type_hash='df74e485', total_sounds=len(sounds),
                       short_descriptors=records), f, ensure_ascii=False, indent=2)
    print(json.dumps(dict(total_sounds=len(sounds), short_descriptors=len(records),
                          linked=sum(bool(r['links']) for r in records)), ensure_ascii=False))
    candidates = [r for r in records if r['name'].lower().startswith('en') and
                  any(t in r['name'].lower() for t in ['lore', 'book', 'note', 'letter', 'scroll'])]
    for r in candidates[:30]:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
