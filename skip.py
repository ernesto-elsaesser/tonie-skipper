import sys
import audio


# usage: python3 skip.py INPUT_PATH OUTPUT_DIR CHAPTER_LIST
# INPUT_DIR - path to folder from SD card
# OUTPUT_DIR - path to the output folder
# CHAPTER_LIST - comma-separated list of chapter numbers (starting from 0)

input_dir, output_dir, chapter_list = sys.argv[1:4]
output_chapter_nums = [int(n) for n in chapter_list.split(",")]

in_file_name = f"{input_dir}/500304E0"
print(in_file_name)
with open(in_file_name, "rb") as in_file:
    tonie_audio = audio.parse_tonie(in_file)

out_file_name = f"{output_dir}/500304E0"
print(out_file_name)
with open(out_file_name, "wb") as out_file:
    audio.compose_tonie(tonie_audio, output_chapter_nums, out_file)

