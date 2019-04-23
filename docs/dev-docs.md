
# Developer's documentation
## Development/Testing
Download python [client](https://github.com/lutraconsulting/mergin-py-client) and
link to qgis plugin:

    ln -s <path-to-py-client>/mergin/ <path-to-mergin-qgis-plugin>/Mergin/mergin

## Production
To create zip with py-client dependency with `<version>` run

    bash scripts/package.sh <version>
