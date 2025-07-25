import sys
import audio


# usage: python3 export.py INPUT_PATH
# INPUT_PATH - path to a 500304E0 file (Tonie Audio Format) from the SD card
# OUTPUT_DIR - path to the output folder

input_path, output_dir = sys.argv[1:3]

print(input_path)
with open(input_path, "rb") as in_file:
    tonie_audio = audio.parse_tonie(in_file)

for chapter_num in tonie_audio.chapter_start_pages:
    ogg_file_name = f"{output_dir}/chapter{chapter_num}.ogg"
    print(ogg_file_name)
    with open(ogg_file_name, "wb") as ogg_file:
        audio.export_chapter(tonie_audio, chapter_num, ogg_file)

