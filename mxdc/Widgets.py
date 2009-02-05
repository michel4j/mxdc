    
def main():
    win = gtk.Window()
    #win.set_default_size(150,250)
    win.set_border_width(0)
    vbox = gtk.VBox(True,0)
    win.add(vbox)
    g = Gauge(0, 100, 5, 3)
    g2 = Gauge(0, 10, 5, 3)
    g.set_property('low',20)
    g.set_property('high',95)
    g2.set_property('digits',1)
    g.set_property('units','%')
    g2.set_property('units','rpm')
    g2.show_all()
    vbox.pack_start(g, expand=True, fill=True)
    vbox.pack_start(g2, expand=True, fill=True)  
    def mv(g):
        g.value += 0.1
        g.show()
        return True
        
    gobject.timeout_add(10, mv, g)
    gobject.timeout_add(100,mv, g2)
    win.show_all()
    win.connect("destroy", gtk.main_quit)

    gtk.main()

if __name__ == "__main__":
    main()
