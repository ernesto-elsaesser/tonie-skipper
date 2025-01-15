import sys

input_path, output_path = sys.argv[1:3]

input_file = open(input_path, "rb")
output_file = open(output_path, "wb")

input_file.seek(0x1000)
data = input_file.read()
input_file.close()
output_file.write(data)
output_file.close()
