'''
Created on May 20, 2010

@author: michel
'''

from bcm.utils import xlrd
from bcm.utils.enum import Enum
import os

EXPERIMENT_SHEET_NUM = 1
EXPERIMENT_SHEET_NAME = 'Groups'
EXPERIMENT_NAME = 0
EXPERIMENT_NAME_ERROR = 'Invalid Experiment name "%s" in cell Groups!$A$%d.'
EXPERIMENT_KIND = 1
EXPERIMENT_KIND_ERROR = 'Invalid Experiment type "%s" in cell Groups!$B$%d.'
EXPERIMENT_PLAN = 2
EXPERIMENT_PLAN_ERROR = 'Invalid Experiment plan "%s" in cell Groups!$C$%d.'
EXPERIMENT_PRIORITY = 3
EXPERIMENT_ABSORPTION_EDGE = 4
EXPERIMENT_R_MEAS = 5
EXPERIMENT_R_MEAS_ERROR = 'Invalid Experiment R-factor "%s" in cell Groups!$F$%d.'
EXPERIMENT_I_SIGMA = 6
EXPERIMENT_I_SIGMA_ERROR = 'Invalid Experiment I/Sigma "%s" in cell Groups!$G$%d.'
EXPERIMENT_RESOLUTION = 7
EXPERIMENT_RESOLUTION_ERROR = 'Invalid Experiment resolution "%s" in cell Groups!$H$%d.'

CRYSTAL_SHEET_NUM = 0
CRYSTAL_SHEET_NAME = 'Crystals'
CRYSTAL_NAME = 0
CRYSTAL_NAME_ERROR = 'Invalid Crystal name "%s" in cell Crystals!$A$%d.'
CRYSTAL_EXPERIMENT = 1
CRYSTAL_EXPERIMENT_ERROR = 'Invalid Group/Experiment name "%s" in cell Crystals!$B$%d.'
CRYSTAL_CONTAINER = 2
CRYSTAL_CONTAINER_ERROR = 'Invalid Container name "%s" in cell Crystals!$C$%d.'
CRYSTAL_CONTAINER_KIND = 3
CRYSTAL_CONTAINER_KIND_ERROR = 'Invalid Container kind "%s" in cell Crystals!$D$%d.'
CRYSTAL_CONTAINER_LOCATION = 4
CRYSTAL_CONTAINER_LOCATION_ERROR = 'Invalid Container location "%s" in cell Crystals!$E$%d.'

IGNORE_CONTAINER_WARNING = 'Ignoring incompatible container "%s" of type "%s".'

CRYSTAL_PRIORITY = 5
CRYSTAL_COCKTAIL = 6
CRYSTAL_COMMENTS = 7

PLAN_SHEET_NUM = 2
PLAN_SHEET_NAME = 'Plans'


CONTAINER_TYPE = Enum(
        'Cassette', 
        'Uni-Puck', 
        'Cane', 
        'Basket', 
        'Carousel',)

def port_is_valid(container, loc):
    if container['type'] == 'CASSETTE':
        all_positions = ["ABCDEFGHIJKL"[x/8]+str(1+x%8) for x in range(96) ]
    elif container['type'] == 'UNI-PUCK':
        all_positions = [ str(x+1) for x in range(16) ]
    return loc in all_positions
    
    
