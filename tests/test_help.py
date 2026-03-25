# GPLv3 license
# Copyright Lutra Consulting Limited

import urllib.request

from Mergin.help import MerginHelp


def test_help_urls():
    mh = MerginHelp()

    req = urllib.request.Request(mh.howto_attachment_widget(), method="HEAD")
    resp = urllib.request.urlopen(req)
    assert resp.status == 200

    req = urllib.request.Request(mh.howto_background_maps(), method="HEAD")
    resp = urllib.request.urlopen(req)
    assert resp.status == 200
