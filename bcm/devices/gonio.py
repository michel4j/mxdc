
class Gonio:
    def __init__(self, name):
        #house_keeping
        self.name = name
        self.scan_cmd = PV("%s:scanFrame.PROC" % name)

        #Status parameters
        self.state = PV("%s:scanFrame:status" % name)
        self.shutter_state = PV("%s:outp1:fbk" % name)
        self.move_state = PV("%s:moving" % name)
        self.active = False
        
        #parameters
        self.params = {
            'time' : PV("%s:expTime" % name),
            'delta' : PV("%s:deltaOmega" % name),
            'start_angle': PV("%s:openSHPos" % name),
        }
                
    def set_params(self, data):
        self.param_vals = data
        for key in data.keys():
            self.params[key].put(data[key])
            #print key, data[key]
    
    def scan(self, wait=True):
        self.scan_cmd.put('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def shutter_is_open(self):
        return self.shutter_state.get() != 0

    def is_active(self):
        return self.state.get() != 0        
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            #print 'waiting for shutter to open'
            while not self.is_active() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            #print 'waiting gonio to stop'
            while self.is_active() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
    
 