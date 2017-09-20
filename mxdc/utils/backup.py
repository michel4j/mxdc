#!/usr/bin/env python
import os, sys, time
try:
    import json
except:
    import simplejson as json
        
import logging
import logging.handlers
import commands

if __name__ == '__main__':
    confdir = os.path.join(os.environ.get('MXDC_PATH'), 'etc')

    # Setup the logger
    _logger = logging.getLogger('backup')
    logger.setLevel(logging.DEBUG)
    logfilename = '/var/log/backup.log'
    logfile = logging.handlers.RotatingFileHandler(logfilename, maxBytes=1048576, backupCount=5)
    logfile.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
    logfile.setFormatter(formatter)
    logging.getLogger('').addHandler(logfile)

    # Read Config files
    try:
        sources = json.loads(file(os.path.join(confdir, "backup-sources.conf")).read())
        config = json.loads(file(os.path.join(confdir, "backup.conf")).read())
    except:
        logger.exception("Backup Failed! Could not read configuration files.")
        sys.exit()
            
    # Initialize time variables and options
    today      = time.strftime('%A')
    todaydate  = time.strftime('%Y-%m-%d')
    thisweek   = time.strftime('%V')
    yesterday  = time.strftime('%A', time.localtime(time.time() - 24*60*60) )
    backupdir =  config.get('backupdir')
    backupuser = config.get('backupuser')
    timeout_interval = config.get('timeout_interval')
    exclude_file = config.get('excludes_file')
    
    rsync_opts = "-e 'ssh -ax' -az --numeric-ids --timeout=%s --delete --exclude-from=%s/%s" % ( timeout_interval, backupdir, exclude_file)
    rsync_opts_local = "-az --numeric-ids --timeout=%s --delete --exclude-from=%s/%s" % ( timeout_interval, backupdir, exclude_file)

    # Check if excludes file exists, otherwise create a blank file
    if  not os.path.exists("%s/%s" % (backupdir, exclude_file)):
        sts, out = commands.getstatusoutput('/bin/touch %s/%s' % (backupdir, exclude_file))
        logger.info('Created `excludes` file. Edit it to specify which files should not be backed-up.')
    
    # and perform the backups one client at a time
    backup_sources = sources.get('hosts',{})
    backup_sources['global'] = sources.get('global',[])
    for host, directories in backup_sources.items():
        logger.info('Performing the backups for %s' % host)
        success = False
        todays_dir = os.path.join(backupdir, host, today)
        yesterdays_dir = os.path.join(backupdir, host, yesterday)
        thisweeks_dir = os.path.join(backupdir, host, 'Week-%s' % thisweek)
        
        # Step 1:  Save previous backup as backup for this week if it exists
        logger.info('Save previous backup as backup for this week if it exists')
        if os.path.exists(todays_dir):
            cmd1 = '/bin/rm -rf %s' % (thisweeks_dir)
            cmd2 = "/bin/mv %s %s" % (todays_dir, thisweeks_dir)
            logger.info('Removing %s' % thisweeks_dir)
            sts, out = commands.getstatusoutput(cmd1)
            logger.info('Copying %s to %s' % (todays_dir, thisweeks_dir))
            sts, out = commands.getstatusoutput(cmd2)
    
        # Step 2: Copy yesterdays backup into todays directory before updating it
        logger.info('Copy yesterdays backup into todays directory before updating it')
        if os.path.exists(yesterdays_dir):
            cmd = '/bin/cp -apl %s %s' % (yesterdays_dir, todays_dir)
            logger.info(' - Copying %s to %s' % (yesterdays_dir, todays_dir))
            sts, out = commands.getstatusoutput(cmd)
        else:
            cmd = '/bin/mkdir -p %s' % (todays_dir)
            logger.info(' - Creating missing directory %s' % (todays_dir))
            sts, out = commands.getstatusoutput(cmd)
    
        # Step 3: rsync from system into today's snapshot directory
        for directory in directories:
            logger.info("rsync from system into today's snapshot directory")
            dir_backup_loc = os.path.join(todays_dir, os.path.sep.join(directory.split(os.path.sep)[1:]))
            if host == 'global':
                command_subst = (rsync_opts_local, directory, dir_backup_loc)
                rsync_cmd = "rsync %s %s/ %s" % (command_subst)
            else:
                command_subst = (rsync_opts, backupuser, host, directory, dir_backup_loc)
                rsync_cmd = "rsync %s  %s@%s:%s/ %s" % (command_subst)
            if not os.path.exists(dir_backup_loc):
                cmd = 'mkdir -p %s' % (dir_backup_loc)
                logger.info(' - Updating %s' % (dir_backup_loc))
                sts, out = commands.getstatusoutput(cmd)
                
            #print rsync_cmd
            sts, out = commands.getstatusoutput(rsync_cmd)
            success = (sts == 0)
                 
            if success: 
                logger.info("%s Backing up %s on %s ... succeeded." % (todaydate, directory, host))
            else:
                logger.error("%s Backing up %s on %s ... failed." % (todaydate, directory, host))
                if out.strip() != "":
                    logger.error(out)
                
        # Step 4: Update the time on todays backup to reflect the snapshot time
        cmd = "touch %s" % (todays_dir)
        sts, out = commands.getstatusoutput(cmd)
