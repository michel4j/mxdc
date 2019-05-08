from matplotlib import cm, colors
from . import cmaps
import numpy
from scipy import interpolate

from mxdc.utils.misc import _COLOR_PATTERN


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


class Category:
    WIKI = [
        "#ff9999","#ff99ff","#9999ff","#cc99ff", "#99ccff","#99ffff","#99ff99","#ccff99",
            "#ffcc99","#ff6666", "#cccccc", "#ffff99"
    ]
    CAT20C = [
        "#3182bd", "#6baed6", "#9ecae1", "#c6dbef", "#e6550d", "#fd8d3c", "#fdae6b", "#fdd0a2",
        "#31a354", "#74c476","#a1d99b", "#c7e9c0", "#756bb1", "#9e9ac8", "#bcbddc", "#dadaeb",
        "#636363", "#969696", "#bdbdbd", "#d9d9d9"
    ]
    CAT20 = [
        "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a", "#d62728", "#ff9896",
        "#9467bd", "#c5b0d5", "#8c564b", "#c49c94", "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7",
        "#bcbd22", "#dbdb8d", "#17becf", "#9edae5"
    ]
    CAT16C = [
        "#aec7e8", "#ff7f0e", "#ffbb78", "#98df8a", "#d62728", "#ff9896",
        "#c5b0d5", "#8c564b", "#c49c94", "#f7b6d2", "#7f7f7f", "#c7c7c7",
        "#dbdb8d", "#17becf", "#9edae5"
    ]
    CAT20B = [
        "#393b79", "#5254a3", "#6b6ecf", "#9c9ede", "#637939", "#8ca252", "#b5cf6b", "#cedb9c", "#8c6d31", "#bd9e39",
        "#e7ba52", "#e7cb94", "#843c39", "#ad494a", "#d6616b", "#e7969c", "#7b4173", "#a55194", "#ce6dbd", "#de9ed6"
    ]
    GOOG20 = [
        "#3366cc", "#dc3912", "#ff9900", "#109618", "#990099", "#0099c6", "#dd4477", "#66aa00", "#b82e2e",
        "#316395", "#994499", "#22aa99", "#aaaa11", "#6633cc", "#e67300", "#8b0707", "#651067", "#329262", "#5574a6", "#3b3eac"
    ]
    EDGES = [
        "#de7878","#de78de","#7878de","#ab78de", "#7899de","#78dede","#78de78","#abde78",
        "#deab78","#de4545", "#ababab", "#dede78"
    ]
    CAT10 = ['#17becf', '#bcbd22', '#7f7f7f', '#e377c2', '#8c564b', '#9467bd', '#d62728', '#2ca02c', '#ff7f0e', '#1f77b4']


class ColorMapper(object):
    def __init__(self, color_map=cmaps.viridis, min_val=0, max_val=1.0):
        self.cmap =  cm.get_cmap(color_map)
        self.norm = colors.Normalize(vmin=min_val, vmax=max_val)

    def autoscale(self, values):
        if len(values) > 1:
            self.norm = colors.Normalize(vmin=min(values), vmax=max(values))
            #self.norm.autoscale(values)
         
    def rgb_values(self, val):
        return self.rgba_values(val)[:3]

    def rgba_values(self, val, alpha=1.0):
        val = 0.0 if val is None else val
        values = self.cmap(self.norm(val))
        return values[0], values[1], values[2], values[3]*alpha

    def rgba(self, val, alpha=1.0):
        red, green, blue, a = self.rgba_values(val, alpha=alpha)
        return {'red': red, 'green': green, 'blue': blue, 'alpha': alpha}

    def rgb(self, val):
        red, green, blue, alpha = self.rgba_values(val)
        return {'red': red, 'green': green, 'blue': blue}

    def get_hex(self, val):
        R,G,B = self.rgb_values(val)
        R,G,B = int(round(255*R)), int(round(255*G)), int(round(255*B))
        return ("#%02x%02x%02x" % (R,G,B)).upper()
        

PERCENT_COLORMAP = ColorMapper(min_val=10, max_val=90)
FRACTION_COLORMAP = ColorMapper(min_val=0.1, max_val=0.9)


def lighten_color(s, step=51):
    R, G, B = [min(max(int('0x' + v, 0) + step, 0), 255) for v in _COLOR_PATTERN.match(s.upper()).groups()]
    return "#%02x%02x%02x" % (R, G, B)

