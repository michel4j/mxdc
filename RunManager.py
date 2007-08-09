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
        self.runs.append(newrun)
        if data:
            data['number'] = number
            self.runs[number].set_parameters(data)
        self.run_labels.append( gtk.Label(" %d " % (len(self.runs)-1)) )
        pos = len(self.runs) - 1
        self.insert_page(self.runs[-1], tab_label=self.run_labels[-1], position=pos)
        self.set_current_page( pos )
        if len(self.runs) > 1:
            self.runs[-1].apply_btn.connect('clicked', self.on_apply_run )
            self.runs[-1].delete_btn.connect('clicked', self.on_delete_run )
        else:
            self.runs[-1].apply_btn.connect('clicked', self.on_apply_single_run )
        self.update_parent()
            
 
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
        if num == 0:
            self.update_parent_single()
        else:
            self.update_parent()
        
    def on_apply_run(self, widget):
        pos = self.get_current_page()
        if pos == 0:
            self.update_parent_single()
        else:
            self.update_parent(pos)
        return True

    def on_apply_single_run(self, widget):
        self.update_parent_single()
        return True        
    
    def on_switch_page(self, notebook, junk, page_num):
        if page_num == len(self.runs):
            self.add_new_run()
            self.emit_stop_by_name('switch-page')
        elif page_num == 0:
            self.update_parent_single()
        else:
            self.update_parent()
        return True 
        
    def on_delete_run(self, widget):
        num = self.get_current_page()
        self.del_run(num)
    
    def update_parent_single(self):
        if self.parent:
            self.parent.clear_runs()
            self.parent.apply_run(self.runs[0].get_parameters())
        
    def update_parent(self, pos=0):
        if self.parent:
            self.parent.clear_runs()
            for run in self.runs[1:]:
                self.parent.apply_run(run.get_parameters())
