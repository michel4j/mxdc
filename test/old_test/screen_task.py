( TASK_MOUNT,
  TASK_ALIGN,
  TASK_PAUSE,
  TASK_COLLECT,
  TASK_ANALYSE ) = range(5)

TASKLET_NAME_MAP = {
    TASK_MOUNT : 'Mount Crystal',
    TASK_ALIGN : 'Align Crystal',
    TASK_PAUSE : 'Pause',
    TASK_COLLECT : 'Collect',
    TASK_ANALYSE : 'Analyse',
}

class Tasklet(object):
    def __init__(self, task_type):
        self.name = TASKLET_NAME_MAP[task_type]
        self.options = {}
        self.task_type = task_type
        
    
    def configure(self, **kwargs):
        for k,v in kwargs.items():
            self.options[k] = v

    def __repr__(self):
        return '<Tasklet: %s>' % self.name
        

if __name__ == '__main__':
    tasks = []
    task_info = [ (TASK_MOUNT, True),
                  (TASK_ALIGN, True),
                  (TASK_PAUSE, False),
                  (TASK_COLLECT, True),
                  (TASK_COLLECT, True),
                  (TASK_COLLECT, False),
                  (TASK_ANALYSE, False),
                  (TASK_PAUSE, False), ]
    for key, sel in task_info:
        t = Tasklet(key)
        t.configure(enabled=sel)
        tasks.append(t)
        
    
    for task in tasks:
        if task.options['enabled']:
            tick = 'x'
        else:
            tick = ' '
        print '[%c]  %s' % (tick, task)
