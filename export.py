import sys
import audio


# usage: python3 export.py INPUT_PATH
# INPUT_DIR - path to folder from SD card
# OUTPUT_DIR - path to the output folder

input_dir, output_dir = sys.argv[1:3]

in_file_name = f"{input_dir}/500304E0"
print(in_file_name)
with open(in_file_name, "rb") as in_file:
    tonie_audio = audio.parse_tonie(in_file)

for chapter_num in tonie_audio.header.chapter_start_pages:
    ogg_file_name = f"{output_dir}/chapter{chapter_num}.ogg"
    print(ogg_file_name)
    with open(ogg_file_name, "wb") as ogg_file:
        audio.compose(tonie_audio, [chapter_num], ogg_file, False)
