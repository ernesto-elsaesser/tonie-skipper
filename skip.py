import sys
import struct
import hashlib
import protobuf_header


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


input_path, output_path, skip_list = sys.argv[1:4]

input_file = open(input_path, "rb")
output_file = open(output_path, "wb")
skipped_chapters = {int(n) for n in skip_list.split(",")}

file_size = input_file.seek(0, 2)
input_file.seek(0)

header_size = struct.unpack(">L", input_file.read(4))[0]
header_data = input_file.read(header_size)
orig_header = protobuf_header.TonieHeader.FromString(header_data)

chapter_nums = {n: i+1 for i, n in enumerate(orig_header.chapterPages)}

output_file.write(bytearray(0x1000)) # placeholder

sha1 = hashlib.sha1()
chapter_pages = []
granule_position = 0
next_page_num = 0
skip = False

while input_file.tell() < file_size:

    # https://datatracker.ietf.org/doc/html/rfc3533#section-6
    magic = input_file.read(4)
    assert magic == b"OggS", magic
    header_data = input_file.read(23)
    page_header = struct.unpack(PAGE_HEADER_FORMAT, header_data)

    page_num = page_header[4]
    chapter_num = chapter_nums.get(page_num)
    if chapter_num is not None:
        skip = chapter_num in skipped_chapters
        print("chapter", chapter_num, "-", "skip" if skip else "copy")
        if not skip:
            chapter_pages.append(next_page_num)

    packet_count = page_header[6]
    packet_table = input_file.read(packet_count)
    packet_data = b""
    duration = 0
    continued = False
    for length in packet_table:
        packet = input_file.read(length)
        packet_data += packet

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
            duration += FRAME_DURATIONS[config_value] * frame_count

        continued = length == 255

    # need page 2 for alignment
    if page_num > 2:
        if skip:
            continue
        granule_position += duration
        modified_header = list(page_header)
        modified_header[2] = granule_position
        modified_header[4] = next_page_num
        modified_header[5] = 0  # zero checksum
        header_data = struct.pack(PAGE_HEADER_FORMAT, *modified_header)
        checksum = crc32(magic + header_data + packet_table + packet_data)
        modified_header[5] = checksum
        header_data = struct.pack(PAGE_HEADER_FORMAT, *modified_header)

    page_data = magic + header_data + packet_table + packet_data
    sha1.update(page_data)
    output_file.write(page_data)
    next_page_num += 1

input_file.close()

fixed_header = protobuf_header.TonieHeader()
fixed_header.dataHash = sha1.digest()
fixed_header.dataLength = output_file.seek(0, 1) - 0x1000
fixed_header.timestamp = orig_header.timestamp
fixed_header.chapterPages.extend(chapter_pages)
fixed_header.padding = bytes(0x100)

fixed_header_data = fixed_header.SerializeToString()
pad = 0xFFC - len(fixed_header_data) + 0x100
fixed_header.padding = bytes(pad)
fixed_header_data = fixed_header.SerializeToString()

output_file.seek(0)
output_file.write(struct.pack(">L", len(fixed_header_data)))
output_file.write(fixed_header_data)

output_file.close()
