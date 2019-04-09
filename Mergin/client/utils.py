import os
import io
import hashlib


def generate_checksum(file, chunk_size=4096):
    """
    Generate checksum for file from chunks.

    :param file: file to calculate checksum
    :param chunk_size: size of chunk
    :return: sha1 checksum
    """
    checksum = hashlib.sha1()
    with open(file, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                return checksum.hexdigest()
            checksum.update(chunk)


def save_to_file(stream, path):
    """
    Save readable object in file.
    :param stream: object implementing readable interface
    :param path: destination file path
    """
    directory = os.path.abspath(os.path.dirname(path))
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(path, 'wb') as output:
        writer = io.BufferedWriter(output, buffer_size=32768)
        while True:
            part = stream.read(4096)
            if part:
                writer.write(part)
            else:
                writer.flush()
                break
