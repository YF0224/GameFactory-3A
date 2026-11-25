"""Bounded exact native-log indexing for the existing lossless wire encoders."""
from array import array
from collections.abc import Sequence
from pathlib import Path
import sys


class IndexedLines(Sequence):
    """Intern exact text once, retaining every original physical occurrence."""
    def __init__(self, path, memory_limit):
        self.texts = []
        self.indices = array('I')
        dictionary = {}
        unique_bytes = 0
        with Path(path).open(errors='replace') as stream:
            # TextIO's universal newlines and splitlines match read_text().splitlines().
            for physical in stream:
                for line in physical.splitlines():
                    index = dictionary.get(line)
                    if index is None:
                        index = len(self.texts)
                        dictionary[line] = index
                        self.texts.append(line)
                        unique_bytes += sys.getsizeof(line)+sys.getsizeof(index)
                    self.indices.append(index)
                    used = (unique_bytes+sys.getsizeof(dictionary)+sys.getsizeof(self.texts)
                            +sys.getsizeof(self.indices))
                    if used > memory_limit:
                        raise ValueError('Native runtime log exceeds bounded indexed-memory limit')
        self.storage_bytes = used if self.indices else 0
        self.physical_line_count = len(self.indices)
        self.unique_line_count = len(self.texts)

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self.texts[i] for i in self.indices[index]]
        return self.texts[self.indices[index]]
