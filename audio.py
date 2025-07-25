import io
import struct
import hashlib
import protobuf_header


OGG_MAGIC = b"OggS"
PAGE_HEADER_FORMAT = "<BBQLLLB"
SAMPLE_RATE_KHZ = 48
FRAME_DURATIONS = {c: [2.5, 5, 10, 20][c % 4] * SAMPLE_RATE_KHZ
                   for c in range(16, 32)}

Header = protobuf_header.TonieHeader  # type: ignore

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
        return self.serialize(self.header_fields)
    
    def adjusted(self, granule_position: int, page_num: int):
        mod_fields = list(self.header_fields)
        mod_fields[2] = granule_position
        mod_fields[4] = page_num
        mod_fields[5] = 0  # zero checksum
        pre_header = struct.pack(PAGE_HEADER_FORMAT, *mod_fields)
        checksum = crc32(OGG_MAGIC + pre_header + self.body)
        mod_fields[5] = checksum
        return self.serialize(tuple(mod_fields))
    
    def serialize(self, header_fields: tuple):
        header = struct.pack(PAGE_HEADER_FORMAT, *header_fields)
        return OGG_MAGIC + header + self.body


class TonieAudio:

    def __init__(self, pages: dict[int, OggPage], timestamp: int, chapter_start_pages: dict[int, int]):

        self.pages = pages
        self.timestamp = timestamp
        self.chapter_start_pages = chapter_start_pages

    def get_chapter_pages(self, chapter_num: int) -> list[OggPage]:

        start_page = self.chapter_start_pages[chapter_num]
        end_page = self.chapter_start_pages[chapter_num + 1]
        return [self.pages[i] for i in range(start_page, end_page)]



def parse_tonie(in_file: io.BufferedReader) -> TonieAudio:

    file_size = in_file.seek(0, 2)
    in_file.seek(0)

    header_size = struct.unpack(">L", in_file.read(4))[0]
    header_data = in_file.read(header_size)
    tonie_header = Header.FromString(header_data)
    timestamp = tonie_header.timestamp
    chapter_start_pages = dict(enumerate(tonie_header.chapterPages))

    pages = parse_ogg(in_file, file_size)

    return TonieAudio(pages, timestamp, chapter_start_pages)


def parse_opus(in_file: io.BufferedReader) -> dict[int, OggPage]:

    file_size = in_file.seek(0, 2)
    in_file.seek(0)
    return parse_ogg(in_file, file_size)


def parse_ogg(in_file: io.BufferedReader, file_size: int) -> dict[int, OggPage]:

    pages: dict[int, OggPage] = {}

    while in_file.tell() < file_size:

        # https://datatracker.ietf.org/doc/html/rfc3533#section-6
        assert in_file.read(4) == OGG_MAGIC
        header = in_file.read(23)
        page = OggPage(header)
        page_num: int = page.header_fields[4]
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

        pages[page_num] = page

    return pages


def export_chapter(tonie_audio: TonieAudio, chapter_num: int, out_file: io.BufferedWriter):

    # prefix
    out_file.write(tonie_audio.pages[0].raw())
    out_file.write(tonie_audio.pages[1].raw())

    granule_position = 0
    next_page_num = 2

    if chapter_num == 1:
        align_page = tonie_audio.pages[2]
        out_file.write(align_page.raw())
        granule_position = align_page.duration
        next_page_num = 3

    for page in tonie_audio.get_chapter_pages(chapter_num):
        granule_position += page.duration
        out_file.write(page.adjusted(granule_position, next_page_num))
        next_page_num += 1


def compose_tonie(tonie_audio: TonieAudio, chapter_nums: list[int], out_file: io.BufferedWriter):

    out_file.write(bytearray(0x1000)) # placeholder

    sha1 = hashlib.sha1()

    for page_num in range(3):
        prefix_page = tonie_audio.pages[page_num]
        page_data = prefix_page.raw()
        out_file.write(page_data)
        sha1.update(page_data)

    output_chapter_page_nums = []
    granule_position = tonie_audio.pages[2].duration
    next_page_num = 3
    for chapter_num in chapter_nums:
        output_chapter_page_nums.append(next_page_num)
        for page in tonie_audio.get_chapter_pages(chapter_num):
            granule_position += page.duration
            page_data = page.adjusted(granule_position, next_page_num)
            out_file.write(page_data)
            sha1.update(page_data)
            next_page_num += 1

    tonie_header = Header()
    tonie_header.dataHash = sha1.digest()
    tonie_header.dataLength = out_file.seek(0, 1) - 0x1000
    tonie_header.timestamp = tonie_audio.timestamp
    tonie_header.chapterPages.extend(output_chapter_page_nums)
    tonie_header.padding = bytes(0x100)

    tonie_header_data = tonie_header.SerializeToString()
    pad = 0xFFC - len(tonie_header_data) + 0x100
    tonie_header.padding = bytes(pad)
    tonie_header_data = tonie_header.SerializeToString()

    out_file.seek(0)
    out_file.write(struct.pack(">L", len(tonie_header_data)))
    out_file.write(tonie_header_data)
