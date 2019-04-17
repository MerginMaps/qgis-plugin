#!/usr/bin/env bash

set -e

VERSION=$1
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
rm -f $DIR/mergin.zip
pip download --extra-index-url https://pypiserver.cloud.lutraconsulting.co.uk/ mergin-client==$VERSION
mv mergin_client-$VERSION-py3-none-any.whl $DIR/Mergin/mergin_client.whl
zip -r mergin.zip Mergin/ -x Mergin/__pycache__/\* -x Mergin/mergin/\*
