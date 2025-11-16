class SourceIterator():

    def __init__(self, content):
        self._index=0
        self.data = content

    def pull_byte(self):
        try:
            b = self.data[self._index]
            self._index += 1
            return b
        except IndexError as ex:
            self.finalize()
            raise ex
        except Exception as ex:
            print(self._index, ex)
            raise ex

    def pull_byte_block(self, len, pre=0):
        try:
            start = self._index - pre
            stop = self._index + len
            bb = self.data[start:stop]
            self._index += len
            return bb
        except IndexError as ex:
            self.finalize()
            raise ex
        except Exception as ex:
            print(self._index, ex)
            raise ex
        
    def finalize(self):
        print("Iterator says goodbye")
   