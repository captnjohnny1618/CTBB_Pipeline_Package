import sys
import os
import shutil
import logging
import random
import tempfile
from hashlib import md5
from time import strftime

import traceback

import pypeline as pype

from ctbb_pipeline_library import ctbb_pipeline_library as ctbb_plib
from pypeline import mutex

from enum import Enum

class qi_status(Enum):
    SUCCESS              = 0
    NO_RAW               = 1
    DOSE_REDUCTION_ERROR = 2
    PRM_CREATION_ERROR   = 3
    RECONSTRUCTION_ERROR = 4

class ctbb_queue_item:

    filepath        = None
    prm_filepath    = None
    case_id         = None # md5 hash of original file    
    dose            = None
    slice_thickness = None
    kernel          = None
    current_library = None
    device          = None
    device_mutex    = None
    run_dir         = None
    study_dir       = None

    def __init__(self,qi,device,library):
        self.qi_raw          = qi;
        
        qi=qi.split(',')

        self.filepath        = qi[0]
        self.dose            = qi[1]
        self.kernel          = qi[2]
        self.slice_thickness = qi[3]
        self.current_library = ctbb_plib(library)
        self.device          = mutex(device,self.current_library.mutex_dir)
        self.run_dir         = os.path.dirname(os.path.abspath(__file__))

        exit_status=qi_status.SUCCESS

    def __enter__(self):
        self.device.lock()
        return self

    def __exit__(self,type,value,traceback):
        self.device.unlock()

    def initialize_study(self):        
        study_dir_path=os.path.join(self.current_library.recon_dir,str(self.dose),( '%s_k%s_st%s' % (self.case_id,self.kernel,self.slice_thickness)))
        if not os.path.isdir(study_dir_path):
            os.makedirs(study_dir_path)

        self.study_dir=pype.study_directory(study_dir_path) # Constructor handles checking for valid directory, etc.
        
    def get_raw_data(self):
        exit_status=qi_status.SUCCESS;
        logging.info('Making sure we have raw data files')
        self.case_id=self.current_library.locate_raw_data(self.filepath)
        if not self.case_id:
            exit_status=qi_status.NO_RAW
        return exit_status

    def simulate_reduced_dose(self):
        exit_status=qi_status.SUCCESS;
        logging.info('Simulating reduced dose data')
        exit_code=self.current_library.locate_reduced_dose_data(self.filepath,self.dose)
        if exit_code != 0:
            exit_status = qi_status.DOSE_REDUCTION_ERROR
        return exit_status

    def make_final_prm(self):
        exit_status=qi_status.SUCCESS;
        logging.info('Assembling final PRM file')

        # Configure all of the paths we'll be using. Create any that don't already exist.
        base_filename=os.path.basename(self.filepath)
        prmb_filepath=os.path.join(self.current_library.raw_dir,base_filename + '.prmb');

        prm_dirpath=os.path.join(self.study_dir.path,'img')
        
        prm_dirpath=os.path.join(self.current_library.recon_dir,str(self.dose),( '%s_k%s_st%s' % (self.case_id,self.kernel,self.slice_thickness)))
        if not os.path.isdir(prm_dirpath):
            os.makedirs(prm_dirpath)
            
        prm_filepath=os.path.join(prm_dirpath,("%s_d%s_k%s_st%s.prm" % (self.case_id,self.dose,self.kernel,self.slice_thickness)));

        
        # Copy the base parameter file into the final output dir
        try :
            shutil.copy(prmb_filepath,prm_filepath)
            
            # Set up any strings we'll write to our final parameter file
            raw_data_dir=os.path.join(self.current_library.raw_dir,self.dose)
            raw_data_file=self.case_id
            recon_outdir=prm_dirpath
            recon_file=("%s_d%s_k%s_st%s.img" % (self.case_id,self.dose,self.kernel,self.slice_thickness))

            # Define a helper function
            def printout(f,a,b): 
                f.write(a+"\t"+str(b))
                f.write("\n")
            
            with open(prm_filepath,"a") as f_prm:
                printout(f_prm,"RawDataDir:",raw_data_dir)
                printout(f_prm,"RawDataFile:",raw_data_file)
                printout(f_prm,"OutputDir:",recon_outdir)
                printout(f_prm,"OutputFile:",recon_file)
                printout(f_prm,"ReconKernel:",self.kernel)
                printout(f_prm,"SliceThickness:",self.slice_thickness)
                printout(f_prm,"AdaptiveFiltration:","1.0")

            self.prm_filepath=prm_filepath
                
        except IOError as e:
            logging.info("Something went wrong when creating PRM file: %s" % e)
            exit_status=qi_status.PRM_CREATION_ERROR            
            
        return exit_status
        
    def dispatch_recon(self):
        exit_status=qi_status.SUCCESS;
        logging.info('Launching reconstruction')

        exit_code=self.__child_process__(('ctbb_recon -v --timing --device=%s %s' % (self.device.name.strip('dev'),self.prm_filepath)),self.prm_filepath+".stdout",self.prm_filepath+".stderr")
        if exit_code !=0:
            logging.info('Something went wrong with the reconstruction')
            exit_status=qi_status.RECONSTRUCTION_ERROR
        
        return exit_status
        
    def clean_up(self,exit_status):
        ## Move files into the proper study directories
        from glob import glob
        # Logs
        stdouts=glob(os.path.join(self.study_dir.path,'*.std*'))
        logs=glob(os.path.join(self.study_dir.path,'*.log'))
        for f in (stdouts+logs):
            #os.rename(f,os.path.join(self.study_dir.log_dir,os.path.basename(f)))
            shutil.move(f,os.path.join(self.study_dir.log_dir,os.path.basename(f)))

        # Images and metadata
        imgs=glob(os.path.join(self.study_dir.path,'*.img'))
        meta=glob(os.path.join(self.study_dir.path,'*.prm'))
        for f in (imgs+meta):
            #os.rename(f,os.path.join(self.study_dir.img_dir,os.path.basename(f)))
            shutil.move(f,os.path.join(self.study_dir.img_dir,os.path.basename(f)))
        
        ## Move job into ".proc/done" or ".proc/error" files

        if exit_status == qi_status.SUCCESS:
            done_mutex=mutex('done',self.current_library.mutex_dir)
            done_mutex.lock()

            with open(os.path.join(self.current_library.path,'.proc','done'),'a') as f:
                f.write("%s\n" % self.qi_raw)

            done_mutex.unlock()
        else:
            error_mutex=mutex('error',self.current_library.mutex_dir)
            error_mutex.lock()

            with open(os.path.join(self.current_library.path,'.proc','error'),'a') as f:
                f.write("%s:%s\n" % (self.qi_raw,str(exit_status)))

            error_mutex.unlock()
        
        logging.info('Cleaning up queue item')

    def __child_process__(self,c,stdout_file="/dev/null",stderr_file="/dev/null"):
        import subprocess
        
        with open(stdout_file,'w') as stdout_fid:
            with open(stderr_file,'w') as stderr_fid:
                logging.info('Dispatching system call: %s' % c)
                exit_code=subprocess.call(c.split(' '),stdout=stdout_fid,stderr=stderr_fid)
                logging.debug('System call exited with status %s' % str(exit_code))
                
        return exit_code
            
