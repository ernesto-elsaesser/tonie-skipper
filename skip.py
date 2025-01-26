import sys
import struct
import hashlib
import protobuf_header


# usage: python3 skip.py INPUT_PATH OUTPUT_DIR CHAPTER_LIST
# INPUT_PATH - path to a 500304E0 file (Tonie Audio Format) from the SD card
# OUTPUT_DIR - path to the output folder
# CHAPTER_LIST - comma-separated list of chapter numbers (starting from 1)

# partially adapted from https://github.com/bailli/opus2tonie


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


def adjust_page_header(header, body, granule_position, page_num):
    modified_header = list(header)
    modified_header[2] = granule_position
    modified_header[4] = page_num
    modified_header[5] = 0  # zero checksum
    header_data = struct.pack(PAGE_HEADER_FORMAT, *modified_header)
    checksum = crc32(OGG_MAGIC + header_data + body)
    modified_header[5] = checksum
    return struct.pack(PAGE_HEADER_FORMAT, *modified_header)


input_path, output_dir, chapter_list = sys.argv[1:4]

output_chapter_nums = [int(n) for n in chapter_list.split(",")]

input_file = open(input_path, "rb")
file_size = input_file.seek(0, 2)
input_file.seek(0)

header_size = struct.unpack(">L", input_file.read(4))[0]
header_data = input_file.read(header_size)
orig_header = protobuf_header.TonieHeader.FromString(header_data)

page_chapter_nums = {n: i+1 for i, n in enumerate(orig_header.chapterPages)}

prefix_page_data = b""
chapter_pages = {}
current_chapter_num = None
current_chapter_pages = None

while input_file.tell() < file_size:

    # https://datatracker.ietf.org/doc/html/rfc3533#section-6
    assert input_file.read(4) == OGG_MAGIC
    header_data = input_file.read(23)
    page_header = struct.unpack(PAGE_HEADER_FORMAT, header_data)

    page_num = page_header[4]
    chapter_num = page_chapter_nums.get(page_num)
    if chapter_num is not None:
        if current_chapter_num is not None:
            chapter_pages[current_chapter_num] = current_chapter_pages
        current_chapter_num = chapter_num
        current_chapter_pages = []

    packet_count = page_header[6]
    packet_table = input_file.read(packet_count)
    body_data = packet_table
    duration = 0
    continued = False
    for length in packet_table:
        packet = input_file.read(length)
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
            duration += FRAME_DURATIONS[config_value] * frame_count

        continued = length == 255

    if page_num < 2:
        prefix_page_data += OGG_MAGIC + header_data + body_data
    else:
        current_chapter_pages.append((page_header, body_data, duration))

chapter_pages[current_chapter_num] = current_chapter_pages
input_file.close()


for chapter_num, pages in chapter_pages.items():

    file_name = output_dir + f"/chapter{chapter_num}.ogg"
    print(file_name)
    output_file = open(file_name, "wb")
    output_file.write(prefix_page_data)
    granule_position = 0
    next_page_num = 2

    for header_data, body_data, duration in pages:
        granule_position += duration
        mod_header_data = adjust_page_header(header_data, body_data,
                                         granule_position, next_page_num)
        page_data = OGG_MAGIC + mod_header_data + body_data
        output_file.write(page_data)
        next_page_num += 1


file_name = output_dir + "/500304E0"
print(file_name)
output_file = open(file_name, "wb")
output_file.write(bytearray(0x1000)) # placeholder

sha1 = hashlib.sha1()
output_file.write(prefix_page_data)
sha1.update(prefix_page_data)

output_chapter_page_nums = []
granule_position = 0
next_page_num = 2

# need third page for block alignment
if output_chapter_nums[0] != 1:
    page_header, body_data, duration = chapter_pages[1][0]
    granule_position += duration
    header_data = adjust_page_header(page_header, body_data,
                                            granule_position, next_page_num)
    page_data = OGG_MAGIC + header_data + body_data
    sha1.update(page_data)
    output_file.write(page_data)
    next_page_num += 1


for chapter_num in output_chapter_nums:

    print(" - chapter", chapter_num)

    output_chapter_page_nums.append(next_page_num)

    for page_header, body_data, duration in chapter_pages[chapter_num]:
        granule_position += duration
        header_data = adjust_page_header(page_header, body_data,
                                            granule_position, next_page_num)
        page_data = OGG_MAGIC + header_data + body_data
        sha1.update(page_data)
        output_file.write(page_data)
        next_page_num += 1


fixed_header = protobuf_header.TonieHeader()
fixed_header.dataHash = sha1.digest()
fixed_header.dataLength = output_file.seek(0, 1) - 0x1000
fixed_header.timestamp = orig_header.timestamp
fixed_header.chapterPages.extend(output_chapter_nums)
fixed_header.padding = bytes(0x100)

fixed_header_data = fixed_header.SerializeToString()
pad = 0xFFC - len(fixed_header_data) + 0x100
fixed_header.padding = bytes(pad)
fixed_header_data = fixed_header.SerializeToString()

output_file.seek(0)
output_file.write(struct.pack(">L", len(fixed_header_data)))
output_file.write(fixed_header_data)

output_file.close()

print("done")
