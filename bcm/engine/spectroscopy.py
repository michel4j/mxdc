class ExcitationScanner(ScannerBase):
    def __init__(self, beamline):
        ScannerBase.__init__(self)
        self.peaks = []
        self.beamline = beamline
    
    def setup(self, time=1.0, output=None):
        self.time = time
        self.filename = output
                        
    def run(self):
        ca.threads_init()
        scan_logger.debug('Exitation Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        scan_logger.debug('Exitation Scan started')
        gobject.idle_add(self.emit, 'started')
       
        try:
            self.beamline.shutter.open()
            if not self.beamline.mca.is_cool():
                self.beamline.mca.set_cooling(True)
            self.beamline.mca.set_channel_roi()
            self.x_data_points, self.y_data_points = self.beamline.mca.acquire(t=self.time)
            self.beamline.shutter.close()
            #self.peaks = find_peaks(self.x_data_points, self.y_data_points, threshold=0.3,w=20)
            #assign_peaks(self.peaks)
            self.save()
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0 )
        except:
            scan_logger.error('There was an error running the Excitation Scan.')
            self.beamline.shutter.close()
            gobject.idle_add(self.emit, "error")
            gobject.idle_add(self.emit, "progress", 1.0 )
            self.beamline.lock.release()
            raise
        self.beamline.lock.release()    
            

    def save(self, filename = None):
        if filename:
            self.filename = filename
        scan_data  = "# Positioner: %s \n" % self.beamline.energy.get_name()
        scan_data += "# Detector: %s \n" % self.beamline.mca.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.beamline.energy.get_name(), self.beamline.mca.get_name())
        for x,y in zip(self.x_data_points, self.y_data_points):
            scan_data += "%15.8g %15.8g \n" % (x, y)
        #scan_data += '# Peak Assignments'
        #for peak in self.peaks:
        #    peak_log = "#Peak position: %8.3f keV  Height: %8.2f" % (peak[0],peak[1])
        #    for ident in peak[2:]:
        #        peak_log = "%s \n%s" % (peak_log, ident)
        #    scan_data += peak_log

        if self.filename != None:
            try:
                scan_file = open(self.filename,'w')        
                scan_file.write(scan_data)
                scan_file.flush()
                scan_file.close()
            except:
                scan_logger.error('Unable to saving Scan data to "%s".' % (self.filename,))
                print scan_data
        else:
            print scan_data

