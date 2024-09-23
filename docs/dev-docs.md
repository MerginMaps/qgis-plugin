
# Developer's documentation
## Development/Testing

### On unix 
Download python [client](https://github.com/MerginMaps/python-api-client), install deps and
link to qgis plugin:
```
    ln -s <path-to-py-client>/mergin/ <path-to-mergin-qgis-plugin>/Mergin/mergin
```

Now link the plugin to your QGIS profile python, e.g. for MacOS
```  
    ln -s <path-to-mergin-qgis-plugin>/Mergin/ <path-to-QGIS-user-folder>/QGIS3/profiles/default/python/plugins/Mergin
```

### On windows 

Download python [client](https://github.com/MerginMaps/python-api-client), install deps and
link to qgis plugin. You might need admin privileges to run these commands:
```
    mklink /J <path-to-mergin-qgis-plugin>\Mergin\mergin <path-to-python-api-client>\mergin
```

Now link the plugin to your QGIS profile python:
```
    mklink /J <path-to-QGIS-user-folder>\QGIS3\profiles\default\python\plugins\Mergin <path-to-mergin-qgis-plugin>\Mergin
```

## Production

Plugin packages are built as GitHub actions for every commit.
When releasing, make sure to check if [run-test.yml](../.github/workflows/run-test.yml) is using the latest QGIS release tag for auto-tests.
