import sys
import audio


# usage: python3 skip.py INPUT_PATH OUTPUT_DIR CHAPTER_LIST
# INPUT_PATH - path to a 500304E0 file (Tonie Audio Format) from the SD card
# OUTPUT_DIR - path to the output folder
# CHAPTER_LIST - comma-separated list of chapter numbers (starting from 1)

# partially adapted from https://github.com/bailli/opus2tonie

input_path, output_dir, chapter_list = sys.argv[1:4]
output_chapter_nums = [int(n) for n in chapter_list.split(",")]

print(input_path)
with open(input_path, "rb") as in_file:
    audio_data = audio.parse(in_file)

for chapter_num in audio_data.chapter_pages:
    ogg_file_name = f"{output_dir}/chapter{chapter_num}.ogg"
    print(ogg_file_name)
    with open(ogg_file_name, "wb") as ogg_file:
        audio.export_chapter(audio_data, chapter_num, ogg_file)

out_file_name = f"{output_dir}/500304E0"
print(input_path)
with open(out_file_name, "wb") as out_file:
    audio.compose(audio_data, output_chapter_nums, out_file)

