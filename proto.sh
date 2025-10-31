SRC_DIR="tonie-skipper"
protoc --proto_path="$SRC_DIR" --pyi_out="$SRC_DIR" --python_out="$SRC_DIR" "$SRC_DIR/tonie_header.proto"