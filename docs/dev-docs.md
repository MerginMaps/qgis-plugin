
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

### Running tests

Tests live in [`tests/`](../tests) and run via `pytest`. Because the suite depends on QGIS alongside Python testing tooling, conda is the most reliable way to assemble the whole stack. It also enables pinning a specific QGIS version, which is how CI tests across multiple releases. The repo ships an [`environment.yml`](../environment.yml) for it.

1. Install [Miniconda](https://docs.anaconda.com/miniconda/) if you don't have it yet.
2. Create the test environment :
   ```
   conda env create -f environment.yml
   ```
3. Activate it and run the suite from the repo root:
   ```
   conda activate qgis-test-env
   pytest ./tests --cov=Mergin
   ```

## Debugging (VS Code)

1. Install the `python3-debugpy` package. QGIS DevTools relies on `debugpy` being available in QGIS's bundled Python.
2. Install the [QGIS DevTools](https://github.com/nextgis/qgis_devtools) plugin in QGIS and restart QGIS.
3. Activate the QGIS DevTools plugin and copy the JSON snippet it provides into a `launch.json` file inside the `.vscode/` folder of this repository:

   ```json
   {
       "version": "0.2.0",
       "configurations": [
           {
               "name": "Attach to QGIS",
               "type": "debugpy",
               "request": "attach",
               "connect": {
                   "host": "127.0.0.1",
                   "port": 5678
               },
               "justMyCode": true
           }
       ]
   }
   ```

4. Start the debugger.

## Production

Plugin packages are built as GitHub actions for every commit.
When releasing, make sure to check if [run-test.yml](../.github/workflows/run-test.yml) is using the latest QGIS release tag for auto-tests.
