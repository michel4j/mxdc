from matplotlib import cm, colors
import numpy
from scipy import interpolate


def cmap_discretize(cmap_name="spectral", N=10):
    """Return a discrete colormap from the continuous colormap cmap.
    
        cmap: colormap name
        N: Number of colors.
    
    Example
        x = resize(arange(100), (5,100))
        djet = cmap_discretize(cm.jet, 5)
        imshow(x, cmap=djet)
    """
    cmap = cm.get_cmap(cmap_name)
    
    cdict = cmap._segmentdata.copy()
    # N colors
    colors_i = numpy.linspace(0,1.,N)
    # N+1 indices
    indices = numpy.linspace(0,1.,N+1)
    for key in ('red','green','blue'):
        # Find the N colors
        D = numpy.array(cdict[key])
        I = interpolate.interp1d(D[:,0], D[:,1])
        colrs = I(colors_i)
        # Place these colors at the correct indices.
        A = numpy.zeros((N+1,3), float)
        A[:,0] = indices
        A[1:,1] = colrs
        A[:-1,2] = colrs
        # Create a tuple for the dictionary.
        L = []
        for l in A:
            L.append(tuple(l))
        cdict[key] = tuple(L)
    # Return colormap object.
    return colors.LinearSegmentedColormap('colormap',cdict,1024)

class ColorMapper(object):
    def __init__(self, color_map="jet", min_val=-0.5, max_val=1.0):
        self.cmap =  cm.get_cmap(color_map)
        self.norm = colors.Normalize(vmin=min_val, vmax=max_val)
    
    def autoscale(self, values):
        self.norm.autoscale(values)
         
    def rgb_values(self, val):
        return self.rgba_values(val)[:3]

    def rgba_values(self, val):
        return self.cmap(self.norm(val))

    def rgba(self, val):
        red, green, blue, alpha = self.rgba_values(val)
        return {'red': red, 'green': green, 'blue': blue, 'alpha': alpha}

    def rgb(self, val):
        red, green, blue, alpha = self.rgba_values(val)
        return {'red': red, 'green': green, 'blue': blue}

    def get_hex(self, val):
        R,G,B = self.rgb_values(val)
        R,G,B = int(round(255*R)), int(round(255*G)), int(round(255*B))
        return ("#%02x%02x%02x" % (R,G,B)).upper()
        

PERCENT_COLORMAP = ColorMapper(color_map='jet', min_val=10, max_val=90)
FRACTION_COLORMAP = ColorMapper(color_map='jet', min_val=0.1, max_val=0.9)
