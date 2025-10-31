import sys
from . import audio

def export():
    """
    Export tonie chapters as Ogg files

    input_path - path to the input tonie audio file
    output_dir - path to the output tonie audio file
    """

    input_path, output_dir = sys.argv[1:3]

    print(input_path)
    with open(input_path, "rb") as in_file:
        tonie_audio = audio.parse_tonie(in_file)

    for chapter_num in tonie_audio.header.chapter_start_pages:
        ogg_file_name = f"{output_dir}/chapter{chapter_num}.ogg"
        print(ogg_file_name)
        with open(ogg_file_name, "wb") as ogg_file:
            audio.compose(tonie_audio, ogg_file, [chapter_num], False)

def skip():
    """
    Remove chapter of an existing tonie

    input_path - path to the input tonie audio file
    output_path - path to the output folder
    chapter_list - comma-separated list of chapter numbers (starting from 0)
    """

    input_path, output_path, chapter_list = sys.argv[1:4]
    output_chapter_nums = [int(n) for n in chapter_list.split(",")]

    print(input_path)
    with open(input_path, "rb") as in_file:
        tonie_audio = audio.parse_tonie(in_file)

    print(output_path)
    with open(output_path, "wb") as out_file:
        audio.compose(tonie_audio, out_file, output_chapter_nums)


def swap():
    """
    Replace all chapters of an existing tonie with a list of own Ogg files

    input_path - path to the input tonie audio file
    output_path - path to the output tonie audio file
    *opus_path - path to Ogg Opus file (one or more)
    """

    input_path, output_path, *opus_paths = sys.argv[1:]

    print(input_path)
    with open(input_path, "rb") as in_file:
        tonie_audio = audio.parse_tonie(in_file)

    chapter_nums = []
    for opus_path in opus_paths:
        print(opus_path)
        with open(opus_path, "rb") as opus_file:
            chapter_num = audio.append_chapter(tonie_audio, opus_file)
            chapter_nums.append(chapter_num)

    print(output_path)
    with open(output_path, "wb") as out_file:
        audio.compose(tonie_audio, out_file, chapter_nums)

