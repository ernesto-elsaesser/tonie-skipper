import sys
from . import audio

def export():
    """
    Export tonie chapters as Ogg files

    INPUT_DIR - path to folder from SD card
    OUTPUT_DIR - path to the output folder
    """

    input_dir, output_dir = sys.argv[1:3]

    in_file_name = f"{input_dir}/500304E0"
    print(in_file_name)
    with open(in_file_name, "rb") as in_file:
        tonie_audio = audio.parse_tonie(in_file)

    for chapter_num in tonie_audio.header.chapter_start_pages:
        ogg_file_name = f"{output_dir}/chapter{chapter_num}.ogg"
        print(ogg_file_name)
        with open(ogg_file_name, "wb") as ogg_file:
            audio.compose(tonie_audio, ogg_file, [chapter_num], False)

def skip():
    """
    Remove chapter of an existing tonie

    INPUT_DIR - path to folder from SD card
    OUTPUT_DIR - path to the output folder
    CHAPTER_LIST - comma-separated list of chapter numbers (starting from 0)
    """

    input_dir, output_dir, chapter_list = sys.argv[1:4]
    output_chapter_nums = [int(n) for n in chapter_list.split(",")]

    in_file_name = f"{input_dir}/500304E0"
    print(in_file_name)
    with open(in_file_name, "rb") as in_file:
        tonie_audio = audio.parse_tonie(in_file)

    out_file_name = f"{output_dir}/500304E0"
    print(out_file_name)
    with open(out_file_name, "wb") as out_file:
        audio.compose(tonie_audio, out_file, output_chapter_nums)


def swap():
    """
    Replace all chapters of an existing tonie with a list of own Ogg files

    INPUT_DIR - path to folder from SD card
    OUTPUT_DIR - path to the output folder
    OPUS_PATH - path to Ogg Opus file (one or more)
    """

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

