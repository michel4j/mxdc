from bcm.tools.scanning import scan, rscan

def _find_and_optimize(pos, det):
    #Wide scan to find beam
    scan(pos, -5., 5., 30, det, 0.25)
    if scan.midp_fit:
        pos.move_to(scan.midp_fit)
    else:
        pos.move_to(scan.xpeak)
    
    # fine relative scan around beam
    rscan(pos, -1.5, 1.5, 20, det, 0.5)
    pos.move_to(rscan.midp_fit)
    
    # fine relative scan around beam
    rscan(pos, -0.5, 0.5, 15, det, 0.5)
    pos.move_to(rscan.midp_fit)

    
def optimize_linac(bl):
    for pos, det in [(bl.h1, bl.i1),(bl.h2, bl.i2),(bl.h3, bl.i3), (bl.h4,bl.i4), (bl.h5,bl.i5)]:
        _find_and_optimize(pos, det)