class SamplesDatabase(object):
    """ A wrapper for an Excel shipment/experiment spreadsheet """
    
    def __init__(self, xls):
        """ Reads the xls file into a xlrd.Book wrapper 
        
        @param xls: the filename of an Excel file
        @param project: a Project instance  
        """
        self.xls = xls
        self.project = {'id': os.getuid(), 'name': os.getlogin()}
        self.errors = []
        self.warnings = []
        self._read_xls()
        
    def _read_xls(self):
        """ Reads the data from the xlrd.Book wrapper """
        if hasattr(self, 'book'):
            return
        
        try:
            self.book = xlrd.open_workbook(self.xls)
        except xlrd.XLRDError:
            self.errors.append('Invalid Excel spreadsheet.')
            return
        
        self.experiments_sheet = self.book.sheet_by_name(EXPERIMENT_SHEET_NAME)
        self.crystals_sheet = self.book.sheet_by_name(CRYSTAL_SHEET_NAME)
        
        self.experiments = self._get_experiments()
        self.containers = self._get_containers()
        self.crystals = self._get_crystals()
                
    def _get_containers(self):
        """ Returns a dict of {'name' : Container} from the Excel file 
        
        @return: dict of {'name' : Container}
        """
        containers = {}
        for row_num in range(1, self.crystals_sheet.nrows):
            row_values = self.crystals_sheet.row_values(row_num)
            if row_values[CRYSTAL_CONTAINER]:
                # only load cassettes and Uni-pucks for mxdc
                if row_values[CRYSTAL_CONTAINER] not in containers:
                    container = {}
                    
                    if row_values[CRYSTAL_CONTAINER]:
                        container['name'] = row_values[CRYSTAL_CONTAINER]
                    else:
                        self.errors.append(CRYSTAL_CONTAINER_ERROR % (row_values[CRYSTAL_CONTAINER], row_num))
                    
                    if row_values[CRYSTAL_CONTAINER_KIND]:
                        container['type'] = row_values[CRYSTAL_CONTAINER_KIND].upper() # validated by Excel
                    else:
                        self.errors.append(CRYSTAL_CONTAINER_KIND_ERROR % (row_values[CRYSTAL_CONTAINER_KIND], row_num))
                    container['comments'] = ''
                    if container['type'] in ['CASSETTE', 'UNI-PUCK']:
                        containers[ container['name'] ] = container
                    else:
                        self.warnings.append(IGNORE_CONTAINER_WARNING % (container['name'], container['type']))
                    
                # a bit more validation to ensure that the Container 'kind' does not change
                else:
                    container = containers[row_values[CRYSTAL_CONTAINER]]
                    
                    if row_values[CRYSTAL_CONTAINER_KIND]:
                        kind = row_values[CRYSTAL_CONTAINER_KIND].upper() # validated by Excel
                        if kind != container['type']:
                            self.errors.append(CRYSTAL_CONTAINER_KIND_ERROR % (row_values[CRYSTAL_CONTAINER_KIND], row_num))
                    else:
                        self.errors.append(CRYSTAL_CONTAINER_KIND_ERROR % (row_values[CRYSTAL_CONTAINER_KIND], row_num))
                    
        return containers
    
    
    def _get_experiments(self):
        """ Returns a dict of {'name' : Experiment} from the Excel file 
        
        @return: dict of {'name' : Experiment}
        """
        experiments = {}
        for row_num in range(1, self.experiments_sheet.nrows):
            row_values = self.experiments_sheet.row_values(row_num)
            experiment = {}
            
            if row_values[EXPERIMENT_NAME]:
                experiment['name'] = row_values[EXPERIMENT_NAME]
            else:
                self.errors.append(EXPERIMENT_NAME_ERROR % (row_values[EXPERIMENT_NAME], row_num))
                
            if row_values[EXPERIMENT_KIND]:
                experiment['type'] = row_values[EXPERIMENT_KIND] # validated by Excel
            else:
                self.errors.append(EXPERIMENT_KIND_ERROR % (row_values[EXPERIMENT_KIND], row_num))
                
            if row_values[EXPERIMENT_PLAN]:
                experiment['plan'] = row_values[EXPERIMENT_PLAN] # validated by Excel
            else:
                self.errors.append(EXPERIMENT_PLAN_ERROR % (row_values[EXPERIMENT_PLAN], row_num))
                
            if row_values[EXPERIMENT_ABSORPTION_EDGE]:
                experiment['absorption_edge'] = row_values[EXPERIMENT_ABSORPTION_EDGE]
                
            if row_values[EXPERIMENT_R_MEAS]:
                experiment['r_meas'] = row_values[EXPERIMENT_R_MEAS]
            else:
                self.errors.append(EXPERIMENT_R_MEAS_ERROR % (row_values[EXPERIMENT_R_MEAS], row_num))
                
            if row_values[EXPERIMENT_I_SIGMA]:
                experiment['i_sigma'] = row_values[EXPERIMENT_I_SIGMA]
            else:
                self.errors.append(EXPERIMENT_I_SIGMA_ERROR % (row_values[EXPERIMENT_I_SIGMA], row_num))
                
            if row_values[EXPERIMENT_RESOLUTION]:
                experiment['resolution'] = row_values[EXPERIMENT_RESOLUTION]
            else:
                self.errors.append(EXPERIMENT_RESOLUTION_ERROR % (row_values[EXPERIMENT_RESOLUTION], row_num))
                
            experiments[experiment['name']] = experiment
        return experiments
    
    def _get_crystals(self):
        """ Returns a dict of {'name' : Crystal} from the Excel file 
        
        @return: dict of {'name' : Crystal}
        """
        crystals = {}
        for row_num in range(1, self.crystals_sheet.nrows):
            row_values = self.crystals_sheet.row_values(row_num)
            crystal = {}
            
            if row_values[CRYSTAL_NAME]:
                crystal['name'] = row_values[CRYSTAL_NAME]
            else:
                self.errors.append(CRYSTAL_NAME_ERROR % (row_values[CRYSTAL_NAME], row_num))
                
            crystal['experiment'] = None
            if row_values[CRYSTAL_EXPERIMENT] and row_values[CRYSTAL_EXPERIMENT] in self.experiments:
                # patch the reference - it will be put in the Experiment in .save()
                crystal['experiment'] = self.experiments[row_values[CRYSTAL_EXPERIMENT]]
            else:
                self.errors.append(CRYSTAL_EXPERIMENT_ERROR % (row_values[CRYSTAL_EXPERIMENT], row_num))
            
            #skip for ignored containers
            if not(row_values[CRYSTAL_CONTAINER] in self.containers):
                continue
            
            if row_values[CRYSTAL_CONTAINER] and row_values[CRYSTAL_CONTAINER] in self.containers:
                crystal['container'] = row_values[CRYSTAL_CONTAINER]
            else:
                self.errors.append(CRYSTAL_CONTAINER_ERROR % (row_values[CRYSTAL_CONTAINER], row_num))
                
            if row_values[CRYSTAL_CONTAINER_LOCATION]:
                # xlrd is doing some auto-conversion to floats regardless of the Excel field type
                try:
                    crystal['port'] = str(int(row_values[CRYSTAL_CONTAINER_LOCATION]))
                except ValueError:
                    crystal['port'] = row_values[CRYSTAL_CONTAINER_LOCATION].strip()
            else:
                self.errors.append(CRYSTAL_CONTAINER_LOCATION_ERROR % (row_values[CRYSTAL_CONTAINER_LOCATION], row_num))
                
            # sanity check on container_location
            if crystal['container']:
                if not port_is_valid(self.containers[crystal['container']], crystal['port']):
                    self.errors.append(CRYSTAL_CONTAINER_LOCATION_ERROR % (row_values[CRYSTAL_CONTAINER_LOCATION], row_num))
                
                
            if row_values[CRYSTAL_COMMENTS]:
                crystal['comments'] = row_values[CRYSTAL_COMMENTS]
            else:
                crystal['comments'] = ''
            crystal['barcode'] = ''    
            crystals[crystal['name']] = crystal
        return crystals
    
    def is_valid(self):
        """ Returns True if the spreadsheet has no validation errors, and False otherwise 
        
        @return: True if the spreadsheet has no validation errors, and False otherwise
        """
        self._read_xls()
        return not bool(self.errors)
    