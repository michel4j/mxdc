from bcm import ibcm
import bcm.scripts
from twisted.plugin import getPlugins
from bcm.utils.log import log_to_console
log_to_console()

if __name__ == '__main__':
    for script in getPlugins(ibcm.IScript, bcm.scripts):
        print script