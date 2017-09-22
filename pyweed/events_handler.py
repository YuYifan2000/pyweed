# -*- coding: utf-8 -*-
"""
Container for events.

:copyright:
    Mazama Science, IRIS
:license:
    GNU Lesser General Public License, Version 3
    (http://www.gnu.org/copyleft/lesser.html)
"""

from __future__ import (absolute_import, division, print_function)

from pyweed.signals import SignalingThread, SignalingObject
import logging
from obspy.core.event.catalog import Catalog
from pyweed.pyweed_utils import get_service_url, CancelledException
from PyQt4 import QtCore
import concurrent.futures

LOGGER = logging.getLogger(__name__)


def load_events(client, parameters):
    """
    Execute one query for event data. This is a standalone function so we can
    run it in a separate thread.
    """
    try:
        LOGGER.info('Loading events: %s', get_service_url(client, 'event', parameters))
        return client.get_events(**parameters)
    except Exception as e:
        # If no results found, the client will raise an exception, we need to trap this
        # TODO: this should be much cleaner with a fix to https://github.com/obspy/obspy/issues/1656
        if str(e).startswith("No data"):
            LOGGER.warning("No events found! Your query may be too narrow.")
            return Catalog()
        else:
            raise


class EventsLoader(SignalingThread):
    """
    Thread to handle event requests
    """
    progress = QtCore.pyqtSignal()

    def __init__(self, request):
        """
        Initialization.
        """
        # Keep a reference to globally shared components
        self.request = request
        self.futures = {}
        super(EventsLoader, self).__init__()

    def run(self):
        """
        Make a webservice request for events using the passed in options.
        """
        self.setPriority(QtCore.QThread.LowestPriority)
        self.clearFutures()
        self.futures = {}

        catalog = None
        LOGGER.info("Making %d event requests" % len(self.request.sub_requests))
        with concurrent.futures.ThreadPoolExecutor(5) as executor:
            for sub_request in self.request.sub_requests:
                # Dictionary lets us look up argument by result later
                self.futures[executor.submit(load_events, self.request.client, sub_request)] = sub_request
            # Iterate through Futures as they complete
            for result in concurrent.futures.as_completed(self.futures):
                LOGGER.debug("Events loaded")
                try:
                    if not catalog:
                        catalog = result.result()
                    else:
                        catalog += result.result()
                    self.progress.emit()
                except Exception:
                    self.progress.emit()
        self.futures = {}
        catalog = self.request.process_result(catalog)
        self.done.emit(catalog)

    def clearFutures(self):
        """
        Cancel any outstanding tasks
        """
        if self.futures:
            for future in self.futures:
                if not future.done():
                    LOGGER.debug("Cancelling unexecuted future")
                    future.cancel()

    def cancel(self):
        """
        User-requested cancel
        """
        self.done.disconnect()
        self.progress.disconnect()
        self.clearFutures()


class EventsHandler(SignalingObject):
    """
    Container for events.
    """

    def __init__(self, pyweed):
        """
        Initialization.
        """
        super(EventsHandler, self).__init__()
        self.pyweed = pyweed
        self.catalog_loader = None

    def load_catalog(self, request):
        self.catalog_loader = EventsLoader(request)
        self.catalog_loader.done.connect(self.on_catalog_loaded)
        self.catalog_loader.start()

    def on_catalog_loaded(self, event_catalog):
        self.done.emit(event_catalog)

    def cancel(self):
        if self.catalog_loader:
            self.catalog_loader.done.disconnect()
        self.done.emit(CancelledException())


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

if __name__ == '__main__':
    import doctest
    doctest.testmod(exclude_empty=True)
