import sys
import os
import logging
import time
from time import strftime
import shutil

import csv
import traceback

from ctbb_pipeline_library import ctbb_pipeline_library as ctbb_plib
from ctbb_pipeline_library import mutex

def isempty(obj):
    return not obj

class ctbb_daemon:

    daemon_mutex = None
    queue_mutex  = None
    pipeline_lib = None
    devices      = []
    queue        = None
    run_dir      = None

    def __init__(self,path):
        logging.info('CTBB Pipeline Daemon: launching')
        self.pipeline_lib=ctbb_plib(path)
        self.run_dir = os.path.dirname(os.path.abspath(__file__))
        self.daemon_mutex=mutex('daemon',self.pipeline_lib.mutex_dir)
        self.queue_mutex=mutex('queue',self.pipeline_lib.mutex_dir)
        self.get_devices()

        self.queue_mutex.lock()
        self.refresh_queue();
        self.queue_mutex.unlock()

    def __enter__(self):
        self.daemon_mutex.lock()
        return self

    def __exit__(self,type,value,traceback):
        logging.info('CTBB Pipeline Daemon: exiting')
        self.daemon_mutex.unlock()

    def __child_process__(self,c):
        import subprocess
        devnull=open('/dev/null','w')        
        #os.system("nohup %s >/dev/null 2>&1 &" % c); # Blocking call?
        subprocess.Popen(c.split(' '),stderr=devnull,stdout=devnull) # non-blocking

    def get_devices(self):
        import pycuda.autoinit
        import pycuda.driver as cuda

        n_devices=cuda.Device.count();

        logging.info('%d CUDA devices found' % n_devices);

        for i in range(n_devices):            
            self.devices.append(mutex(('dev%d' % i),self.pipeline_lib.mutex_dir))

            device=cuda.Device(i)
            attrs=device.get_attributes()

            if attrs[pycuda._driver.device_attribute.KERNEL_EXEC_TIMEOUT]:
                logging.info('Display attached to DEVICE %d' % i)

    def run(self):
        logging.info('CTBB Pipeline Daemon: RUNNING')
        
        while not isempty(self.queue):
            self.queue_mutex.lock(); 
        
            self.refresh_queue()

            logging.info(str(self.queue))
            
            for dev in self.get_empty_devices():
                if self.queue:
                    qi=self.pop_queue_item()
                    logging.debug('Popping %s from queue' % qi)
                    self.process_queue_item(qi,dev)
                else:
                    continue
            
            self.queue_mutex.unlock()

            self.pipeline_lib.refresh_recon_list();
            
            time.sleep(5)

    def pop_queue_item(self):
        # Removes first item in queue
        # Writes queue back to disk
        qi=self.queue.pop(0)
        logging.info(qi)

        with open(os.path.join(self.pipeline_lib.path,'.proc','queue'),'w') as f:
            for item in self.queue:
                f.write('%s\n' % item);        
        return qi

    def refresh_queue(self):
        with open(os.path.join(self.pipeline_lib.path,'.proc','queue')) as f:
            self.queue=f.read().splitlines();
        #logging.debug('Queue is:\n%s' % str(self.queue))

    def process_queue_item(self,qi,dev):
        logging.debug('Current queue item is: %s for device %s' % (qi,dev.name))
        call_command = ('python3 %s/ctbb_queue_item.py %s %s %s' % (self.run_dir,qi,dev.name,self.pipeline_lib.path))
        logging.debug('Sending to system call: %s' % call_command)
        self.__child_process__(call_command)
        
    def get_empty_devices(self):
        logging.info('Checking for device availability')
        empty_devices=[]
        for i in range(len(self.devices)):
            dev=self.devices[i]
            if not dev.check_state():
                logging.info('Device %d available for next job' % i)
                empty_devices.append(dev)

        return empty_devices
        
    def idle(self):
        logging.info('CTBB Pipeline Daemon: going idle')

    def grab_next_job(self):
        logging.info('CTBB Pipeline Daemon: Starting next queue item')
        
if __name__=="__main__":
    try:
        m=mutex('daemon',os.path.join(sys.argv[1],'.proc','mutex'))
    
        library_path=sys.argv[1]
    
        #logdir=os.path.join(os.path.dirname(os.path.abspath(__file__)),'log');
        logdir=os.path.join(library_path,'log');
        logfile=os.path.join(logdir,('%s_daemon.log' % strftime('%y%m%d_%H%M%S')))
    
        logging.basicConfig(format=('%(asctime)s %(message)s'),filename=logfile, level=logging.DEBUG)
    
        # If not running on current directory launch an instance of our daemon
        if not m.check_state():
            logging.info('No instance of CTBB Pipeline Daemon found for library')
            with ctbb_daemon(library_path) as ctbb_pd:
                ctbb_pd.run();
    
            shutil.copy(logfile,os.path.join(ctbb_pd.pipeline_lib.log_dir))
    
        # If instance already running on current dir, exit    
        else:
            logging.info('Instance of CTBB Pipeline Daemon already running.')
            # Clean up unneeded logfile if we're not debugging
            #if logging.getLogger().getEffectiveLevel() != logging.DEBUG:
            #    os.remove(logfile);
            sys.exit()

    except NameError:
        exc_type, exc_value, exc_traceback = sys.exc_info()     
        lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        logging.info(''.join('ERROR TRACEBACK: ' + line for line in lines))
