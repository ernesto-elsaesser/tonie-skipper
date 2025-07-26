import io
import struct
import hashlib
from . import tonie_header_pb2


OGG_MAGIC = b"OggS"
PAGE_HEADER_FORMAT = "<BBQLLLB"
SAMPLE_RATE_KHZ = 48
# https://datatracker.ietf.org/doc/html/rfc6716#section-3.1
FRAME_DURATIONS = {c: [2.5, 5, 10, 20][c % 4] * SAMPLE_RATE_KHZ
                   for c in range(16, 32)}
PAGE_SIZE = 0x1000


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


OPH_VERSION = 0
OPH_PAGE_TYPE = 1
OPH_GRANULE_POS = 2
OPH_SERIAL_NO = 3
OPH_PAGE_NO = 4
OPH_CHECKSUM = 5
OPH_SEGMENT_COUNT = 6


class OggPage:

    def __init__(self, info: list):

        self.info = info
        self.segments: list[bytes] = []

    def set_opus_packets(self, packets: list[list[bytes]]) -> int:

        self.segments = [s for p in packets for s in p]
        if len(packets[-1][-1]) == 255:
            self.segments.append(b"")
        return self.get_size()

    def get_duration(self) -> int:

        # https://datatracker.ietf.org/doc/html/rfc7845

        duration = 0
        prev_length = 0
        for segment in self.segments:
            if prev_length < 255:  # continued segment
                config_value = segment[0] >> 3
                framepacking = segment[0] & 3
                if framepacking == 0:
                    frame_count = 1
                elif framepacking == 1:
                    frame_count = 2
                elif framepacking == 2:
                    frame_count = 2
                elif framepacking == 3:
                    frame_count = segment[1] & 63
                else:
                    raise ValueError
                duration += FRAME_DURATIONS[config_value] * frame_count
            prev_length = len(segment)

        return duration

    def serialize_with(self, is_last: bool, granule_position: int, page_num: int):

        adj_info = list(self.info)
        adj_info[OPH_PAGE_TYPE] = 4 if is_last else 0
        adj_info[OPH_GRANULE_POS] = granule_position
        adj_info[OPH_PAGE_NO] = page_num
        page = OggPage(adj_info)
        page.segments = self.segments
        page.update_checksum()
        return page.serialize()

    def update_checksum(self):

        self.info[OPH_CHECKSUM] = 0
        checksum_data = self.serialize()
        self.info[OPH_CHECKSUM] = crc32(checksum_data)

    def serialize_header(self) -> bytes:

        return struct.pack(PAGE_HEADER_FORMAT, *self.info)

    def serialize_body(self) -> bytes:

        body = bytes(len(s) for s in self.segments)
        for segment in self.segments:
            body += segment
        return body

    def serialize(self):

        return OGG_MAGIC + self.serialize_header() + self.serialize_body()

    def get_size(self) -> int:

        return 27 + len(self.segments) + sum(len(s) for s in self.segments)


class OpusPacket:

    def __init__(self, segments: list[bytes]):

        self.data = [b for s in segments for b in s]

    def three_pack(self) -> int:

        framepacking = self.data[0] & 3
        if framepacking == 3:
            padded = self.data[1] & 64
            if padded > 0:
                raise NotImplementedError("already padded")
            return 0

        self.data[0] |= 3
        if framepacking == 0:
            frame_count_byte = 1
        elif framepacking == 1:
            frame_count_byte = 2
        elif framepacking == 2:
            frame_count_byte = 2 + (1 << 7)  # VBR
            size1 = self.data[2]
            assert size1 < 255, size1
            #    size1 += self.data[3]
            #    pre_len = 3
        else:
            raise ValueError
        self.data.insert(1, frame_count_byte)
        return 1

    def get_segments(self) -> list[bytes]:

        return [bytes(self.data[i:i + 255])
                for i in range(0, len(self.data), 255)]


class TonieHeader:

    def __init__(self, header: bytes):
        self.protobuf = tonie_header_pb2.TonieHeader.FromString(header)
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
        info = struct.unpack(PAGE_HEADER_FORMAT, header)
        page = OggPage(list(info))
        assert page.info[OPH_PAGE_NO] == len(pages)
        segment_count = page.info[OPH_SEGMENT_COUNT]
        segment_lengths = in_file.read(segment_count)
        for length in segment_lengths:
            segment = in_file.read(length)
            page.segments.append(segment)

        pages.append(page)

    return pages