if __name__=="__main__":

    try:

        qi  = sys.argv[1]
        dev = sys.argv[2]
        lib = sys.argv[3]
    
        logdir=os.path.join(lib,'log');
        logfile=os.path.join(logdir,('%s_%s_qi.log' % (os.getpid(),strftime('%y%m%d_%H%M%S'))))
    
        if not os.path.isdir(logdir):
            os.mkdir(logdir);
    
        logging.basicConfig(format=('%(asctime)s %(message)s'), filename=logfile, level=logging.DEBUG)
                            
        with ctbb_queue_item(qi,dev,lib) as queue_item:
            logging.info('START: QUEUE ITEM')
            
            exit_status=qi_status.SUCCESS

            # Check for (and acquire if needed) 100% raw data
            logging.info('START: FETCH RAW')
            if exit_status==qi_status.SUCCESS:
                exit_status=queue_item.get_raw_data()
            logging.info('END: FETCH RAW')

            # Create the study directory
            logging.info('Creating new study directory')
            queue_item.initialize_study()
            logging.info('Done creating study directory')
                        
            # If doing reduced dose, check for (and simulate if needed) reduced-dose data
            logging.info('START: DOSE REDUCTION')
            if exit_status==qi_status.SUCCESS:    
                if str(queue_item.dose) != '100':        
                    exit_status=queue_item.simulate_reduced_dose()
            logging.info('END: DOSE REDUCTION')
                    
            # Assemble final parameter file
            if exit_status==qi_status.SUCCESS:        
                exit_status=queue_item.make_final_prm()
            
            # Launch reconstruction
            logging.info('START: RECON')
            if exit_status==qi_status.SUCCESS:
                exit_status=queue_item.dispatch_recon()
            logging.info('END: RECON')
            
            # Clean up after ourselves
            queue_item.clean_up(exit_status)

            logging.info('END: QUEUE ITEM')
            logging.info('FINAL STATUS: %d',exit_status)
            
        shutil.copy(logfile,os.path.join(queue_item.study_dir.log_dir,os.path.basename(logfile)))

    except NameError:
        exc_type, exc_value, exc_traceback = sys.exc_info()     
        lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        logging.info(''.join('ERROR TRACEBACK: ' + line for line in lines))
