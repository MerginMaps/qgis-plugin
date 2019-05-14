#!/usr/bin/env bash

set -e

VERSION=$1
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
rm -f mergin.zip
rm -rf mergin-py-client
# get py-client
git clone git@github.com:lutraconsulting/mergin-py-client.git
cd mergin-py-client
git checkout $VERSION
# prepare py-client dependencies
python3 setup.py sdist bdist_wheel
mkdir -p mergin/deps
pip wheel -r mergin_client.egg-info/requires.txt -w mergin/deps
cd ..
# create final .zip
rm -rf Mergin/mergin
cp -r mergin-py-client/mergin Mergin
rm -rf mergin-py-client
zip -r mergin.zip Mergin/ -x Mergin/__pycache__/\*
