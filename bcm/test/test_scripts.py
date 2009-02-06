from bcm import ibcm
import bcm.scripts
from twisted.plugin import getPlugins

if __name__ == '__main__':
    for script in getPlugins(ibcm.IScript, bcm.scripts):
        print script