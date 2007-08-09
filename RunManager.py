#!/usr/bin/env python

import gtk, gobject
import sys, time
from RunWidget import RunWidget

class RunManager(gtk.Notebook):
    def __init__(self):
        gtk.Notebook.__init__(self)       
        self.runs = []
        self.run_labels = []
        self.blank_page = gtk.EventBox()
        self.set_tab_pos(gtk.POS_RIGHT)
        
        self.add_run_btn = gtk.image_new_from_stock('gtk-add',gtk.ICON_SIZE_MENU) 
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
                number =0
                self.runs[0].set_parameters(data)
                return
            else:
                data['number'] = number
                newrun.set_parameters(data)
        self.runs.append(newrun)
        self.run_labels.append( gtk.Label(" %d " % (len(self.runs)-1)) )
        pos = len(self.runs) - 1
        self.insert_page(self.runs[-1], tab_label=self.run_labels[-1], position=pos)
        self.set_current_page( pos )
        self.runs[-1].apply_btn.connect('clicked', self.on_apply_run )
        if len(self.runs) > 1:
            self.runs[-1].delete_btn.connect('clicked', self.on_delete_run )
            
 
    def del_run(self, num):
        if num > 0 and num < len(self.runs):
            self.remove_page(num)
            del self.runs[num]
            del self.run_labels[num]
            for i in range(num,len(self.runs)):
                self.runs[i].set_number(i)
                self.run_labels[i].set_text(" %d " % i)
        if num == len(self.runs):
            num = num-1
        self.set_current_page( num )
        
    def on_apply_run(self, widget):
        num = self.get_current_page()
        self.update_parent(num)
        return True

    
    def on_switch_page(self, notebook, junk, page_num):
        if page_num == len(self.runs):
            self.add_new_run()
            self.emit_stop_by_name('switch-page')
        #else:
        #    self.update_parent(page_num)
        return True 
        
    def on_delete_run(self, widget):
        num = self.get_current_page()
        self.del_run(num)
        self.reset_parent()
    
    def reset_parent(self):
        if self.parent:
            self.parent.clear_runs()
            for run in self.runs:
                self.parent.apply_run()
                          
    def update_parent(self, pos):
        if self.parent:
           self.parent.apply_run()
                
                
                
