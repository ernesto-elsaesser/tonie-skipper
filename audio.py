import io
import struct
import hashlib
import protobuf_header


OGG_MAGIC = b"OggS"
PAGE_HEADER_FORMAT = "<BBQLLLB"
SAMPLE_RATE_KHZ = 48
FRAME_DURATIONS = {c: [2.5, 5, 10, 20][c % 4] * SAMPLE_RATE_KHZ
                   for c in range(16, 32)}


crc_table = []
for i in range(256):
    k = i << 24
    for _ in range(8):
        k = (k << 1) ^ 0x04c11db7 if k & 0x80000000 else k << 1
    crc_table.append(k & 0xffffffff)


def crc32(bytestream):
    crc = 0
    for byte in bytestream:
        lookup_index = ((crc >> 24) ^ byte) & 0xff
        crc = ((crc & 0xffffff) << 8) ^ crc_table[lookup_index]
    return crc


class OggPage:

    def __init__(self, header: bytes):

        self.header = header
        self.header_fields = struct.unpack(PAGE_HEADER_FORMAT, header)
        self.body = b""
        self.duration = 0

    def raw(self) -> bytes:
        return self.serialize(self.header)
    
    def adjusted(self, granule_position: int, page_num: int):
        mod_fields = list(self.header_fields)
        mod_fields[2] = granule_position
        mod_fields[4] = page_num
        mod_fields[5] = 0  # zero checksum
        pre_header = struct.pack(PAGE_HEADER_FORMAT, *mod_fields)
        checksum = crc32(OGG_MAGIC + pre_header + self.body)
        mod_fields[5] = checksum
        mod_header = struct.pack(PAGE_HEADER_FORMAT, *mod_fields)
        return self.serialize(mod_header)
    
    def serialize(self, header: bytes):
        return OGG_MAGIC + header + self.body


class TonieHeader:

    def __init__(self, header: bytes):

        self.protobuf = protobuf_header.TonieHeader.FromString(header)  # type: ignore
        self.timestamp: int = self.protobuf.timestamp
        self.chapter_start_pages: list[int] = list(self.protobuf.chapterPages)


class TonieAudio:

    def __init__(self, header: TonieHeader, pages: list[OggPage]):

        self.header = header
        self.pages = pages

    def get_chapter_page_nums(self, chapter_num: int) -> list[int]:

        index = self.header.chapter_start_pages
        start_num = index[chapter_num]
        if chapter_num + 1 < len(index):
            end_num = index[chapter_num + 1]
        else:
            end_num = len(self.pages)
        return list(range(start_num, end_num))


def parse_tonie(in_file: io.BufferedReader) -> TonieAudio:

    tonie_header = parse_tonie_header(in_file)
    pages = parse_ogg(in_file)
    return TonieAudio(tonie_header, pages)


def parse_tonie_header(in_file: io.BufferedReader) -> TonieHeader:

    header_size = struct.unpack(">L", in_file.read(4))[0]
    header_data = in_file.read(header_size)
    return TonieHeader(header_data)


def parse_ogg(in_file: io.BufferedReader) -> list[OggPage]:

    # https://datatracker.ietf.org/doc/html/rfc3533#section-6

    pages: list[OggPage] = []

    while True:

        magic = in_file.read(4)
        if len(magic) == 0:
            break
        assert magic == OGG_MAGIC

        header = in_file.read(23)
        page = OggPage(header)
        page_num: int = page.header_fields[4]
        assert page_num == len(pages)
        packet_count: int = page.header_fields[6]
        packet_table = in_file.read(packet_count)
        page.body += packet_table
        continued = False
        for length in packet_table:
            packet = in_file.read(length)
            page.body += packet

            if page_num > 1 and not continued:
                info = struct.unpack("<B", packet[0:1])[0]
                config_value = info >> 3
                framepacking = info & 3
                if framepacking == 0:
                    frame_count = 1
                elif framepacking == 1:
                    frame_count = 2
                elif framepacking == 2:
                    frame_count = 2
                elif framepacking == 3:
                    frame_count = struct.unpack("<B", packet[1:2])[0] & 63
                else:
                    raise ValueError
                page.duration += FRAME_DURATIONS[config_value] * frame_count

            continued = length == 255

        pages.append(page)

    return pages


def export_chapter(tonie_audio: TonieAudio, chapter_num: int, out_file: io.BufferedWriter):

    next_page_num = 0
    if chapter_num > 0:
        out_file.write(tonie_audio.pages[0].raw())
        out_file.write(tonie_audio.pages[1].raw())
        next_page_num = 2

    granule_position = 0
    for page_num in tonie_audio.get_chapter_page_nums(chapter_num):
        page = tonie_audio.pages[page_num]
        granule_position += page.duration
        out_file.write(page.adjusted(granule_position, next_page_num))
        next_page_num += 1


def append_chapter(tonie_audio: TonieAudio, in_file: io.BufferedReader) -> int:

    chapter_num = len(tonie_audio.header.chapter_start_pages)
    start_page_num = len(tonie_audio.pages)
    tonie_audio.header.chapter_start_pages.append(start_page_num)
    tonie_audio.pages += parse_ogg(in_file)
    return chapter_num


def compose_tonie(tonie_audio: TonieAudio, chapter_nums: list[int],
                  out_file: io.BufferedWriter) -> list[int]:

    out_file.write(bytearray(0x1000)) # placeholder

    sha1 = hashlib.sha1()

    output_chapter_page_nums = []
    granule_position = 0
    next_page_num = 0
    first = True

    for chapter_num in chapter_nums:
        output_chapter_page_nums.append(next_page_num)
        page_nums = tonie_audio.get_chapter_page_nums(chapter_num)
        if first:
            if chapter_num > 0:
                page_nums = [0, 1, 2] + page_nums
            first = False
        
        for page_num in page_nums:
            page = tonie_audio.pages[page_num]
            granule_position += page.duration
            if page_num < 3:
                page_data = page.raw()
            else:
                page_data = page.adjusted(granule_position, next_page_num)
            out_file.write(page_data)
            sha1.update(page_data)
            next_page_num += 1

    tonie_header = protobuf_header.TonieHeader()  # type: ignore
    tonie_header.dataHash = sha1.digest()
    tonie_header.dataLength = out_file.seek(0, 1) - 0x1000
    tonie_header.timestamp = tonie_audio.header.timestamp
    tonie_header.chapterPages.extend(output_chapter_page_nums)
    tonie_header.padding = bytes(0x100)

    tonie_header_data = tonie_header.SerializeToString()
    pad = 0xFFC - len(tonie_header_data) + 0x100
    tonie_header.padding = bytes(pad)
    tonie_header_data = tonie_header.SerializeToString()

    out_file.seek(0)
    out_file.write(struct.pack(">L", len(tonie_header_data)))
    out_file.write(tonie_header_data)

    return output_chapter_page_nums
