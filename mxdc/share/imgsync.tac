#!/usr/bin/env python

# Invoke this script with:
# $ twistd -ny imgsync.tac

from twisted.application import service
from mxdc.services.imagesync import get_service

# prepare service for twistd
application = service.Application('Data Sync Server')
service = get_service()
service.setServiceParent(application)

