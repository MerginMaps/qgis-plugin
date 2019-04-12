import os
import json
import base64
import urllib.parse
import urllib.request

from .utils import save_to_file, generate_checksum
from .multipart import MultipartReader, MultipartEncoder, Field, parse_boundary


def find(items, fn):
    for item in items:
        if fn(item):
            return item

def list_project_directory(directory):
    prefix = os.path.abspath(directory) # .rstrip(os.path.sep)
    proj_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            abs_path = os.path.abspath(os.path.join(root, file))
            proj_path = abs_path[len(prefix) + 1:]
            proj_files.append({
                "path": proj_path,
                "checksum": generate_checksum(abs_path),
                "size": os.path.getsize(abs_path)
            })
    return proj_files


def pretty_diff(diff):
    added = diff["added"]
    removed = diff["removed"]
    updated = diff["updated"]
    renamed = diff["renamed"]

    if renamed:
        print("\n>>> Renamed:")
        for f in renamed:
            print(f["path"], "->", f["new_path"])

    if removed:
        print("\n>>> Removed:")
        print('\n'.join('- ' + f["path"] for f in removed))

    if added:
        print("\n>>> Added:")
        print('\n'.join('+ ' + f["path"] for f in added))

    if updated:
        print("\n>>> Updated:")
        print('\n'.join('M ' + f["path"] for f in updated))


def project_changes(origin, current):
    origin_map = {f["path"]: f for f in origin}
    current_map = {f["path"]: f for f in current}
    removed = [f for f in origin if f["path"] not in current_map]
    added = [f for f in current if f["path"] not in origin_map]

    # updated = list(filter(
    #     lambda f: f["path"] in origin_map and f["checksum"] != origin_map[f["path"]]["checksum"],
    #     current
    # ))
    updated = []
    for f in current:
        path = f["path"]
        if path in origin_map and f["checksum"] != origin_map[path]["checksum"]:
            updated.append(f)

    moved = []
    for rf in removed:
        match = find(
            current,
            lambda f: f["checksum"] == rf["checksum"] and f["size"] == rf["size"] and all(f["path"] != mf["path"] for mf in moved)
        )
        if match:
            moved.append({**rf, "new_path": match["path"]})

    added = [f for f in added if all(f["path"] != mf["new_path"] for mf in moved)]
    removed = [f for f in removed if all(f["path"] != mf["path"] for mf in moved)]

    return {
        "renamed": moved,
        "added": added,
        "removed": removed,
        "updated": updated
    }


class MerginClient:

    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password

        # auth_handler = urllib.request.HTTPBasicAuthHandler()
        # auth_handler.add_password('', url, username, password)
        # opener = urllib.request.build_opener(auth_handler)

        self.opener = urllib.request.build_opener()
        urllib.request.install_opener(self.opener)
        auth_string = '{}:{}'.format(username, password)
        self._auth_header = base64.standard_b64encode(auth_string.encode('utf-8')).decode('utf-8')

    def get(self, path, data=None):
        url = urllib.parse.urljoin(self.url, urllib.parse.quote(path))
        if data:
            url += "?" + urllib.parse.urlencode(data)
        request = urllib.request.Request(url)
        request.add_header("Authorization", "Basic {}".format(self._auth_header))
        return self.opener.open(request) 

    def post(self, path, data, headers={}):
        url = urllib.parse.urljoin(self.url, urllib.parse.quote(path))
        request = urllib.request.Request(url, data, headers)
        request.add_header("Authorization", "Basic {}".format(self._auth_header))
        return self.opener.open(request) 

    def projects_list(self, tags=None):
        params = {"tags": ",".join(tags)} if tags else None
        resp = self.get('/v1/project', params)
        projects = json.load(resp)
        return projects

    def project_info(self, project_name):
        resp = self.get('/v1/project/{}'.format(project_name))
        return json.load(resp)

    def download_project(self, project_name, directory):
        resp = self.get('/v1/project/download/{}'.format(project_name))
        reader = MultipartReader(resp, parse_boundary(resp.headers['Content-Type']))
        part = reader.next_part()
        while part:
            dest = os.path.join(directory, part.filename)
            save_to_file(part, dest)
            part = reader.next_part()

    def upload_project(self, project_name, directory):
        info = self.project_info(project_name)
        files = list_project_directory(directory)
        changes = project_changes(info['files'], files)
        count = sum(len(items) for items in changes.values())
        if count:
            def fields():
                yield Field("changes", json.dumps(changes).encode("utf-8"))
                for file in (changes["added"] + changes["updated"]):
                    path = file["path"]
                    with open(os.path.join(directory, path), 'rb') as f:
                        yield Field(path, f, filename=path, content_type="application/octet-stream")

            encoder = MultipartEncoder(fields())
            try:
                resp = self.post('/v1/project/data_sync/{}'.format(project_name), encoder, encoder.get_headers())
            except urllib.error.HTTPError as e:
                print(e.fp.read())
                raise
