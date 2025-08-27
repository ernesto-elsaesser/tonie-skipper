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

    def get_opus_packets(self) -> list[list[bytes]]:

        packets = [[]]
        prev_len = 255
        for segment in self.segments:
            if prev_len < 255:
                packets.append([])
            packets[-1].append(segment)
            prev_len = len(segment)
        return packets

    def set_opus_packets(self, packets: list[list[bytes]]) -> int:

        self.segments = [s for p in packets for s in p]
        if len(packets[-1][-1]) == 255:
            self.segments.append(b"")
        return PAGE_SIZE - self.get_size()

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

        self.info[OPH_SEGMENT_COUNT] = len(self.segments)
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

    # https://datatracker.ietf.org/doc/html/rfc6716#section-3.2.5

    def __init__(self, segments: list[bytes]):

        self.data = [b for s in segments for b in s]

    def get_packing(self) -> int:

        return self.data[0] & 3

    def three_pack(self):

        framepacking = self.get_packing()
        if framepacking == 3:
            return

        self.data[0] |= 3
        if framepacking == 0:
            frame_count_byte = 1
        elif framepacking == 1:
            frame_count_byte = 2
        elif framepacking == 2:
            frame_count_byte = 2 + (1 << 7)  # VBR
            size1 = self.data[2]
            assert size1 < 255, size1
        else:
            raise ValueError
        self.data.insert(1, frame_count_byte)

    def pad(self, pad_len: int):

        framepacking = self.get_packing()
        assert framepacking == 3

        padded = self.data[1] & 64
        if padded > 0:
            raise NotImplementedError("already padded")

        self.data[1] |= 64  # set padding bit

        if pad_len == 0:
            self.data.insert(2, 0)
            return

        last_seg_len = len(self.data) % 255
        if last_seg_len + pad_len < 255:
            zero_count = pad_len - 1
        else:
            added_segs = (last_seg_len + pad_len) // 255
            added_pads = (pad_len // 255) + 1
            zero_count = pad_len - added_segs - added_pads

        pad_lengths = [255] * (zero_count // 255) + [zero_count % 255]
        padding = [0] * zero_count

        self.data = self.data[:2] + pad_lengths + self.data[2:] + padding

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

    def get_chapter_count(self) -> int: 
        
        return len(self.header.chapter_start_pages)

    def get_chapter_page_nums(self, chapter_num: int) -> list[int]:

        start_page_nums = self.header.chapter_start_pages
        start_num = start_page_nums[chapter_num]
        if chapter_num + 1 < len(start_page_nums):
            end_num = start_page_nums[chapter_num + 1]
        else:
            end_num = len(self.pages)
        return list(range(start_num, end_num))


def parse_tonie(in_file: io.BufferedReader) -> TonieAudio:

    tonie_header = parse_tonie_header(in_file)
    pages = parse_ogg(in_file)

    last_page = pages[-1]
    packets = last_page.get_opus_packets()
    packets[-1] = repack_packet(packets[-1])
    missing_bytes = last_page.set_opus_packets(packets)
    packets[-1] = pad_packet(packets[-1], missing_bytes)
    missing_bytes = last_page.set_opus_packets(packets)
    assert missing_bytes == 0
    last_page.update_checksum()

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

    new_chapter_num = tonie_audio.get_chapter_count()
    next_page_num = len(tonie_audio.pages)
    tonie_audio.header.chapter_start_pages.append(next_page_num)

    src_pages = parse_ogg(in_file)

    last_page = tonie_audio.pages[-1]
    granule_position = last_page.info[OPH_GRANULE_POS]
    next_page_packets: list[list[bytes]] = []
    next_page_size = 27
    next_page_seg_count = 0

    for src_page in src_pages[2:]:
        for packet in src_page.get_opus_packets():

            added_size = len(packet) + sum(len(s) for s in packet)
            assert 27 + added_size < PAGE_SIZE, added_size

            if next_page_size + added_size > PAGE_SIZE or next_page_seg_count + len(packet) > 255:
                dst_page = OggPage(last_page.info)
                dst_page.info[OPH_PAGE_NO] = next_page_num
                pad_page(dst_page, next_page_packets)
                granule_position += dst_page.get_duration()
                dst_page.info[OPH_GRANULE_POS] = granule_position
                dst_page.update_checksum()
                tonie_audio.pages.append(dst_page)
                next_page_num += 1
                next_page_packets = []
                next_page_size = 27
                next_page_seg_count = 0

            next_page_packets.append(packet)
            next_page_seg_count += len(packet)
            next_page_size += added_size

    return new_chapter_num


def pad_page(page: OggPage, packets: list[list[bytes]]) -> OggPage:

    missing_bytes = page.set_opus_packets(packets)
    if missing_bytes == 0:
        return page

    pre_size = page.get_size()
    pre_last_packet_lens = [len(s) for s in packets[-1]]

    packets[-1] = repack_packet(packets[-1])
    missing_bytes = page.set_opus_packets(packets)
    if missing_bytes == 0:
        return page

    packets[-2] = repack_packet(packets[-2])
    missing_bytes = page.set_opus_packets(packets)
    if missing_bytes == 0:
        return page

    packets[-1] = pad_packet(packets[-1], missing_bytes)
    missing_bytes = page.set_opus_packets(packets)
    if missing_bytes == 0:
        return page

    if missing_bytes == 1:
        packets[-2] = pad_packet(packets[-2], None)
        missing_bytes = page.set_opus_packets(packets)
        if missing_bytes == 0:
            return page

    page_num = page.info[OPH_PAGE_NO]
    post_size = page.get_size()
    post_last_packet_lens = [len(s) for s in packets[-1]]
    raise AssertionError(page_num, pre_size, post_size,
                         pre_last_packet_lens, post_last_packet_lens)


# https://datatracker.ietf.org/doc/html/rfc6716#section-3.2.5

def repack_packet(packet: list[bytes]) -> list[bytes]:

    data = [b for s in packet for b in s]

    framepacking = data[0] & 3
    if framepacking != 3:
        data[0] |= 3
        if framepacking == 0:
            frame_count_byte = 1
        elif framepacking == 1:
            frame_count_byte = 2
        elif framepacking == 2:
            frame_count_byte = 2 + (1 << 7)  # VBR
            size1 = data[2]
            assert size1 < 255, size1
        else:
            raise ValueError
        data.insert(1, frame_count_byte)

    return [bytes(data[i:i + 255]) for i in range(0, len(data), 255)]


def pad_packet(packet: list[bytes], pad_len: int | None) -> list[bytes]:

    data = [b for s in packet for b in s]

    framepacking = data[0] & 3
    assert framepacking == 3

    is_padded = data[1] & 64
    assert is_padded == 0

    data[1] |= 64  # set padding bit

    if pad_len is None:
        data.insert(2, 0)
    else:
        last_seg_len = len(data) % 255
        if last_seg_len + pad_len < 255:
            zero_count = pad_len - 1
        else:
            added_segs = (last_seg_len + pad_len) // 255
            added_pads = (pad_len // 255) + 1
            zero_count = pad_len - added_segs - added_pads

        pad_lengths = [255] * (zero_count // 255) + [zero_count % 255]
        padding = [0] * zero_count

        data = data[:2] + pad_lengths + data[2:] + padding

    return [bytes(data[i:i + 255]) for i in range(0, len(data), 255)]


def compose(tonie_audio: TonieAudio,
            out_file: io.BufferedWriter,
            chapter_nums: list[int] | None = None,
            add_header: bool = True) -> list[int]:

    if chapter_nums is None:
        chapter_count = tonie_audio.get_chapter_count()
        chapter_nums = list(range(chapter_count))

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