def append_chapter(tonie_audio: TonieAudio, in_file: io.BufferedReader) -> int:

    chapter_num = len(tonie_audio.header.chapter_start_pages)
    next_page_num = len(tonie_audio.pages)
    tonie_audio.header.chapter_start_pages.append(next_page_num)

    src_pages = parse_ogg(in_file)[2:]
    src_pages.insert(0, tonie_audio.pages.pop())  # add last page for padding
    next_page_num -= 1

    packets: list[list[bytes]] = []
    for src_page in src_pages:
        packets.append([])
        prev_len = 255
        for segment in src_page.segments:
            if prev_len < 255:
                packets.append([])
            packets[-1].append(segment)
            prev_len = len(segment)

    last_page = tonie_audio.pages[-1]
    granule_position = last_page.info[OPH_GRANULE_POS]
    next_page_packets: list[list[bytes]] = []
    next_page_size = 27
    next_page_seg_count = 0

    for packet in packets:

        added_size = len(packet) + sum(len(s) for s in packet)
        assert 27 + added_size < PAGE_SIZE, added_size

        if next_page_size + added_size > PAGE_SIZE or next_page_seg_count + len(packet) > 255:
            dst_page = OggPage(last_page.info)
            dst_page.info[OPH_PAGE_NO] = next_page_num
            pad_page(dst_page, next_page_packets)
            granule_position += dst_page.get_duration()
            dst_page.info[OPH_GRANULE_POS] = granule_position
            dst_page.info[OPH_SEGMENT_COUNT] = len(dst_page.segments)
            dst_page.update_checksum()
            tonie_audio.pages.append(dst_page)
            next_page_num += 1
            next_page_packets = []
            next_page_size = 27
            next_page_seg_count = 0

        next_page_packets.append(packet)
        next_page_seg_count += len(packet)
        next_page_size += added_size

    return chapter_num


def pad_page(page: OggPage, packets: list[list[bytes]]) -> OggPage:

    unpadded_size = page.set_opus_packets(packets)
    pad_length = PAGE_SIZE - unpadded_size
    if pad_length == 0:
        return page

    # https://datatracker.ietf.org/doc/html/rfc6716#section-3.2.5

    last_packet = OpusPacket(packets[-1])
    prev_packet = OpusPacket(packets[-2])

    pad_length -= last_packet.three_pack()
    packets[-1] = last_packet.get_segments()

    if pad_length > 0:
        pad_length -= prev_packet.three_pack()
        packets[-2] = prev_packet.get_segments()

        if pad_length > 0:

            last_packet.data[1] |= 64  # set padding bit

            last_seg_len = len(packets[-1][-1])
            if last_seg_len + pad_length < 255:
                zero_count = pad_length - 1
            else:
                added_segs = (last_seg_len + pad_length) // 255
                added_pads = (pad_length // 255) + 1
                zero_count = pad_length - added_segs - added_pads

            pad_lengths = [255] * (zero_count // 255) + [zero_count % 255]
            padding = [0] * zero_count
            last_packet.data = last_packet.data[:2] + pad_lengths \
                + last_packet.data[2:] + padding

            packets[-1] = last_packet.get_segments()

    padded_size = page.set_opus_packets(packets)
    if padded_size == PAGE_SIZE - 1:
        prev_packet.data[1] |= 64  # set padding bit
        prev_packet.data.insert(2, 0)
        packets[-2] = prev_packet.get_segments()
        padded_size = page.set_opus_packets(packets)

    if padded_size != PAGE_SIZE:
        last_packet_lens = [len(s) for s in packets[-1]]
        raise AssertionError(page.info[OPH_PAGE_NO], unpadded_size,
                             padded_size, last_packet_lens)

    return page


def compose(tonie_audio: TonieAudio, chapter_nums: list[int],
            out_file: io.BufferedWriter, add_header: bool = True) -> list[int]:

    if add_header:
        out_file.write(bytearray(PAGE_SIZE))  # placeholder

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
            if page_num < 2:
                page_data = page.serialize()
            else:
                is_last = page_num == page_nums[-1]
                granule_position += page.get_duration()
                page_data = page.serialize_with(
                    is_last, granule_position, next_page_num)
            out_file.write(page_data)
            sha1.update(page_data)
            next_page_num += 1

    if add_header:
        tonie_header = tonie_header_pb2.TonieHeader()
        tonie_header.dataHash = sha1.digest()
        tonie_header.dataLength = out_file.seek(0, 1) - PAGE_SIZE
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
