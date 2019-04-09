import re
import io
import uuid


def parse_boundary(content_type):
    return re.match('[^;]+; boundary=(?P<boundary>.+)', content_type).group('boundary').strip('"')


class Part:

    def __init__(self, reader, name, filename=None, content_type=None):
        self.reader = reader
        self.name = name
        self.filename = filename
        self.content_type = content_type
        self.eof = False

    def read(self, length=None):
        if self.eof:
            return None

        if length is None:
            # read whole part
            data = b''
            while True:
                part, self.eof = self.reader._read_part(4096)
                data = data + part
                if self.eof:
                    return data

        data, self.eof = self.reader._read_part(length)
        return data


class MultipartReader:

    def __init__(self, stream, boundary):
        self.stream = stream
        self.chunk_size = 4096 * 4

        self.boundary = boundary
        self.boundary_pattern = re.compile(b'\r\n--' + re.escape(self.boundary.encode()) + b'\r\n')

        header_parts = [
            b'(Content-Type: multipart/form-data\r\n)?',
            b'Content-Disposition: form-data; name="(?P<name>[^"]+)"'
            b'(; filename="(?P<filename>[^"]+)"\r\n)?'
            b'(Content-Type: (?P<content_type>.+)\r\n)?',
            b'\r\n'
        ]
        self.header_pattern = re.compile(b''.join(header_parts))
        self.boundary_lookahead = len(self.boundary) + 8

        # first boundary doesn't start with \r\n, so let's pretend it does
        self.data = b'\r\n'
        self.eof = False

    def _strip_end(self):
        if not self.eof:
            end_pattern = re.compile(b'(\r\n)?--' + re.escape(self.boundary.encode()) + b'--\r\n')
            self.data = self.data[:end_pattern.search(self.data).start()]
            self.eof = True

    def _read_part(self, length):
        # try to fetch required amount of data (+ safe lookahead)
        while len(self.data) - self.boundary_lookahead < length:
            chunk = self.stream.read(self.chunk_size)
            if not chunk:
                self._strip_end()
                break
            self.data = self.data + chunk

        if not self.data:
            return b'', True

        m = self.boundary_pattern.search(self.data[:length + self.boundary_lookahead])
        if m:
            part_data = self.data[:m.start()]
            self.data = self.data[m.start():]
            return part_data, True

        part_data = self.data[:length]
        self.data = self.data[length:]
        return part_data, False


    def next_part(self):
        while True:
            if len(self.data) <= self.boundary_lookahead:
                chunk = self.stream.read(self.chunk_size)
                if not chunk:
                    self._strip_end()
                    return None
                self.data = self.data + chunk

            m = self.boundary_pattern.search(self.data)
            if m:
                self.data = self.data[m.end():]
                hm = self.header_pattern.match(self.data)
                while not hm:
                    # not valid header, probably not enough data, fetch more data
                    chunk = self.stream.read(self.chunk_size)
                    if not chunk:
                        raise ValueError('Unexpected end of stream')
                    self.data = self.data + chunk
                    hm = self.header_pattern.match(self.data)

                self.data = self.data[hm.end():]
                name = hm.group('name').decode()
                filename = (hm.group('filename') or b'').decode()
                ct = (hm.group('content_type') or b'').decode()
                return Part(self, name, filename, ct)

            # throw away unread data
            self.data = self.data[-self.boundary_lookahead:]


class Field:
    def __init__(self, name, data, filename=None, content_type=None):
        self.name = name
        self.data = data
        self.filename = filename
        self.content_type = content_type


def b(data):
    return data.encode("utf-8")


class MultipartEncoder:

    def __init__(self, fields, boundary=None):
        self.fields = fields
        self.boundary = boundary if boundary else uuid.uuid4().hex
        self.buffer = io.BytesIO()
        self.eof = False
        self._field = None

    def get_headers(self):
        return {
            "Content-Type": "multipart/form-data; boundary={}".format(self.boundary)
        }

    def read(self, size=8192):
        if self._field:
            read_size = size - self.buffer.tell()
            data = self._field.data.read(read_size)
            if data:
                self.buffer.write(data)
            else:
                self._field = None

        if not self._field:
            field = next(self.fields, None)
            if field:
                self.buffer.write(b'\r\n--' + b(self.boundary) + b'\r\n')
                if field.filename:
                    self.buffer.write(b'Content-Disposition: form-data; name="' + b(field.name) + b'"; filename="' + b(field.filename) + b'"\r\n')
                    self.buffer.write(b'Content-Type: ' + b(field.content_type) + b'\r\n')
                else:
                    self.buffer.write(b'Content-Disposition: form-data; name="' + b(field.name) + b'"\r\n')
                self.buffer.write(b'\r\n')

                if type(field.data) == bytes:
                    self.buffer.write(field.data)
                else:
                    self.buffer.write(field.data.read(size))
                    self._field = field
            elif not self.eof:
                self.eof = True
                self.buffer.write(b'--' + b(self.boundary) + b'--\r\n')

        pos = self.buffer.tell()
        self.buffer.seek(0)
        data = self.buffer.read(min(pos, size))
        overflow = self.buffer.read(pos - size) if pos > size else None
        self.buffer.seek(0)
        if overflow:
            self.buffer.write(overflow)
        return data
