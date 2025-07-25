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


def adjust_page_header(header, body, granule_position, page_num):
    modified_header = list(header)
    modified_header[2] = granule_position
    modified_header[4] = page_num
    modified_header[5] = 0  # zero checksum
    header_data = struct.pack(PAGE_HEADER_FORMAT, *modified_header)
    checksum = crc32(OGG_MAGIC + header_data + body)
    modified_header[5] = checksum
    return struct.pack(PAGE_HEADER_FORMAT, *modified_header)


class AudioData:

    def __init__(self, timestamp: int):

        self.timestamp = timestamp
        self.prefix_page_data = b""
        self.align_page_data = b""
        self.align_duration = 0
        self.chapter_pages: dict[int, list] = {}


def parse(in_file: io.BufferedReader) -> AudioData:

    file_size = in_file.seek(0, 2)
    in_file.seek(0)

    header_size = struct.unpack(">L", in_file.read(4))[0]
    header_data = in_file.read(header_size)
    tonie_header = Header.FromString(header_data)

    page_chapter_nums = {n: i+1 for i, n in enumerate(tonie_header.chapterPages)}

    audio_data = AudioData(tonie_header.timestamp)
    current_chapter_num = -1
    current_chapter_pages = []

    while in_file.tell() < file_size:

        # https://datatracker.ietf.org/doc/html/rfc3533#section-6
        assert in_file.read(4) == OGG_MAGIC
        header_data = in_file.read(23)
        page_header = struct.unpack(PAGE_HEADER_FORMAT, header_data)

        page_num = page_header[4]
        chapter_num = page_chapter_nums.get(page_num)
        if chapter_num is not None:
            if current_chapter_num != -1:
                audio_data.chapter_pages[current_chapter_num] = current_chapter_pages
            current_chapter_num = chapter_num
            current_chapter_pages = []

        packet_count = page_header[6]
        packet_table = in_file.read(packet_count)
        body_data = packet_table
        duration = 0
        continued = False
        for length in packet_table:
            packet = in_file.read(length)
            body_data += packet

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
                duration += FRAME_DURATIONS[config_value] * frame_count

            continued = length == 255

        if page_num < 2:
            audio_data.prefix_page_data += OGG_MAGIC + header_data + body_data
        elif page_num == 2:
            audio_data.align_page_data = OGG_MAGIC + header_data + body_data
            audio_data.align_duration = duration
        else:
            current_chapter_pages.append((page_header, body_data, duration))

    audio_data.chapter_pages[current_chapter_num] = current_chapter_pages

    return audio_data


def export_chapter(audio_data: AudioData, chapter_num: int, out_file: io.BufferedWriter):

    out_file.write(audio_data.prefix_page_data)
    granule_position = 0
    next_page_num = 2

    if chapter_num == 1:
        out_file.write(audio_data.align_page_data)
        granule_position = audio_data.align_duration
        next_page_num = 3

    for header_data, body_data, duration in audio_data.chapter_pages[chapter_num]:
        granule_position += duration
        mod_header_data = adjust_page_header(header_data, body_data,
                                        granule_position, next_page_num)
        page_data = OGG_MAGIC + mod_header_data + body_data
        out_file.write(page_data)
        next_page_num += 1


def compose(audio_data: AudioData, chapter_nums: list[int], out_file: io.BufferedWriter):

    out_file.write(bytearray(0x1000)) # placeholder

    sha1 = hashlib.sha1()
    out_file.write(audio_data.prefix_page_data)
    sha1.update(audio_data.prefix_page_data)

    # need third page for block alignment
    granule_position = audio_data.align_duration
    next_page_num = 3
    out_file.write(audio_data.align_page_data)
    sha1.update(audio_data.align_page_data)

    output_chapter_page_nums = []

    for chapter_num in chapter_nums:

        output_chapter_page_nums.append(next_page_num)

        for page_header, body_data, duration in audio_data.chapter_pages[chapter_num]:
            granule_position += duration
            header_data = adjust_page_header(page_header, body_data,
                                                granule_position, next_page_num)
            page_data = OGG_MAGIC + header_data + body_data
            out_file.write(page_data)
            sha1.update(page_data)
            next_page_num += 1

    tonie_header = Header()
    tonie_header.dataHash = sha1.digest()
    tonie_header.dataLength = out_file.seek(0, 1) - 0x1000
    tonie_header.timestamp = audio_data.timestamp
    tonie_header.chapterPages.extend(chapter_nums)
    tonie_header.padding = bytes(0x100)

    tonie_header_data = tonie_header.SerializeToString()
    pad = 0xFFC - len(tonie_header_data) + 0x100
    tonie_header.padding = bytes(pad)
    tonie_header_data = tonie_header.SerializeToString()

    out_file.seek(0)
    out_file.write(struct.pack(">L", len(tonie_header_data)))
    out_file.write(tonie_header_data)
