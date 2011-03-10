import gtk, gobject
import sys, time
from mxdc.widgets.runwidget import RunWidget

class RunManager(gtk.Notebook):
    __gsignals__ = {
        'saved' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'del-run' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
    }
    def __init__(self):
        gtk.Notebook.__init__(self)
        self.runs = []
        self.run_labels = []
        self.blank_page = gtk.EventBox()
        self.set_tab_pos(gtk.POS_RIGHT)
        
        self.add_run_btn = gtk.image_new_from_stock('gtk-add', gtk.ICON_SIZE_MENU) 
        self.add_run_btn.show()
        self.append_page(self.blank_page, tab_label=self.add_run_btn)
        self.add_new_run()
        self.show_all()
        self.connect('switch-page', self.on_switch_page)
        
    def add_new_run(self, data=None):
        number = len(self.runs)
        newrun = RunWidget(num=number)
        if data:
            if data['number'] == 0:
                number = 0
                self.runs[0].set_parameters(data)
                return
            else:
                data['number'] = number
                newrun.set_parameters(data)
        else:
            if number > 0:
                data = self.runs[number - 1].get_parameters()
                data['number'] = number
                data['skip'] = ''
                data['wedge'] = 360
                data['two_theta'] = 0.0
                data['inverse_beam'] = False
                newrun.set_parameters(data)
        self.runs.append(newrun)
        self.run_labels.append(gtk.Label(" %d " % (len(self.runs) - 1)))
        pos = len(self.runs) - 1
        self.insert_page(self.runs[-1], tab_label=self.run_labels[-1], position=pos)
        self.set_current_page(pos)
        self.runs[-1].save_btn.connect('clicked', self.on_save)
        if len(self.runs) > 1:
            self.runs[-1].delete_btn.connect('clicked', self.on_delete_run)
            
 
    def del_run(self, num):
        if num > 0 and num < len(self.runs):
            self.remove_page(num)
            del self.runs[num]
            del self.run_labels[num]
            for i in range(num, len(self.runs)):
                self.runs[i].set_number(i)
                self.run_labels[i].set_text(" %d " % i)
        if num == len(self.runs):
            num = num - 1
        self.set_current_page(num)
    
    def update_sample(self, data):
        for run in self.runs:
            run.update_sample(data)
            
    def on_save(self, widget):
        self.emit('saved')
        return True
    
    def on_switch_page(self, notebook, junk, page_num):
        if page_num == len(self.runs):
            self.add_new_run()
            self.emit_stop_by_name('switch-page')
        return True 
        
    def on_delete_run(self, widget):
        num = self.get_current_page()
        self.del_run(num)
        self.emit('del-run', num)
        
                              
gobject.type_register(RunManager)
                
            
