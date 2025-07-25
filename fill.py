import sys
import audio


# usage: python3 skip.py INPUT_PATH OUTPUT_DIR CHAPTER_LIST
# INPUT_PATH - path to a 500304E0 file (Tonie Audio Format) from the SD card
# OPUS_PATH - path to Ogg Opus file
# OUTPUT_DIR - path to the output folder

input_path, opus_path, output_dir = sys.argv[1:4]

print(input_path)
with open(input_path, "rb") as in_file:
    tonie_audio = audio.parse_tonie(in_file)

print(opus_path)
with open(opus_path, "rb") as opus_file:
    fill_pages = audio.parse_opus(opus_file)

out_pages = {i: tonie_audio.pages[i] for i in range(3)}
for page_num, page in fill_pages.items():
    out_pages[page_num + 3] = page

out_audio = audio.TonieAudio(out_pages, tonie_audio.timestamp, {})

out_file_name = f"{output_dir}/500304E0"
print(input_path)
with open(out_file_name, "wb") as out_file:
    audio.compose_tonie(out_audio, [0], out_file)

