#!/usr/bin/env bash

DEPLOY_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
TOP_DIR=$( dirname "${DEPLOY_DIR}" )

python3 -m venv venv &&
source venv/bin/activate &&
cd "${TOP_DIR}" &&

python setup.py install