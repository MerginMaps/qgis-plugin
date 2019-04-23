#!/usr/bin/env bash

set -e

VERSION=$1
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
rm -f mergin.zip
rm -rf mergin-py-client
git clone git@github.com:lutraconsulting/mergin-py-client.git
cd mergin-py-client
git checkout $VERSION
cd ..
rm -rf Mergin/mergin
cp -r mergin-py-client/mergin Mergin
rm -rf mergin-py-client
zip -r mergin.zip Mergin/ -x Mergin/__pycache__/\*
