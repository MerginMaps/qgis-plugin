# mergin QGIS plugin

QGIS plugin to simplify handling of Mergin projects.

## Development/Testing
Download python [client](https://gitlab.cloud.lutraconsulting.co.uk/mergin/py-client) and
link to qgis plugin:

    ln -s <path-to-py-client>/mergin/ <path-to-mergin-qgis-plugin>/Mergin/mergin

## Production
Download py-client wheel from https://pypiserver.cloud.lutraconsulting.co.uk/ to ship with plugin
and update its [version](Mergin/utils.py).