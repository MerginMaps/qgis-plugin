
# Developer's documentation
## Development/Testing
Download python [client](https://github.com/MerginMaps/python-api-client), install deps and
link to qgis plugin:
```
    ln -s <path-to-py-client>/mergin/ <path-to-mergin-qgis-plugin>/Mergin/mergin
```

Now link the plugin to your QGIS profile python, e.g. for MacOS
```  
    ln -s <path-to-mergin-qgis-plugin>/Mergin/ <path-to-QGIS-user-folder>/QGIS3/profiles/default/python/plugins/Mergin
```

## Production

Plugin packages are built as GitHub actions for every commit.
