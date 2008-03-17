from bcm.protocols import ca

class QBPM:
    def __init__(self, A, B, C, D):
        self.A = ca.PV(A)
        self.B = ca.PV(B)
        self.C = ca.PV(C)
        self.D = ca.PV(D)
        self.x_factor = 1.0
        self.y_factor = 1.0
        self.x_offset = 0.0
        self.y_offset = 0.0

    def set_factors(self, xf=1, yf=1):
        self.x_factor = xf
        self.y_factor = yf
    
    def set_offsets(self, xoff=0, yoff=0):
        self.x_offset = xoff
        self.y_offset = yoff

    def get_position(self):
        a = self.A.get()
        b= self.B.get()
        c = self.C.get()
        d = self.D.get()
        sumy = (a + b) - self.y_offset
        sumx = (c + d) - self.x_offset
        if sumy == 0.0:
            sumy = 1.0e-10
        if sumx == 0.0:
            sumx = 1.0e-10
        y = self.y_factor * (a - b) / sumy
        x = self.x_factor * (c - d) / sumx
        return [x, y]
    
    def sum(self):
        a, b, c, d = self.A.get(), self.B.get(), self.C.get(), self.D.get()
        return a + b + c + d
