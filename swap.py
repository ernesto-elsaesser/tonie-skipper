import sys
import audio


# usage: python3 skip.py INPUT_PATH OUTPUT_DIR OPUS_PATH OPUS_PATH ...
# INPUT_DIR - path to folder from SD card
# OUTPUT_DIR - path to the output folder
# OPUS_PATH - path to Ogg Opus file (one or more)

input_dir, output_dir, *opus_paths = sys.argv[1:]

in_file_name = f"{input_dir}/500304E0"
print(in_file_name)
with open(in_file_name, "rb") as in_file:
    tonie_audio = audio.parse_tonie(in_file)

chapter_nums = []
for opus_path in opus_paths:
    print(opus_path)
    with open(opus_path, "rb") as opus_file:
        chapter_num = audio.append_chapter(tonie_audio, opus_file)
        chapter_nums.append(chapter_num)

out_file_name = f"{output_dir}/500304E0"
print(out_file_name)
with open(out_file_name, "wb") as out_file:
    audio.compose(tonie_audio, out_file, chapter_nums)
