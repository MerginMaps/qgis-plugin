#!/usr/bin/env bash

set -e

if [ -z "$1" ]
  then
    echo "Please specify py-client git branch/tag you want to use"
    exit 1
fi

VERSION=$1
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
rm -f mergin.zip
rm -rf mergin-py-client
# get py-client
git clone https://github.com/lutraconsulting/mergin-py-client.git
cd mergin-py-client
git checkout $VERSION
# prepare py-client dependencies
python3 setup.py sdist bdist_wheel
mkdir -p mergin/deps
# without __init__.py the deps dir may get recognized as "namespace package" in python
# and it can break qgis plugin unloading mechanism - see #126
touch mergin/deps/__init__.py
pip3 wheel -r mergin_client.egg-info/requires.txt -w mergin/deps
# special care for pygeodiff
unzip mergin/deps/pygeodiff-*.whl -d mergin/deps
# remove unncesessary files
rm -rf mergin/deps/*.dist-info mergin/deps/*.data
# download geodiff binaries for multiple platforms
GEODIFF_VER="$(geodiff="$(cat mergin_client.egg-info/requires.txt | grep pygeodiff)";echo ${geodiff#pygeodiff==})"
echo "Downloading binaries for $GEODIFF_VER ..." 
cd mergin/deps
mkdir -p tmp
platforms=(win32 win_amd64 macosx_10_14_x86_64 manylinux2010_x86_64)
for platform in "${platforms[@]}"
do
pip3 download --only-binary=:all: --no-deps --platform ${platform} --python-version 36 --implementation cp --abi cp36m pygeodiff==$GEODIFF_VER
unzip -o pygeodiff-$GEODIFF_VER-cp36-cp36m-${platform}.whl -d tmp
# ignore failures on copy
cp tmp/pygeodiff/*.{so,dll,dylib} ./pygeodiff 2>/dev/null || :
rm pygeodiff-$GEODIFF_VER-cp36-cp36m-${platform}.whl
done
rm -r tmp
cd ../../..
# create final .zip
rm -rf Mergin/mergin
cp -r mergin-py-client/mergin Mergin
rm -rf mergin-py-client
zip -r mergin.zip Mergin/ -x Mergin/__pycache__/\*
