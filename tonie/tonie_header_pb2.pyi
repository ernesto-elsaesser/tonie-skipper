from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class TonieHeader(_message.Message):
    __slots__ = ("dataHash", "dataLength", "timestamp", "chapterPages", "padding")
    DATAHASH_FIELD_NUMBER: _ClassVar[int]
    DATALENGTH_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    CHAPTERPAGES_FIELD_NUMBER: _ClassVar[int]
    PADDING_FIELD_NUMBER: _ClassVar[int]
    dataHash: bytes
    dataLength: int
    timestamp: int
    chapterPages: _containers.RepeatedScalarFieldContainer[int]
    padding: bytes
    def __init__(self, dataHash: _Optional[bytes] = ..., dataLength: _Optional[int] = ..., timestamp: _Optional[int] = ..., chapterPages: _Optional[_Iterable[int]] = ..., padding: _Optional[bytes] = ...) -> None: ...