class MADScanner(ScannerBase):
    def __init__(self, beamline):
        ScannerBase.__init__(self)
        self.beamline = beamline
        self.factor = 1.0
        self._energy_db = get_energy_database()
    
    def setup(self, edge, count_time, output):
        en, em = self._energy_db[edge]
        self.energy = en
        self.emission = em
        self.time = count_time
        self.filename = output
        scan_logger.info('Edge Scan setup for %s, %0.2f sec exposures, output file "%s".' % (edge, count_time, output))
        
    def calc_targets(self):
        energy = self.energy
        very_low_start = energy - 0.2
        very_low_end = energy - 0.17
        low_start = energy -0.15
        low_end = energy -0.03
        mid_start = low_end
        mid_end = energy + 0.03
        hi_start = mid_end + 0.0015
        hi_end = energy + 0.16
        very_hi_start = energy + 0.18
        very_hi_end = energy + 0.21

        targets = []
        # Add very low points
        targets.append(very_low_start)
        targets.append(very_low_end)
        
        # Decreasing step size for the beginning
        step_size = 0.02
        val = low_start
        while val < low_end:
            targets.append(val)
            step_size -= 0.0015
            val += step_size

        # Fixed step_size for the middle
        val = mid_start
        step_size = 0.001
        while val < mid_end:
            targets.append(val)
            val += step_size
            
        # Increasing step size for the end
        step_size = 0.002
        val = hi_start
        while val < hi_end:
            targets.append(val)
            step_size += 0.0015
            val += step_size
            
        # Add very hi points
        targets.append(very_hi_start)
        targets.append(very_hi_end)
            
        self.energy_targets = targets

    def run(self):
        ca.threads_init()
        self.stopped = False
        self.aborted = False
        self.x_data_points = []
        self.y_data_points = []
        self.calc_targets()
        
        scan_logger.info('Edge Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        scan_logger.info('Edge Scan started.')
        gobject.idle_add(self.emit, 'started')

        try:
            self.beamline.mca.set_energy(self.emission)

            if not self.beamline.mca.is_cool():
                self.beamline.mca.set_cooling(True)
            self.beamline.energy.move_to(self.energy, wait=True)   
                   
            self.count = 0
            self.beamline.shutter.open()
            self.beamline.mca.erase()
            scan_logger.info("%4s %15s %15s %15s" % ('#', 'Energy', 'Counts', 'Scale Factor'))
            for x in self.energy_targets:
                if self.stopped or self.aborted:
                    scan_logger.info('Edge Scan stopped.')
                    break
                    
                self.count += 1
                prev = self.beamline.bragg_energy.get_position()                
                self.beamline.bragg_energy.move_to(x, wait=True)
                if self.count == 1:
                    self.first_intensity = (self.beamline.i0.count(0.5) * 1e9)
                    self.factor = 1.0
                else:
                    self.factor = self.first_intensity/(self.beamline.i0.count(0.5)*1e9)
                y = self.beamline.mca.count(self.time)
                    
                y = y * self.factor
                self.x_data_points.append( x )
                self.y_data_points.append( y )
                
                fraction = float(self.count) / len(self.energy_targets)
                scan_logger.info("%4d %15g %15g %15g" % (self.count, x, y, self.factor))
                gobject.idle_add(self.emit, "new-point", x, y )
                gobject.idle_add(self.emit, "progress", fraction )
                 
            self.beamline.shutter.close()
            
            if self.aborted:
                scan_logger.warning("Edge Scan aborted.")
                gobject.idle_add(self.emit, "aborted")
                gobject.idle_add(self.emit, "progress", 0.0 )
            else:
                self.save()
                gobject.idle_add(self.emit, "done")
                gobject.idle_add(self.emit, "progress", 1.0 )
        except:
            scan_logger.error("An error occurred during the scan. Edge Scan aborted.")
            self.beamline.shutter.close()
            self.beamline.lock.release()
            gobject.idle_add(self.emit, "aborted")
            gobject.idle_add(self.emit, "progress", 0.0 )
            raise
        self.beamline.lock.release()
        

    def save(self, filename=None):
        if filename:
            self.set_output(filename)
        scan_data  = "# Positioner: %s \n" % self.beamline.bragg_energy.get_name()
        scan_data += "# Detector: %s \n" % self.beamline.mca.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.beamline.bragg_energy.get_name(), self.beamline.mca.get_name())
        for x,y in zip(self.x_data_points, self.y_data_points):
            scan_data += "%15.8g %15.8g \n" % (x, y)

        if self.filename != None:
            try:
                scan_file = open(self.filename,'w')        
                scan_file.write(scan_data)
                scan_file.flush()
                scan_file.close()
            except:
                scan_logger.error('Unable to saving Scan data to "%s".' % (self.filename,))
      

def emissions_list():
    table_data = read_periodic_table()
    emissions = {
            'K':  'Ka',
            'L1': 'Lg2',
            'L2': 'Lb2',
            'L3': 'Lb1'
    }
    emissions_dict = {}
    for key in table_data.keys():
        for line in emissions.values():
            emissions_dict["%s-%s" % (key,line)] = float(table_data[key][line])
    return emissions_dict

def get_energy_database():
    table_data = read_periodic_table()
    emissions = {
            'K':  'Ka',
            'L1': 'Lg2',
            'L2': 'Lb2',
            'L3': 'Lb1'
    }
    data_dict = {}
    for key in table_data.keys():
            for edge in emissions.keys():
                val = float(table_data[key][edge])
                e_val = float(table_data[key][ emissions[edge] ])
                data_dict["%s-%s" % (key,edge)] = (val, e_val)
    return data_dict

def assign_peaks(peaks):
    stdev = 0.01 #kev
    data = emissions_list()
    for peak in peaks:
        hits = []
        for key in data.keys():
            value = data[key]
            if value == 0.0:
                continue
            score = abs(value - peak[0])/ (2.0 * stdev)
            if abs(value - peak[0]) < 2.0 * stdev:
                hits.append( (score, key, value) )
            hits.sort()
        for score, key,value in hits:
            peak.append("%8s : %8.4f (%8.5f)" % (key,value, score))
    return peaks

def find_peaks(x, y, w=10, threshold=0.1):
    peaks = []
    ys = smooth(y,w,1)
    ny = correct_baseline(x,ys)
    yp = slopes(x, ny)
    ypp = slopes(x, yp)
    yr = max(y) - min(y)
    factor = threshold*get_baseline(x,y).std()
    offset = 1+w/2
    for i in range(offset+1, len(x)-offset):
        p_sect = scipy.mean(yp[(i-offset):(i+offset)])
        sect = scipy.mean(yp[(i+1-offset):(i+1+offset)])
        #if scipy.sign(yp[i]) < scipy.sign(yp[i-1]):
        if scipy.sign(sect) < scipy.sign(p_sect):
            if ny[i] > factor:
                peaks.append( [x[i], ys[i]] )
    return peaks
